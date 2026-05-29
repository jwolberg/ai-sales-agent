import React, { useEffect, useState } from 'react'
import { api } from './api.js'

// What the agent offers: the two options it routes between, their tests/subjects, each with its
// authoritative price and a short explainer. Reference for the operator.
export default function Catalog() {
  const [categories, setCategories] = useState([])
  useEffect(() => {
    api
      .catalog()
      .then((d) => setCategories(d.categories))
      .catch(() => {})
  }, [])

  return (
    <div className="catalog">
      {categories.map((c) => (
        <div key={c.key} className="cat">
          <div className="cat-head">
            <span className="cat-name">{c.label}</span>
            <span className="muted">{c.description}</span>
          </div>
          {c.groups.map((g, i) => (
            <div key={i} className="cat-group">
              {g.label && <div className="group-label">{g.label}</div>}
              {g.leaves.map((l) => (
                <div key={l.id} className="offering" title={l.id}>
                  <div className="offering-row">
                    <span className="off-name">{l.label}</span>
                    <span className="off-price">
                      {l.display || '—'}
                      {l.unit ? ` ${l.unit}` : ''}
                    </span>
                  </div>
                  {l.summary && <div className="off-summary">{l.summary}</div>}
                </div>
              ))}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}
