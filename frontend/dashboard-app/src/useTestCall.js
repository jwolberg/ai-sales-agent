// Test Call (IR8-T2): drive the real voice path with the operator's mic.
//
// mic -> POST /voice/offer (WebRTC) -> run_bot (Deepgram STT -> IntentRouterEngine -> Cartesia
// TTS) -> agent audio plays back through an <audio> element. Plain-connect: no dial/ring SFX and
// no energy-based pickup detection — we report `connected` as soon as the agent's track arrives.
// Signaling ported from frontend/client.js (the standalone /demo client).
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'

// Single offer/answer (no trickle ICE): wait for gathering to finish before sending the offer.
function waitForIceGathering(pc) {
  return new Promise((resolve) => {
    if (pc.iceGatheringState === 'complete') return resolve()
    const check = () => {
      if (pc.iceGatheringState === 'complete') {
        pc.removeEventListener('icegatheringstatechange', check)
        resolve()
      }
    }
    pc.addEventListener('icegatheringstatechange', check)
    setTimeout(resolve, 3000) // fallback so we never hang
  })
}

// status: idle | checking | connecting | connected | ended | error
export function useTestCall() {
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)
  const pcRef = useRef(null)
  const streamRef = useRef(null)
  const audioRef = useRef(null) // attached to a hidden <audio> by the component

  const stop = useCallback((nextStatus = 'ended') => {
    const pc = pcRef.current
    pcRef.current = null
    if (pc) {
      // Detach handlers before close() so the resulting 'closed' state change doesn't get
      // misread as an unexpected drop and overwrite a clean hang-up with an error.
      pc.ontrack = null
      pc.onconnectionstatechange = null
      pc.close()
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
    if (audioRef.current) audioRef.current.srcObject = null
    setStatus(nextStatus)
  }, [])

  const start = useCallback(async () => {
    setError(null)
    setStatus('checking')
    try {
      const s = await api.voiceStatus()
      if (!s.ready) {
        setError(`Voice not configured — missing: ${(s.missing_keys || []).join(', ')}`)
        setStatus('error')
        return
      }

      setStatus('connecting')
      const pc = new RTCPeerConnection({
        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
      })
      pcRef.current = pc
      pc.ontrack = (event) => {
        if (audioRef.current) audioRef.current.srcObject = event.streams[0]
        setStatus('connected') // agent track arrived — plain connect, no ring
      }
      pc.onconnectionstatechange = () => {
        if (['failed', 'disconnected', 'closed'].includes(pc.connectionState)) {
          // A clean hang-up sets status itself; only surface unexpected drops.
          if (pcRef.current) {
            setError(`Connection ${pc.connectionState}.`)
            stop('error')
          }
        }
      }

      // Echo cancellation/noise suppression so the agent's own voice isn't captured back into the
      // mic (defense in depth; the server also mutes STT while the agent speaks).
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
      streamRef.current = stream
      stream.getTracks().forEach((t) => pc.addTrack(t, stream))

      const offer = await pc.createOffer({ offerToReceiveAudio: true })
      await pc.setLocalDescription(offer)
      await waitForIceGathering(pc)

      const resp = await api.voiceOffer(pc.localDescription.sdp, pc.localDescription.type)
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}))
        setError(body.detail || `Offer failed (${resp.status}).`)
        stop('error')
        return
      }
      const answer = await resp.json()
      await pc.setRemoteDescription({ type: answer.type, sdp: answer.sdp })
    } catch (e) {
      // getUserMedia denial lands here (NotAllowedError) — surface a clear message.
      const msg =
        e && e.name === 'NotAllowedError'
          ? 'Microphone permission denied.'
          : e?.message || 'Failed to start test call.'
      setError(msg)
      stop('error')
    }
  }, [stop])

  // Tear down on unmount so a navigated-away call doesn't keep the mic open.
  useEffect(() => () => stop('idle'), [stop])

  const hangup = useCallback(() => stop('ended'), [stop])
  return { status, error, start, hangup, audioRef }
}
