// api.js
// -------
// Classroom ("single shared camera") mode's REST + WebSocket client. See
// httpClient.js for the shared fetch/WebSocket plumbing, and meetingApi.js
// for the Google-Meet-style link-based meeting system's client.

import { req, connectSocket } from './httpClient'

export const api = {
  getStatus: () => req('GET', '/api/status'),
  start: () => req('POST', '/api/start'),
  stop: () => req('POST', '/api/stop'),
  setMode: (mode) => req('POST', '/api/mode', { mode }),
  setDelay: (seconds) => req('POST', '/api/delay', { seconds }),
  registerStart: (payload) => req('POST', '/api/register/start', payload),
  registerStatus: () => req('GET', '/api/register/status'),
  train: () => req('POST', '/api/train'),
  roster: () => req('GET', '/api/roster'),
  setSessionAttendees: (labelIds) => req('POST', '/api/session/attendees', { label_ids: labelIds }),
  getSessionAttendees: () => req('GET', '/api/session/attendees'),
  attentivenessEvents: (limit = 50) => req('GET', `/api/events/attentiveness?limit=${limit}`),
  unknownEvents: (limit = 50) => req('GET', `/api/events/unknown?limit=${limit}`),
  snapshotUrl: (filename) => `/api/snapshots/${filename}`,
}

// Opens a WebSocket to /ws/live and calls onMessage(parsedJson) for every
// message. Returns a close() function. Auto-reconnects with backoff if the
// connection drops (e.g. backend restarts).
export function connectLiveSocket(onMessage, onStatusChange) {
  const socket = connectSocket('/ws/live', onMessage, onStatusChange)
  return socket.close
}
