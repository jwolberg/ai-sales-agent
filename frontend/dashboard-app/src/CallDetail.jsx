import React, { useEffect, useState } from 'react'
import { api } from './api.js'

// Shows a call's streaming transcript + decision trace. For a live call we render the
// accumulating live object; for a historical one (no streamed turns) we fetch the snapshot.
export default function CallDetail({ call }) {
  const [fetched, setFetched] = useState(null)

  useEffect(() => {
    setFetched(null)
    if (call && call.status === 'ended' && call.turns.length === 0) {
      api.call(call.call_id).then(setFetched).catch(() => {})
    }
  }, [call?.call_id, call?.status, call?.turns.length])

  if (!call) return <p className="muted">Select a call to see its transcript and decisions.</p>

  const turns = call.turns.length ? call.turns : fetched?.turns || []
  const decisions = call.decisions.length ? call.decisions : fetched?.decisions || []
  const leaf = call.reached_leaf || fetched?.reached_leaf
  const price = call.quoted_price ?? fetched?.quoted_price
  // Prefer the full payment list from the fetched snapshot; fall back to the live latest-payment.
  const payments = fetched?.payments?.length ? fetched.payments : call.payment ? [call.payment] : []

  return (
    <div>
      <div className="row" style={{ marginBottom: 10 }}>
        <span className="leaf">{leaf || 'classifying…'}</span>
        <span>{price != null ? `$${price}` : ''}</span>
      </div>

      <h2>Transcript</h2>
      <div className="transcript">
        {turns.length === 0 && <p className="muted">No turns yet.</p>}
        {turns.map((t, i) => (
          <div key={i} className={`bubble ${t.speaker}`}>
            <div className="who">{t.speaker}</div>
            {t.text}
          </div>
        ))}
      </div>

      <h2 style={{ marginTop: 16 }}>Decision trace</h2>
      <ul className="trace">
        {decisions.length === 0 && <li className="muted">No decisions yet.</li>}
        {decisions.map((d, i) => (
          <li key={i}>
            <span className="action">{d.action || d.selected_action}</span>
            {d.confidence != null && <span className="muted"> · conf {d.confidence}</span>}
            {d.leaf && <span> · {d.leaf}</span>}
            <div className="slots">{JSON.stringify(d.slots || {})}</div>
            {d.reason && <div className="muted">{d.reason}</div>}
          </li>
        ))}
      </ul>

      {payments.length > 0 && (
        <>
          <h2 style={{ marginTop: 16 }}>Payments</h2>
          <ul className="trace">
            {payments.map((p, i) => {
              const paid = p.status === 'paid'
              return (
                <li key={p.payment_id || i}>
                  <span className="action" style={{ color: paid ? 'var(--good)' : 'var(--warn)' }}>
                    {p.kind} · {p.status}
                  </span>
                  {p.amount != null && <span> · ${p.amount}</span>}
                  {p.url && (
                    <div>
                      <a href={p.url} target="_blank" rel="noreferrer">
                        {p.url}
                      </a>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        </>
      )}
    </div>
  )
}
