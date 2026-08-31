// meetingApi.js
// --------------
// REST + WebSocket client for the Google-Meet-style link-based meeting
// system. See httpClient.js for the shared fetch/WebSocket plumbing.

import { req, connectSocket } from './httpClient'

export const meetingApi = {
  createMeeting: (title) => req('POST', '/api/meetings', { title: title || '' }),
  getMeeting: (meetingId) => req('GET', `/api/meetings/${meetingId}`),
  getMeetingRoster: (meetingId) => req('GET', `/api/meetings/${meetingId}/roster`),

  registerStart: (meetingId, payload) => req('POST', `/api/meetings/${meetingId}/register/start`, payload),
  registerStatus: (token) => req('GET', `/api/meetings/register/status?token=${encodeURIComponent(token)}`),

  join: (meetingId, payload) => req('POST', `/api/meetings/${meetingId}/join`, payload),
  leave: (meetingId, participantId) =>
    req('POST', `/api/meetings/${meetingId}/leave`, { participant_id: participantId }),

  getEvents: (meetingId, limit = 50) => req('GET', `/api/meetings/${meetingId}/events?limit=${limit}`),

  snapshotUrl: (filename) => `/api/snapshots/${filename}`,
  logDownloadUrl: () => `/api/download/log`,
}

// One-shot socket: the browser streams frames while registering a NEW
// person (during the pre-join flow), and the socket closes itself once
// enough images are captured (see the 'done' field in each progress message).
export function connectRegistrationSocket(token, onMessage, onStatusChange) {
  return connectSocket(`/ws/meetings/register/${token}`, onMessage, onStatusChange, { noRetry: true })
}

// Long-lived socket: streams this participant's own camera frames for the
// whole meeting, and receives their own live attentiveness/identity status
// back (self-view only -- alerts to the host go over a separate socket).
export function connectParticipantSocket(meetingId, participantId, onMessage, onStatusChange) {
  return connectSocket(`/ws/meetings/${meetingId}/participant/${participantId}`, onMessage, onStatusChange)
}

// Host dashboard socket: receives every attentiveness / impersonation /
// extra-person alert for the whole meeting, live.
export function connectHostSocket(meetingId, onMessage, onStatusChange) {
  return connectSocket(`/ws/meetings/${meetingId}/host`, onMessage, onStatusChange)
}

// Custom WebRTC signaling channel. No Jitsi/third-party meeting UI is used.
export function connectMeetingSignalSocket(meetingId, participantId, onMessage, onStatusChange) {
  return connectSocket(`/ws/meetings/${meetingId}/signal/${participantId}`, onMessage, onStatusChange)
}
