import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate, useSearchParams, Link } from 'react-router-dom'
import { meetingApi, connectRegistrationSocket } from '../meetingApi'
import { openCamera, stopStream, captureFrameBase64 } from '../cameraUtils'

const emptyForm = { name: '', roll_no: '', student_class: '', department: '', year: '' }

export default function PreJoin() {
  const { meetingId } = useParams()
  const [searchParams] = useSearchParams()
  const [isHost, setIsHost] = useState(searchParams.get('host') === '1')
  const navigate = useNavigate()

  const [meeting, setMeeting] = useState(null)
  const [error, setError] = useState('')
  const [roster, setRoster] = useState([])
  const [search, setSearch] = useState('')

  const [mode, setMode] = useState('select') // 'select' | 'register'
  const [selected, setSelected] = useState(null) // roster entry
  const [form, setForm] = useState(emptyForm)
  const [registering, setRegistering] = useState(false)
  const [regProgress, setRegProgress] = useState({ captured: 0, target: 0 })
  const [registeredAs, setRegisteredAs] = useState(null) // { label_id, name }
  const [joining, setJoining] = useState(false)

  const videoRef = useRef(null)
  const streamRef = useRef(null)
  const regSocketRef = useRef(null)
  const regIntervalRef = useRef(null)

  useEffect(() => {
    meetingApi.getMeeting(meetingId).then((m) => {
      setMeeting(m)
      if (searchParams.get('host') === '1' || localStorage.getItem(`attn-host-meeting:${meetingId}`) === '1') setIsHost(true)
    }).catch(() => setError('Meeting not found.'))
    meetingApi.getMeetingRoster(meetingId).then(setRoster).catch(() => {})

    openCamera()
      .then((stream) => {
        streamRef.current = stream
        if (videoRef.current) videoRef.current.srcObject = stream
      })
      .catch(() => setError('Camera access is required to join. Please allow camera permission.'))

    return () => {
      stopStream(streamRef.current)
      clearInterval(regIntervalRef.current)
      if (regSocketRef.current) regSocketRef.current.close()
    }
  }, [meetingId])

  const filteredRoster = roster.filter((r) =>
    r.name.toLowerCase().includes(search.toLowerCase()),
  )

  const startRegistration = async (e) => {
    e.preventDefault()
    if (!form.name.trim()) {
      setError('Name is required.')
      return
    }
    setError('')
    try {
      const { token, label_id } = await meetingApi.registerStart(meetingId, form)
      setRegistering(true)
      setRegProgress({ captured: 0, target: 0 })

      const socket = connectRegistrationSocket(
        token,
        (msg) => {
          if (msg.type === 'error') {
            setError(msg.data)
            setRegistering(false)
            return
          }
          const data = msg.data
          setRegProgress({ captured: data.captured, target: data.target })
          if (data.done) {
            setRegistering(false)
            setRegisteredAs({ label_id: data.label_id ?? label_id, name: form.name })
            clearInterval(regIntervalRef.current)
          }
        },
        () => {},
      )
      regSocketRef.current = socket

      // Stream frames from the camera preview a few times a second while capturing.
      regIntervalRef.current = setInterval(() => {
        const b64 = captureFrameBase64(videoRef.current)
        if (b64) socket.send({ type: 'frame', data: b64 })
      }, 350)
    } catch (err) {
      setError(err.message)
    }
  }

  const chosen = registeredAs || selected
  const chosenIsHost = isHost || Boolean(meeting?.host_label_id != null && chosen?.label_id != null && Number(meeting.host_label_id) === Number(chosen.label_id))
  const canJoin = registeredAs || selected
  const joinName = registeredAs ? registeredAs.name : selected ? selected.name : ''
  const joinLabelId = registeredAs ? registeredAs.label_id : selected ? selected.label_id : null

  const handleJoin = async () => {
    if (!canJoin) return
    setJoining(true)
    setError('')
    try {
      const result = await meetingApi.join(meetingId, {
        name: joinName,
        claimed_label_id: joinLabelId,
        is_host: chosenIsHost,
      })
      if (result.is_host) localStorage.setItem(`attn-host-meeting:${meetingId}`, '1')
      sessionStorage.setItem(`attn-participant:${meetingId}`, JSON.stringify({ participantId: result.participant_id, name: joinName, isHost: result.is_host ?? chosenIsHost }))
      stopStream(streamRef.current)
      navigate(`/meeting/${meetingId}/room`, {
        state: {
          participantId: result.participant_id,
          name: joinName,
          isHost: result.is_host ?? chosenIsHost,
        },
      })
    } catch (err) {
      setError(err.message)
      setJoining(false)
    }
  }

  const copyLink = () => {
    const url = `${window.location.origin}/meeting/${meetingId}`
    navigator.clipboard.writeText(url)
  }

  if (error && !meeting) {
    return (
      <div className="min-h-screen bg-[#0b0f14] text-slate-100 flex items-center justify-center p-4">
        <div className="text-center">
          <p className="text-red-400 mb-3">{error}</p>
          <Link to="/" className="text-sm underline text-slate-400 hover:text-slate-200">
            Back to home
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#0b0f14] text-slate-100 p-4 md:p-8">
      <div className="max-w-3xl mx-auto">
        <div className="mb-6">
          <Link to="/" className="text-xs text-slate-500 hover:text-slate-300">&larr; Home</Link>
          <h1 className="text-xl font-semibold mt-1">{meeting ? meeting.title : 'Loading meeting…'}</h1>
          <div className="flex items-center gap-2 mt-2">
            <button
              onClick={copyLink}
              className="text-xs px-2 py-1 rounded-md bg-slate-800 border border-slate-700 hover:bg-slate-700 text-slate-300"
            >
              Copy meeting link
            </button>
            {isHost && (
              <span className="text-xs px-2 py-1 rounded-md bg-emerald-950 text-emerald-300 border border-emerald-800">
                You're the host
              </span>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          <div className="rounded-xl overflow-hidden bg-black border border-slate-800 aspect-video">
            <video ref={videoRef} autoPlay muted playsInline className="w-full h-full object-cover" />
          </div>

          <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
            <h2 className="text-sm font-semibold mb-3">Before you join, who are you?</h2>

            {registeredAs ? (
              <div className="text-sm text-emerald-300 bg-emerald-950/40 border border-emerald-800 rounded-lg p-3 mb-3">
                Registered as <span className="font-medium">{registeredAs.name}</span>. You're ready to join.
              </div>
            ) : (
              <>
                <div className="flex rounded-lg border border-slate-700 overflow-hidden mb-3">
                  <button
                    onClick={() => setMode('select')}
                    className={`flex-1 py-1.5 text-xs font-medium transition ${
                      mode === 'select' ? 'bg-slate-200 text-slate-900' : 'text-slate-300'
                    }`}
                  >
                    I'm already registered
                  </button>
                  <button
                    onClick={() => setMode('register')}
                    className={`flex-1 py-1.5 text-xs font-medium transition ${
                      mode === 'register' ? 'bg-slate-200 text-slate-900' : 'text-slate-300'
                    }`}
                  >
                    Register myself
                  </button>
                </div>

                {mode === 'select' && (
                  <div className="space-y-2">
                    <input
                      value={search}
                      onChange={(e) => {
                        setSearch(e.target.value)
                        setSelected(null)
                      }}
                      placeholder="Search your name…"
                      className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-emerald-500"
                    />
                    <div className="max-h-40 overflow-y-auto rounded-lg border border-slate-700 divide-y divide-slate-800">
                      {filteredRoster.length === 0 && (
                        <p className="text-xs text-slate-500 p-3">
                          {roster.length === 0 ? 'No one is registered yet.' : 'No match.'}
                        </p>
                      )}
                      {filteredRoster.map((r) => (
                        <button
                          key={r.label_id}
                          onClick={() => setSelected(r)}
                          className={`w-full text-left px-3 py-2 text-sm hover:bg-slate-800/60 ${
                            selected?.label_id === r.label_id ? 'bg-emerald-950/50 text-emerald-300' : 'text-slate-200'
                          }`}
                        >
                          {r.name} {r.roll_no && <span className="text-xs text-slate-500">({r.roll_no})</span>}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {mode === 'register' && !registering && (
                  <form onSubmit={startRegistration} className="space-y-2">
                    {[
                      ['name', 'Name'],
                      ['roll_no', 'Roll No'],
                      ['student_class', 'Class'],
                      ['department', 'Department'],
                      ['year', 'Year'],
                    ].map(([key, label]) => (
                      <input
                        key={key}
                        value={form[key]}
                        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                        placeholder={label}
                        className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-emerald-500"
                      />
                    ))}
                    <button
                      type="submit"
                      className="w-full py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-sm font-medium"
                    >
                      Start Registration (turn your head slowly)
                    </button>
                  </form>
                )}

                {registering && (
                  <div className="space-y-2">
                    <p className="text-xs text-slate-400">
                      Look at the camera and slowly turn your head left / right / up / down…
                    </p>
                    <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
                      <div
                        className="bg-emerald-500 h-2 transition-all"
                        style={{
                          width: `${regProgress.target ? Math.min(100, (regProgress.captured / regProgress.target) * 100) : 0}%`,
                        }}
                      />
                    </div>
                    <p className="text-xs text-slate-500">
                      {regProgress.captured} / {regProgress.target || '…'} images captured
                    </p>
                  </div>
                )}
              </>
            )}

            {error && <p className="text-sm text-red-400 mt-3">{error}</p>}

            <button
              onClick={handleJoin}
              disabled={!canJoin || joining}
              className="w-full mt-4 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white text-sm font-medium transition"
            >
              {joining ? 'Joining…' : 'Open / Start Video'}
            </button>
            <p className="text-xs text-slate-500 mt-2">
              You cannot join this meeting without registering or selecting your registered name.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
