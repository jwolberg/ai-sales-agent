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
  startSim: (persona) =>
    fetch('/api/sim/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ persona }),
    }).then((r) => r.json()),

  // Test Call (IR8): the voice pipeline lives at /voice (not /api). voiceStatus reports
  // readiness/missing keys; voiceOffer does WebRTC signaling and returns the SDP answer.
  voiceStatus: () => getJSON('/voice/status'),
  voiceOffer: (sdp, type) =>
    fetch('/voice/offer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sdp, type }),
    }),
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
