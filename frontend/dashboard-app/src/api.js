// REST + SSE client for the call-center dashboard. The API lives at /api on the same origin.

async function getJSON(path) {
  const r = await fetch(path)
  if (!r.ok) throw new Error(`${path} -> ${r.status}`)
  return r.json()
}

export const api = {
  calls: () => getJSON('/api/calls'),
  call: (id) => getJSON(`/api/calls/${id}`),
  routerMetrics: () => getJSON('/api/router-metrics'),
  catalog: () => getJSON('/api/catalog'),
  simPersonas: () => getJSON('/api/sim/personas'),
  // Throws with the server's detail on a non-2xx (e.g. 429 when too many calls are live).
  startSim: async (persona) => {
    const r = await fetch('/api/sim/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ persona }),
    })
    const body = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(body.detail || `start failed (${r.status})`)
    return body
  },

  // Test Call (IR8): the voice pipeline lives at /voice (not /api). voiceStatus reports
  // readiness/missing keys; voiceOffer does WebRTC signaling and returns the SDP answer.
  voiceStatus: () => getJSON('/voice/status'),
  voiceOffer: (sdp, type) =>
    fetch('/voice/offer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sdp, type }),
    }),

  // Text a call's latest payment link to a number (PAY7-T2). Resolves to the JSON body; throws on
  // a non-2xx so the caller can surface the error detail.
  sendPaymentSms: async (callId, phone) => {
    const r = await fetch(`/api/calls/${callId}/send-payment-sms`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone }),
    })
    const body = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(body.detail || `send failed (${r.status})`)
    return body
  },
}

// Subscribe to the live event stream. Returns an unsubscribe function.
export function subscribe(onEvent) {
  const es = new EventSource('/api/stream')
  es.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data))
    } catch {
      /* keepalive / comment line */
    }
  }
  return () => es.close()
}
