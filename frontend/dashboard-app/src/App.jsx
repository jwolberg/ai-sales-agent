import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import { useLiveCalls } from './useLiveCalls.js'
import CallBoard from './CallBoard.jsx'
import CallDetail from './CallDetail.jsx'
import InsightsPanel from './InsightsPanel.jsx'
import Catalog from './Catalog.jsx'
import TestCall from './TestCall.jsx'

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
  const { calls, order } = useLiveCalls()
  const [selected, setSelected] = useState(null)
  const connected = order.length >= 0 // stream is opened by the hook
  const activeCount = Object.values(calls).filter((c) => c.status === 'active').length

  // The Test Call's own call for the in-panel billing link: newest web call that's live or has a
  // payment (order is newest-first). Lets TestCall show + text the link it just generated (PAY7-T2).
  const testCall = order
    .map((id) => calls[id])
    .find((c) => c && c.channel === 'web' && (c.status === 'active' || c.payment))

  // Auto-focus a call so the Transcript + Decision trace are visible without a manual click:
  // pick the newest one when nothing is selected, and follow a newly-arrived live call.
  useEffect(() => {
    if (!order.length) return
    const newest = order[0]
    if (!selected) setSelected(newest)
    else if (newest !== selected && calls[newest]?.status === 'active') setSelected(newest)
  }, [order, calls, selected])

  return (
    <div className="app">
      <header className="topbar">
        <h1>Nerdy Router — Call Center</h1>
        <span className={connected ? 'status live' : 'status'}>
          <span className="dot" /> live
        </span>
      </header>
      <SimControls />
      <TestCall liveCall={testCall} />
      <section className="panel">
        <h2>Insights</h2>
        <InsightsPanel activeCount={activeCount} />
      </section>
      <div className="layout">
        <section className="panel">
          <h2>Active &amp; recent calls</h2>
          <CallBoard calls={calls} order={order} selected={selected} onSelect={setSelected} />
        </section>
        <section className="panel">
          <h2>Call detail</h2>
          <CallDetail call={selected ? calls[selected] : null} />
        </section>
      </div>
      <section className="panel">
        <h2>What the agent offers</h2>
        <Catalog />
      </section>
    </div>
  )
}
