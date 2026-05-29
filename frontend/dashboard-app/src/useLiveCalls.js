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

// Maintains a live map of calls from the SSE event stream, with a periodic REST reconcile so the
// board self-heals (e.g. if the first load raced a transient API error) and picks up calls that
// finished before the page opened.
export function useLiveCalls() {
  const [calls, setCalls] = useState({})
  const [order, setOrder] = useState([])

  useEffect(() => {
    let alive = true

    // Merge REST summaries in without clobbering live-accumulated turns/decisions.
    const reconcile = () =>
      api
        .calls()
        .then((rows) => {
          if (!alive) return
          setCalls((prev) => {
            const next = { ...prev }
            for (const r of rows) {
              const ex = next[r.call_id] || emptyCall(r.call_id)
              next[r.call_id] = {
                ...ex,
                ...r,
                status: r.ended_at ? 'ended' : ex.status,
                turns: ex.turns, // keep streamed turns/decisions; summaries don't carry them
                decisions: ex.decisions,
              }
            }
            return next
          })
          setOrder((prev) => {
            const ids = rows.map((r) => r.call_id) // API returns newest-first
            return [...ids, ...prev.filter((id) => !ids.includes(id))]
          })
        })
        .catch(() => {})

    reconcile()
    const timer = setInterval(reconcile, 8000)

    const unsub = subscribe((ev) => {
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

    return () => {
      alive = false
      clearInterval(timer)
      unsub()
    }
  }, [])

  return { calls, order }
}
