import { Link } from 'react-router-dom'
import { useEffect, useRef, useState, useCallback } from 'react'
import { api, connectLiveSocket } from '../api'
import LiveFeed from '../components/LiveFeed'
import StudentsPanel from '../components/StudentsPanel'
import UnknownAlerts from '../components/UnknownAlerts'
import EventHistory from '../components/EventHistory'
import Controls from '../components/Controls'
import RegisterModal from '../components/RegisterModal'
import PreMeetingModal from '../components/PreMeetingModal'
import { speakAttentivenessAlert, speakUnknownPersonAlert } from '../voiceAlert'

let toastId = 0

export default function ClassroomDashboard() {
  const [status, setStatus] = useState({
    running: false,
    mode: 'unknown',
    delay_seconds: 7,
    min_delay: 5,
    max_delay: 25,
    roster_size: 0,
    attentiveness_event_count: 0,
    unknown_event_count: 0,
    members: [],
  })
  const [frame, setFrame] = useState(null)
  const [members, setMembers] = useState([])
  const [attentivenessEvents, setAttentivenessEvents] = useState([])
  const [unknownEvents, setUnknownEvents] = useState([])
  const [wsStatus, setWsStatus] = useState('disconnected')
  const [registerOpen, setRegisterOpen] = useState(false)
  const [preMeetingOpen, setPreMeetingOpen] = useState(false)
  const [registerFromPreMeeting, setRegisterFromPreMeeting] = useState(false)
  const [busy, setBusy] = useState(false)
  const [toasts, setToasts] = useState([]) // {id, text, kind: 'info' | 'unknown' | 'alert'}

  const pushToast = (text, kind = 'info', ttl = 5000) => {
    const id = ++toastId
    setToasts((prev) => [...prev, { id, text, kind }])
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), ttl)
  }

  const refreshStatus = useCallback(async () => {
    try {
      const s = await api.getStatus()
      setStatus(s)
      setMembers(s.members || [])
    } catch {
      // backend not reachable yet -- fine on first load
    }
  }, [])

  useEffect(() => {
    refreshStatus()
    api.attentivenessEvents(50).then(setAttentivenessEvents).catch(() => {})
    api.unknownEvents(50).then(setUnknownEvents).catch(() => {})

    const close = connectLiveSocket(
      (msg) => {
        if (msg.type === 'frame') setFrame(msg.data)
        else if (msg.type === 'members') setMembers(msg.data)
        else if (msg.type === 'attentiveness_event') {
          setAttentivenessEvents((prev) => [msg.data, ...prev].slice(0, 200))
        } else if (msg.type === 'attentiveness_alert') {
          // Fires the INSTANT someone crosses the delay threshold -- the
          // teacher needs to know right away, not after they recover.
          const d = msg.data
          pushToast(`⏰ ${d.who} has been "${d.reason}" for ${d.elapsed}s`, 'alert', 6000)
          speakAttentivenessAlert(d)
        } else if (msg.type === 'unknown_event') {
          setUnknownEvents((prev) => [msg.data, ...prev].slice(0, 200))
          pushToast(`⚠ ${msg.data.message} (${msg.data.unknown_id})`, 'unknown')
          speakUnknownPersonAlert(msg.data)
        }
      },
      setWsStatus,
    )

    const poll = setInterval(refreshStatus, 5000)
    return () => {
      close()
      clearInterval(poll)
    }
  }, [refreshStatus])

  const handleStart = async () => {
    setBusy(true)
    try {
      await api.start()
      await refreshStatus()
    } catch (err) {
      pushToast(err.message, 'unknown')
    } finally {
      setBusy(false)
    }
  }

  // In Known/classroom mode, starting the meeting is gated: register a
  // roster first if empty, otherwise pick attendees, THEN the video starts.
  // In Unknown/open-room mode, Start Monitoring works immediately as before.
  const handleRequestStart = () => {
    if (status.mode === 'known') {
      setPreMeetingOpen(true)
    } else {
      handleStart()
    }
  }

  const handleStop = async () => {
    await api.stop()
    setFrame(null)
    setMembers([])
    await refreshStatus()
  }

  const handleModeChange = async (mode) => {
    await api.setMode(mode)
    setStatus((s) => ({ ...s, mode }))
  }

  const handleDelayChange = async (seconds) => {
    setStatus((s) => ({ ...s, delay_seconds: seconds }))
    await api.setDelay(seconds)
  }

  const handleTrained = async (result) => {
    pushToast(`Trained on ${result.people} people (${result.images} images)`, 'info')
    await refreshStatus()
    // Registering was opened from the pre-meeting gate -- go back to it so
    // the teacher can pick attendees (or register another student) and
    // then actually start the video.
    if (registerFromPreMeeting) {
      setRegisterFromPreMeeting(false)
      setPreMeetingOpen(true)
    }
  }

  const toastStyle = (kind) => {
    if (kind === 'alert') return 'border-red-700 bg-red-950/70 text-red-200'
    if (kind === 'unknown') return 'border-fuchsia-700 bg-fuchsia-950/60 text-fuchsia-200'
    return 'border-slate-700 bg-slate-800/70 text-slate-200'
  }

  return (
    <div className="min-h-screen bg-[#0b0f14] text-slate-100 p-4 md:p-6">
      <header className="mb-5 flex items-center justify-between">
        <div>
          <Link to="/" className="text-xs text-slate-500 hover:text-slate-300">&larr; Home</Link>
          <h1 className="text-xl font-semibold">Classroom Attentiveness Monitor</h1>
          <p className="text-sm text-slate-400">
            {status.attentiveness_event_count} attentiveness events · {status.unknown_event_count} unknown-person alerts logged
          </p>
        </div>
      </header>

      {toasts.length > 0 && (
        <div className="mb-4 space-y-2">
          {toasts.map((t) => (
            <div key={t.id} className={`rounded-lg border text-sm px-4 py-2 ${toastStyle(t.kind)}`}>
              {t.text}
            </div>
          ))}
        </div>
      )}

      <div className="mb-4">
        <Controls
          status={status}
          busy={busy}
          onStart={handleRequestStart}
          onStop={handleStop}
          onModeChange={handleModeChange}
          onDelayChange={handleDelayChange}
          onOpenRegister={() => setRegisterOpen(true)}
          onTrain={async () => {
            try {
              const result = await api.train()
              handleTrained(result)
            } catch (err) {
              pushToast(err.message, 'unknown')
            }
          }}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 space-y-4">
          <LiveFeed frame={frame} running={status.running} wsStatus={wsStatus} mode={status.mode} />
          <EventHistory events={attentivenessEvents} />
        </div>

        <div className="space-y-4">
          <StudentsPanel members={members} />
          <UnknownAlerts events={unknownEvents} />
        </div>
      </div>

      <RegisterModal
        open={registerOpen}
        onClose={() => {
          setRegisterOpen(false)
          if (registerFromPreMeeting) {
            setRegisterFromPreMeeting(false)
            setPreMeetingOpen(true)
          }
        }}
        onTrained={(result) => {
          setRegisterOpen(false)
          handleTrained(result)
        }}
      />

      <PreMeetingModal
        open={preMeetingOpen}
        onClose={() => setPreMeetingOpen(false)}
        onStartVideo={() => {
          setPreMeetingOpen(false)
          handleStart()
        }}
        onOpenRegister={() => {
          setPreMeetingOpen(false)
          setRegisterFromPreMeeting(true)
          setRegisterOpen(true)
        }}
      />
    </div>
  )
}
