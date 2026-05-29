import { useEffect, useState } from 'react'
import { api, subscribe } from './api.js'

const emptyCall = (id) => ({
  call_id: id,
  channel: null,
  status: 'active',
  turns: [],
  decisions: [],
  reached_leaf: null,
  quoted_price: null,
  lastLatency: null,
  misQuotes: 0,
})

// Maintains a live map of calls from an initial REST load plus the SSE event stream.
export function useLiveCalls() {
  const [calls, setCalls] = useState({})
  const [order, setOrder] = useState([])

  useEffect(() => {
    api
      .calls()
      .then((rows) => {
        const map = {}
        const ord = []
        for (const r of rows) {
          map[r.call_id] = {
            ...emptyCall(r.call_id),
            ...r,
            status: r.ended_at ? 'ended' : 'active',
            turns: [],
            decisions: [],
          }
          ord.push(r.call_id)
        }
        setCalls(map)
        setOrder(ord)
      })
      .catch(() => {})

    return subscribe((ev) => {
      const id = ev.call_id
      if (!id) return
      setCalls((prev) => {
        const c = { ...(prev[id] || emptyCall(id)) }
        if (ev.type === 'call_started') {
          c.channel = ev.channel
          c.status = 'active'
        } else if (ev.type === 'turn') {
          c.turns = [...c.turns, { speaker: ev.speaker, text: ev.text }]
          if (ev.latency_ms != null) c.lastLatency = ev.latency_ms
        } else if (ev.type === 'decision') {
          c.decisions = [
            ...c.decisions,
            {
              action: ev.action,
              reason: ev.reason,
              confidence: ev.confidence,
              slots: ev.slots,
              leaf: ev.leaf,
            },
          ]
          if (ev.leaf) c.reached_leaf = ev.leaf
        } else if (ev.type === 'kpi') {
          if (ev.event_type === 'mis_quote_blocked') c.misQuotes += 1
        } else if (ev.type === 'call_ended') {
          c.status = 'ended'
          if (ev.reached_leaf != null) c.reached_leaf = ev.reached_leaf
          if (ev.quoted_price != null) c.quoted_price = ev.quoted_price
        }
        return { ...prev, [id]: c }
      })
      setOrder((prev) => (prev.includes(id) ? prev : [id, ...prev]))
    })
  }, [])

  return { calls, order }
}
