import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useLocation, useNavigate } from 'react-router-dom'
import { meetingApi, connectParticipantSocket, connectHostSocket, connectMeetingSignalSocket } from '../meetingApi'
import { openCamera, stopStream, captureFrameBase64 } from '../cameraUtils'
import MeetingAlertsFeed from '../components/MeetingAlertsFeed'
import { speakAttentivenessAlert, speakIdentityMismatchAlert, speakExtraPersonAlert } from '../voiceAlert'

const STATUS_COLOR = {
  Attentive: 'bg-emerald-600',
  'Away from camera': 'bg-slate-600',
  'Identity mismatch': 'bg-red-600',
}

function statusColor(status) {
  if (STATUS_COLOR[status]) return STATUS_COLOR[status]
  if (status && status.includes('(')) return 'bg-amber-600'
  return 'bg-slate-600'
}

function displayName(participant, selfId) {
  return participant?.participant_id === selfId ? 'You' : (participant?.name || 'Participant')
}

function gridStyle(count) {
  const columns = count <= 1 ? 1 : count === 2 ? 2 : count <= 4 ? 2 : count <= 9 ? 3 : 4
  const rows = Math.max(1, Math.ceil(count / columns))
  return {
    gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
    gridTemplateRows: `repeat(${rows}, minmax(0, 1fr))`,
  }
}

