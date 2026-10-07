import React, { useState } from 'react'
import { api } from './api.js'
import { useTestCall } from './useTestCall.js'

// Test Call (IR8-T3): speak to the agent with your own mic and hear it route in real time.
// The call records as channel="web", so it appears on the call board with its live transcript
// + decision trace — this control just starts/stops the audio session. When the agent creates a
// billing link during the call, it's surfaced here too (PAY7-T2).
const STATUS_LABEL = {
  idle: 'Idle.',
  checking: 'Checking voice configuration…',
  connecting: 'Connecting — allow microphone access…',
  connected: 'Connected — speak to the agent.',
  ended: 'Call ended.',
  error: '',
}

// Shown once the agent has generated a payment link for this call: open it, or text it to a number
// (a browser mic call has no caller ID, so we ask for one).
function BillingLink({ call }) {
  const [phone, setPhone] = useState('')
  const [sms, setSms] = useState(null) // { ok, msg }
  const [busy, setBusy] = useState(false)
  const payment = call?.payment
  if (!payment?.url) return null

  const text = async () => {
    setBusy(true)
    setSms(null)
    try {
      await api.sendPaymentSms(call.call_id, phone)
      setSms({ ok: true, msg: `Texted to ${phone}.` })
    } catch (e) {
      setSms({ ok: false, msg: e.message })
    } finally {
      setBusy(false)
    }
  }

  const paid = payment.status === 'paid'
  return (
    <div className="panel" style={{ marginTop: 12 }}>
      <h2>Billing link {paid ? '· paid ✓' : `· ${payment.kind}`}</h2>
      <div className="row" style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <a href={payment.url} target="_blank" rel="noreferrer">
          {payment.url}
        </a>
        {payment.amount != null && <span className="muted">${payment.amount}</span>}
      </div>
      {!paid && (
        <div className="sim-controls" style={{ marginTop: 8 }}>
          <input
            type="tel"
            placeholder="+15551234567"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
          />
          <button disabled={busy || !phone.trim()} onClick={text}>
            Text link
          </button>
          {sms && (
            <span className="muted" style={{ color: sms.ok ? 'var(--good)' : 'var(--bad)' }}>
              {sms.msg}
            </span>
          )}
        </div>
      )}
    </div>
  )
}

// Dev instance = the Vite dev server (`npm run dev`) OR the app served from a loopback host (e.g.
// uvicorn on 127.0.0.1 serving the built bundle). Keying off build mode alone isn't enough — the
// production *bundle* served locally is still a "dev instance". Only the deployed (non-loopback)
// host counts as production.
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '0.0.0.0', '::1', '[::1]'])

function isDevInstance() {
  if (import.meta.env.DEV) return true
  return typeof window !== 'undefined' && LOOPBACK_HOSTS.has(window.location.hostname)
}

export default function TestCall({ liveCall }) {
  const { status, error, start, hangup, audioRef } = useTestCall()
  const live = status === 'checking' || status === 'connecting' || status === 'connected'

  // The browser mic Test Call only works against a local backend (WebRTC needs inbound UDP, which
  // Cloud Run can't do). Show the buttons on a dev instance; production points callers at the
  // Twilio number instead.
  if (!isDevInstance()) {
    return (
      <div className="sim-controls">
        <span style={{ color: '#ff7a00', fontSize: '16px' }}>
          Call us at 1-986-786-3739
        </span>
      </div>
    )
  }

  return (
    <>
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
      <BillingLink call={liveCall} />
    </>
  )
}
