import React from 'react'
import { useTestCall } from './useTestCall.js'

// Test Call (IR8-T3): speak to the agent with your own mic and hear it route in real time.
// The call records as channel="web", so it appears on the call board with its live transcript
// + decision trace — this control just starts/stops the audio session.
const STATUS_LABEL = {
  idle: 'Idle.',
  checking: 'Checking voice configuration…',
  connecting: 'Connecting — allow microphone access…',
  connected: 'Connected — speak to the agent.',
  ended: 'Call ended.',
  error: '',
}

export default function TestCall() {
  const { status, error, start, hangup, audioRef } = useTestCall()
  const live = status === 'checking' || status === 'connecting' || status === 'connected'

  return (
    <div className="sim-controls">
      <button disabled={live} onClick={start}>
        ▶ Start Test Call
      </button>
      <button disabled={!live} onClick={hangup}>
        ■ Hang up
      </button>
      <span className="muted">{status === 'error' ? error : STATUS_LABEL[status]}</span>
      <audio ref={audioRef} autoPlay playsInline />
    </div>
  )
}
