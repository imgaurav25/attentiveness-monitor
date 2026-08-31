// httpClient.js
// --------------
// The one place that knows how to reach the FastAPI backend, shared by
// api.js (classroom mode) and meetingApi.js (meeting system). In dev,
// Vite proxies /api and /ws to http://localhost:8000 (see vite.config.js),
// so relative paths work identically in dev and behind a production
// reverse proxy. Set VITE_API_BASE_URL only if the frontend is served
// from a different origin than the backend (see .env.example).

export const BASE = import.meta.env.VITE_API_BASE_URL || ''

export async function req(method, path, body) {
  const res = await fetch(BASE + path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const data = await res.json()
      detail = data.detail || detail
    } catch {
      // ignore
    }
    throw new Error(detail)
  }
  return res.json()
}

export function wsUrl(path) {
  if (BASE) {
    const proto = BASE.startsWith('https') ? 'wss:' : 'ws:'
    const host = BASE.replace(/^https?:\/\//, '')
    return `${proto}//${host}${path}`
  }
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}${path}`
}

// Opens a WebSocket to the given path and calls onMessage(parsedJson) for
// every message. Returns a close() function. Auto-reconnects with backoff
// if the connection drops (e.g. backend restarts), unless noRetry is set
// (used for one-shot sockets like registration capture, which finish and
// close on their own).
export function connectSocket(path, onMessage, onStatusChange, { noRetry = false } = {}) {
  let ws = null
  let closedByUser = false
  let retryDelay = 1000

  function connect() {
    ws = new WebSocket(wsUrl(path))
    ws.onopen = () => {
      retryDelay = 1000
      onStatusChange && onStatusChange('connected')
    }
    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data)
        onMessage(msg)
      } catch {
        // ignore malformed message
      }
    }
    ws.onclose = () => {
      onStatusChange && onStatusChange('disconnected')
      if (!closedByUser && !noRetry) {
        setTimeout(connect, retryDelay)
        retryDelay = Math.min(retryDelay * 1.5, 10000)
      }
    }
    ws.onerror = () => {
      ws.close()
    }
  }

  connect()

  return {
    close: () => {
      closedByUser = true
      if (ws) ws.close()
    },
    send: (data) => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(data))
    },
  }
}

