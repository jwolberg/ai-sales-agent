import React, { useEffect, useState } from 'react'
import { api, subscribe } from './api.js'

function SimControls() {
  const [personas, setPersonas] = useState([])
  const [sel, setSel] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    api
      .simPersonas()
      .then((p) => {
        setPersonas(p)
        if (p[0]) setSel(p[0].key)
      })
      .catch(() => {})
  }, [])
  return (
    <div className="sim-controls">
      <select value={sel} onChange={(e) => setSel(e.target.value)}>
        {personas.map((p) => (
          <option key={p.key} value={p.key}>
            {p.name} → {p.target_leaf}
          </option>
        ))}
      </select>
      <button
        disabled={busy || !sel}
        onClick={async () => {
          setBusy(true)
          try {
            await api.startSim(sel)
          } finally {
            setTimeout(() => setBusy(false), 800)
          }
        }}
      >
        ▶ Start simulated call
      </button>
    </div>
  )
}

export default function App() {
  const [events, setEvents] = useState([])
  const [connected, setConnected] = useState(false)
  useEffect(() => {
    const unsub = subscribe((ev) => setEvents((prev) => [ev, ...prev].slice(0, 200)))
    setConnected(true)
    return unsub
  }, [])

  return (
    <div className="app">
      <header className="topbar">
        <h1>Nerdy Router — Call Center</h1>
        <span className={connected ? 'status live' : 'status'}>
          <span className="dot" /> live
        </span>
      </header>
      <SimControls />
      <section className="panel">
        <h2>Live events</h2>
        <ul className="events">
          {events.length === 0 && <li className="muted">Waiting for calls… start a simulated one above.</li>}
          {events.map((e, i) => (
            <li key={i}>
              <code className={`tag tag-${e.type}`}>{e.type}</code>
              <span className="cid">{e.call_id?.slice(0, 8)}</span>
              <span>{e.speaker || e.action || e.event_type || ''}</span>
              <span className="detail">{e.text || e.leaf || ''}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