export default function MeetingRoom() {
  const { meetingId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const saved = (() => { try { return JSON.parse(sessionStorage.getItem(`attn-participant:${meetingId}`) || 'null') } catch { return null } })()
  const { participantId, name, isHost } = location.state || saved || {}

  const localVideoRef = useRef(null)
  const localStreamRef = useRef(null)
  const signalSocketRef = useRef(null)
  const participantSocketRef = useRef(null)
  const hostSocketRef = useRef(null)
  const intervalRef = useRef(null)
  const peersRef = useRef(new Map())
  const remoteVideoRefs = useRef(new Map())

  const [selfStatus, setSelfStatus] = useState('Connecting…')
  const [wsStatus, setWsStatus] = useState('disconnected')
  const [signalStatus, setSignalStatus] = useState('disconnected')
  const [participants, setParticipants] = useState({})
  const [remoteStreams, setRemoteStreams] = useState({})
  const [hostEvents, setHostEvents] = useState([])
  const [urgentToast, setUrgentToast] = useState('')
  const [leaving, setLeaving] = useState(false)
  const [muted, setMuted] = useState(false)
  const [audioAvailable, setAudioAvailable] = useState(false)
  const [cameraOff, setCameraOff] = useState(false)
  const [sharing, setSharing] = useState(false)

  const allParticipants = useMemo(() => {
    const self = { participant_id: participantId, name, is_host: Boolean(isHost), connected: true }
    return Object.values({ ...participants, [participantId]: self })
  }, [participants, participantId, name, isHost])

  useEffect(() => {
    if (!participantId) {
      navigate(`/meeting/${meetingId}`, { replace: true })
      return
    }

    let disposed = false

    const sendSignal = (target, signal) => {
      signalSocketRef.current?.send({ type: 'webrtc_signal', target, signal })
    }

    const closePeer = (remoteId) => {
      const pc = peersRef.current.get(remoteId)
      if (pc) pc.close()
      peersRef.current.delete(remoteId)
      remoteVideoRefs.current.delete(remoteId)
      setRemoteStreams((prev) => {
        const next = { ...prev }
        delete next[remoteId]
        return next
      })
      setParticipants((prev) => {
        const next = { ...prev }
        delete next[remoteId]
        return next
      })
    }

    const ensurePeer = async (remoteParticipant) => {
      if (!remoteParticipant?.participant_id || remoteParticipant.participant_id === participantId) return
      const remoteId = remoteParticipant.participant_id
      setParticipants((prev) => ({ ...prev, [remoteId]: remoteParticipant }))
      let pc = peersRef.current.get(remoteId)
      if (!pc) {
        pc = new RTCPeerConnection({
          iceServers: [
            { urls: 'stun:stun.l.google.com:19302' },
            { urls: 'stun:stun1.l.google.com:19302' },
          ],
        })
        peersRef.current.set(remoteId, pc)
        const stream = localStreamRef.current
        stream?.getTracks().forEach((track) => pc.addTrack(track, stream))
        pc.onicecandidate = (event) => {
          if (event.candidate) sendSignal(remoteId, { kind: 'candidate', candidate: event.candidate })
        }
        pc.ontrack = (event) => {
          const stream = event.streams?.[0]
          if (stream) {
            setRemoteStreams((prev) => ({ ...prev, [remoteId]: stream }))
          }
        }
        pc.onconnectionstatechange = () => {
          if (['failed', 'closed', 'disconnected'].includes(pc.connectionState)) {
            if (pc.connectionState === 'failed') pc.restartIce?.()
          }
        }
      }
      // Deterministic offerer avoids SDP offer collisions: the lexicographically
      // smaller participant id initiates the connection.
      if (participantId < remoteId && pc.signalingState === 'stable') {
        const offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        sendSignal(remoteId, { kind: 'offer', description: pc.localDescription })
      }
    }

    const handleSignal = async (msg) => {
      if (msg.type === 'webrtc_peers') {
        for (const p of msg.participants || []) await ensurePeer(p)
        return
      }
      if (msg.type === 'participant_joined') {
        if (msg.participant?.participant_id !== participantId) await ensurePeer(msg.participant)
        return
      }
      if (msg.type === 'participant_left') {
        if (msg.participant?.participant_id) closePeer(msg.participant.participant_id)
        return
      }
      if (msg.type !== 'webrtc_signal') return
      const remoteId = msg.from
      const signal = msg.signal || {}
      const remoteParticipant = participants[remoteId] || { participant_id: remoteId, name: 'Participant' }
      await ensurePeer(remoteParticipant)
      const pc = peersRef.current.get(remoteId)
      if (!pc) return
      try {
        if (signal.kind === 'offer') {
          await pc.setRemoteDescription(signal.description)
          const answer = await pc.createAnswer()
          await pc.setLocalDescription(answer)
          sendSignal(remoteId, { kind: 'answer', description: pc.localDescription })
        } else if (signal.kind === 'answer') {
          if (pc.signalingState === 'have-local-offer') await pc.setRemoteDescription(signal.description)
        } else if (signal.kind === 'candidate' && signal.candidate) {
          try { await pc.addIceCandidate(signal.candidate) } catch { /* remote may have changed */ }
        }
      } catch (err) {
        console.warn('WebRTC signaling error', err)
      }
    }

    openCamera({ audio: true })
      .then(async (stream) => {
        if (disposed) {
          stopStream(stream)
          return
        }
        localStreamRef.current = stream
        setAudioAvailable(stream.getAudioTracks().length > 0)
        if (localVideoRef.current) localVideoRef.current.srcObject = stream

        const participantSocket = connectParticipantSocket(
          meetingId, participantId,
          (msg) => {
            if (msg.type === 'self_status') setSelfStatus(msg.data.status)
            else if (msg.type === 'attentiveness_alert') speakAttentivenessAlert(msg.data, { self: true })
            else if (msg.type === 'impersonation_alert') speakIdentityMismatchAlert(msg.data, { self: true })
            else if (msg.type === 'extra_person_alert') speakExtraPersonAlert(msg.data, { self: true })
          },
          setWsStatus,
        )
        participantSocketRef.current = participantSocket

        intervalRef.current = setInterval(() => {
          const b64 = captureFrameBase64(localVideoRef.current)
          if (b64) participantSocket.send({ type: 'frame', data: b64 })
        }, 1000)

        const signalSocket = connectMeetingSignalSocket(meetingId, participantId, handleSignal, setSignalStatus)
        signalSocketRef.current = signalSocket
      })
      .catch((err) => {
        console.error(err)
        setSelfStatus('Camera unavailable')
      })

    if (isHost) {
      hostSocketRef.current = connectHostSocket(meetingId, (msg) => {
        if (msg.type === 'attentiveness_alert') {
          setUrgentToast(`⏰ ${msg.data.is_self_for_host ? 'You' : (msg.data.who || 'A participant')} — ${msg.data.reason} (${msg.data.elapsed}s)`)
          speakAttentivenessAlert(msg.data, { self: false })
          setHostEvents((prev) => [msg, ...prev].slice(0, 200))
          setTimeout(() => setUrgentToast(''), 6000)
        } else if (msg.type === 'impersonation_alert') {
          setUrgentToast(`🚨 ${msg.data.message}`)
          speakIdentityMismatchAlert(msg.data, { self: false })
          setTimeout(() => setUrgentToast(''), 8000)
          setHostEvents((prev) => [msg, ...prev].slice(0, 200))
        } else if (msg.type === 'extra_person_alert') {
          setUrgentToast(`⚠ ${msg.data.message}`)
          speakExtraPersonAlert(msg.data, { self: false })
          setTimeout(() => setUrgentToast(''), 6000)
          setHostEvents((prev) => [msg, ...prev].slice(0, 200))
        } else if (msg.type === 'attentiveness_event') {
          setHostEvents((prev) => [msg, ...prev].slice(0, 200))
        }
      })
      meetingApi.getEvents(meetingId, 100).then((events) => {
        setHostEvents(events.map((data) => ({ type: data.reason ? 'attentiveness_event' : 'extra_person_alert', data })))
      }).catch(() => {})
    }

    return () => {
      disposed = true
      clearInterval(intervalRef.current)
      participantSocketRef.current?.close()
      signalSocketRef.current?.close()
      hostSocketRef.current?.close()
      peersRef.current.forEach((pc) => pc.close())
      peersRef.current.clear()
      stopStream(localStreamRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const toggleMute = () => {
    const tracks = localStreamRef.current?.getAudioTracks?.() || []
    if (!tracks.length) return
    const nextMuted = !muted
    tracks.forEach((track) => { track.enabled = !nextMuted })
    setMuted(nextMuted)
  }

  const toggleCamera = () => {
    const track = localStreamRef.current?.getVideoTracks?.()[0]
    if (!track) return
    track.enabled = !track.enabled
    setCameraOff(!track.enabled)
  }

  const toggleShare = async () => {
    if (!localStreamRef.current) return
    if (!sharing) {
      try {
        const screen = await navigator.mediaDevices.getDisplayMedia({ video: true })
        const screenTrack = screen.getVideoTracks()[0]
        const cameraTrack = localStreamRef.current.getVideoTracks()[0]
        peersRef.current.forEach((pc) => {
          const sender = pc.getSenders().find((s) => s.track?.kind === 'video')
          if (sender) sender.replaceTrack(screenTrack)
        })
        if (localVideoRef.current) localVideoRef.current.srcObject = screen
        screenTrack.onended = () => {
          peersRef.current.forEach((pc) => {
            const sender = pc.getSenders().find((s) => s.track?.kind === 'video')
            if (sender) sender.replaceTrack(cameraTrack)
          })
          if (localVideoRef.current) localVideoRef.current.srcObject = localStreamRef.current
          setSharing(false)
        }
        setSharing(true)
      } catch { /* user cancelled */ }
    }
  }

  const handleLeave = async () => {
    setLeaving(true)
    try { await meetingApi.leave(meetingId, participantId) } catch { /* leaving anyway */ }
    sessionStorage.removeItem(`attn-participant:${meetingId}`)
    navigate('/')
  }

  if (!participantId) return null

  return (
    <div className="min-h-screen bg-[#070b12] text-slate-100 flex flex-col">
      {urgentToast && (
        <div className="bg-red-950/90 border-b border-red-700 text-red-200 text-sm text-center py-2 px-4">
          {urgentToast}
        </div>
      )}

      <header className="h-14 shrink-0 px-4 flex items-center justify-between border-b border-slate-800 bg-[#0b111b]">
        <div>
          <div className="font-semibold">Attentiveness Meeting</div>
          <div className="text-[11px] text-slate-500">{isHost ? 'Host' : 'Participant'} · {allParticipants.length} connected</div>
        </div>
        <div className="flex items-center gap-2 text-[11px]">
          <span className="px-2 py-1 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-900">{signalStatus === 'connected' ? 'Live' : 'Connecting'}</span>
          <span className="px-2 py-1 rounded-full bg-slate-900 border border-slate-800">{wsStatus === 'connected' ? 'Monitoring' : 'Reconnecting'}</span>
        </div>
      </header>

      <div className="flex-1 flex flex-col lg:flex-row gap-3 p-3 min-h-0">
        <main className="flex-1 min-w-0 flex flex-col min-h-0">
          <div className="flex-1 grid gap-3 min-h-0 auto-rows-fr" style={gridStyle(allParticipants.length)}>
            <div className="relative min-h-0 rounded-xl overflow-hidden bg-black border border-slate-800 shadow-lg">
              <video ref={localVideoRef} autoPlay muted playsInline className="w-full h-full object-cover" />
              <div className="absolute bottom-2 left-2 px-2 py-1 rounded bg-black/60 text-xs">You {isHost ? '· Host' : ''}</div>
              <div className="absolute top-2 right-2 px-2 py-1 rounded bg-black/60 text-[11px]">{selfStatus}</div>
            </div>

            {Object.entries(remoteStreams).map(([remoteId, stream]) => {
              const p = participants[remoteId] || { participant_id: remoteId, name: 'Participant' }
              return <RemoteTile key={remoteId} stream={stream} participant={p} selfId={participantId} />
            })}
          </div>

          <div className="mt-3 rounded-2xl border border-slate-800 bg-[#0b111b] px-4 py-3 flex items-center justify-center gap-2">
            <button onClick={toggleMute} disabled={!audioAvailable} className={`h-11 px-4 rounded-full border ${muted ? 'bg-red-900/60 border-red-700' : 'bg-slate-800 border-slate-700'} text-sm`}>{muted ? '🔇 Unmute' : '🎤 Mute'}</button>
            <button onClick={toggleCamera} className={`h-11 px-4 rounded-full border ${cameraOff ? 'bg-red-900/60 border-red-700' : 'bg-slate-800 border-slate-700'} text-sm`}>{cameraOff ? '📷 Turn camera on' : '📹 Camera'}</button>
            <button onClick={toggleShare} className="h-11 px-4 rounded-full bg-slate-800 border border-slate-700 text-sm">🖥 {sharing ? 'Sharing' : 'Share screen'}</button>
            <button onClick={handleLeave} disabled={leaving} className="h-11 px-5 rounded-full bg-red-600 hover:bg-red-500 text-sm font-semibold">{leaving ? 'Leaving…' : 'Leave'}</button>
          </div>
        </main>

        {isHost && (
          <aside className="lg:w-96 shrink-0 min-h-0 flex flex-col">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-sm font-semibold">Live alerts</span>
              <a href={meetingApi.logDownloadUrl()} download="attentiveness_log.xlsx" className="text-xs px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 hover:bg-slate-700">Download Excel</a>
            </div>
            <div className="mb-3 rounded-xl border border-slate-800 bg-[#0b111b] p-3">
              <div className="text-xs text-slate-500 mb-2">Participants</div>
              <div className="space-y-1.5 max-h-40 overflow-auto">
                {allParticipants.map((p) => <div key={p.participant_id} className="text-xs flex justify-between"><span>{displayName(p, participantId)}</span><span className="text-slate-500">{p.is_host ? 'Host' : 'User'}</span></div>)}
              </div>
            </div>
            <div className="flex-1 min-h-0 overflow-auto"><MeetingAlertsFeed events={hostEvents} /></div>
          </aside>
        )}
      </div>
    </div>
  )
}

function RemoteTile({ stream, participant }) {
  const ref = useRef(null)
  useEffect(() => {
    if (ref.current) ref.current.srcObject = stream
  }, [stream])
  return (
    <div className="relative min-h-0 rounded-xl overflow-hidden bg-black border border-slate-800 shadow-lg">
      <video ref={ref} autoPlay playsInline className="w-full h-full object-cover" />
      <div className="absolute bottom-2 left-2 px-2 py-1 rounded bg-black/60 text-xs">{participant.name || 'Participant'}{participant.is_host ? ' · Host' : ''}</div>
    </div>
  )
}
