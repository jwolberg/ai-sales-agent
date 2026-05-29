import React, { useEffect, useState } from 'react'
import { api } from './api.js'

const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`)
const ms = (v) => (v == null ? '—' : `${Math.round(v)}ms`)

function Tile({ k, v, cls = '' }) {
  return (
    <div className={`tile ${cls}`}>
      <div className="v">{v}</div>
      <div className="k">{k}</div>
    </div>
  )
}

// DB-derived router KPIs (Classification Accuracy needs ground truth and comes from the benchmark,
// not this live endpoint). Polls every few seconds + shows the live active-call count.
export default function InsightsPanel({ activeCount }) {
  const [m, setM] = useState(null)
  useEffect(() => {
    let alive = true
    const load = () =>
      api
        .routerMetrics()
        .then((d) => alive && setM(d))
        .catch(() => {})
    load()
    const t = setInterval(load, 4000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  return (
    <div className="tiles">
      <Tile k="active calls" v={activeCount} cls={activeCount > 0 ? 'good' : ''} />
      <Tile k="total calls" v={m?.total_calls ?? '—'} />
      <Tile k="leaf reached" v={pct(m?.leaf_reached_rate)} />
      <Tile k="quoted" v={pct(m?.quote_rate)} />
      <Tile k="escalation" v={pct(m?.escalation_rate)} />
      <Tile k="mis-quote" v={pct(m?.mis_quote_rate)} cls={m?.mis_quote_rate ? 'bad' : 'good'} />
      <Tile k="latency p50" v={ms(m?.turn_latency_ms_p50)} />
      <Tile k="latency p95" v={ms(m?.turn_latency_ms_p95)} />
      <Tile k="paid" v={pct(m?.paid_rate)} cls={m?.payments_paid ? 'good' : ''} />
      <Tile k="revenue" v={m?.revenue != null ? `$${m.revenue}` : '—'} />
    </div>
  )
}
