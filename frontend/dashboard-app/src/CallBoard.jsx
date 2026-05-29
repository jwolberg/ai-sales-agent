import React from 'react'

export default function CallBoard({ calls, order, selected, onSelect }) {
  if (order.length === 0) {
    return <p className="muted">No calls yet — start a simulated one above.</p>
  }
  return (
    <div className="board">
      {order.map((id) => {
        const c = calls[id]
        if (!c) return null
        return (
          <div
            key={id}
            className={`call-card ${c.status === 'active' ? 'active' : ''} ${
              selected === id ? 'selected' : ''
            }`}
            onClick={() => onSelect(id)}
          >
            <div className="row">
              <span>{c.channel || 'call'}</span>
              <span>{c.status === 'active' ? '● live' : 'ended'}</span>
            </div>
            <div className="leaf">{c.reached_leaf || '—'}</div>
            <div className="row">
              <span>{c.quoted_price != null ? `$${c.quoted_price}` : 'no quote'}</span>
              <span>{c.lastLatency != null ? `${Math.round(c.lastLatency)}ms` : ''}</span>
            </div>
            {c.misQuotes > 0 && <div className="row" style={{ color: 'var(--bad)' }}>⚠ mis-quote blocked</div>}
          </div>
        )
      })}
    </div>
  )
}
