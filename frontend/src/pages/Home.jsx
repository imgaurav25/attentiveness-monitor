import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Link } from 'react-router-dom'
import { meetingApi } from '../meetingApi'

export default function Home() {
  const navigate = useNavigate()
  const [tab, setTab] = useState('create') // 'create' | 'join'
  const [title, setTitle] = useState('')
  const [joinInput, setJoinInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const extractMeetingId = (input) => {
    const trimmed = input.trim()
    if (!trimmed) return ''
    try {
      const url = new URL(trimmed)
      const parts = url.pathname.split('/').filter(Boolean)
      const idx = parts.indexOf('meeting')
      if (idx !== -1 && parts[idx + 1]) return parts[idx + 1]
    } catch {
      // not a URL -- treat the whole input as the meeting id
    }
    return trimmed
  }

  const createMeeting = async () => {
    setBusy(true)
    setError('')
    try {
      const meeting = await meetingApi.createMeeting(title)
      localStorage.setItem(`attn-host-meeting:${meeting.meeting_id}`, '1')
      navigate(`/meeting/${meeting.meeting_id}?host=1`)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const joinMeeting = async (e) => {
    e.preventDefault()
    const id = extractMeetingId(joinInput)
    if (!id) {
      setError('Paste a meeting link or enter a meeting ID.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await meetingApi.getMeeting(id) // validate it exists before navigating
      navigate(`/meeting/${id}`)
    } catch (err) {
      setError('Meeting not found. Check the link and try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#0b0f14] text-slate-100 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-semibold">Attentiveness Meetings</h1>
          <p className="text-sm text-slate-400 mt-1">
            Registered-only video meetings with live attentiveness monitoring.
          </p>
        </div>

        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-6">
          <div className="flex rounded-lg border border-slate-700 overflow-hidden mb-5">
            <button
              onClick={() => setTab('create')}
              className={`flex-1 py-2 text-sm font-medium transition ${
                tab === 'create' ? 'bg-slate-200 text-slate-900' : 'text-slate-300'
              }`}
            >
              Create a Meeting
            </button>
            <button
              onClick={() => setTab('join')}
              className={`flex-1 py-2 text-sm font-medium transition ${
                tab === 'join' ? 'bg-slate-200 text-slate-900' : 'text-slate-300'
              }`}
            >
              Join a Meeting
            </button>
          </div>

          {tab === 'create' ? (
            <div className="space-y-3">
              <label className="block text-xs text-slate-400">Meeting title (optional)</label>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Physics 101"
                className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-emerald-500"
              />
              <button
                onClick={createMeeting}
                disabled={busy}
                className="w-full py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium transition disabled:opacity-50"
              >
                Create Meeting Link &amp; Join
              </button>
            </div>
          ) : (
            <form onSubmit={joinMeeting} className="space-y-3">
              <label className="block text-xs text-slate-400">Meeting link or ID</label>
              <input
                value={joinInput}
                onChange={(e) => setJoinInput(e.target.value)}
                placeholder="Paste the link the host shared"
                className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-emerald-500"
              />
              <button
                type="submit"
                disabled={busy}
                className="w-full py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium transition disabled:opacity-50"
              >
                Join Meeting
              </button>
            </form>
          )}

          {error && <p className="text-sm text-red-400 mt-3">{error}</p>}
        </div>

        <p className="text-center text-xs text-slate-500 mt-6">
          Prefer a single shared classroom camera instead?{' '}
          <Link to="/classroom" className="underline hover:text-slate-300">
            Open the classroom dashboard
          </Link>
        </p>
      </div>
    </div>
  )
}
