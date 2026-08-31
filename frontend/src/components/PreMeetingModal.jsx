import { useEffect, useState } from 'react'
import { api } from '../api'

export default function PreMeetingModal({ open, onClose, onStartVideo, onOpenRegister }) {
  const [roster, setRoster] = useState(null) // null = loading
  const [selected, setSelected] = useState(new Set())
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setError('')
    api.roster().then(setRoster).catch((err) => setError(err.message))
  }, [open])

  if (!open) return null

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const selectAll = () => setSelected(new Set((roster || []).map((r) => r.label_id)))
  const selectNone = () => setSelected(new Set())

  const startVideo = async () => {
    try {
      await api.setSessionAttendees(Array.from(selected))
      onStartVideo()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 w-full max-w-md">
        <h2 className="text-lg font-semibold text-slate-100 mb-1">Before the meeting starts</h2>
        <p className="text-sm text-slate-400 mb-4">Classroom mode needs a registered roster.</p>

        {roster === null && !error && <p className="text-sm text-slate-400">Loading roster…</p>}
        {error && <p className="text-sm text-red-400 mb-3">{error}</p>}

        {roster && roster.length === 0 && (
          <div className="space-y-4">
            <p className="text-sm text-slate-300">
              No students are registered yet. Register at least one student and train the
              model before starting the meeting.
            </p>
            <div className="flex justify-end gap-2">
              <button onClick={onClose} className="px-3 py-2 rounded-lg text-sm text-slate-300 hover:text-white">
                Cancel
              </button>
              <button
                onClick={onOpenRegister}
                className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium"
              >
                Register a Student
              </button>
            </div>
          </div>
        )}

        {roster && roster.length > 0 && (
          <div className="space-y-3">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>Select who is attending this session</span>
              <span className="space-x-2">
                <button onClick={selectAll} className="underline hover:text-slate-200">
                  All
                </button>
                <button onClick={selectNone} className="underline hover:text-slate-200">
                  None
                </button>
              </span>
            </div>

            <div className="max-h-56 overflow-y-auto rounded-lg border border-slate-700 divide-y divide-slate-800">
              {roster.map((r) => (
                <label
                  key={r.label_id}
                  className="flex items-center gap-3 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800/60 cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={selected.has(r.label_id)}
                    onChange={() => toggle(r.label_id)}
                    className="accent-emerald-500"
                  />
                  <div className="flex flex-col">
                    <span>{r.name}</span>
                    {r.roll_no && <span className="text-xs text-slate-500">{r.roll_no}</span>}
                  </div>
                </label>
              ))}
            </div>

            <div className="flex justify-between items-center pt-1">
              <button onClick={onOpenRegister} className="text-xs text-slate-400 underline hover:text-slate-200">
                Register another student
              </button>
              <div className="flex gap-2">
                <button onClick={onClose} className="px-3 py-2 rounded-lg text-sm text-slate-300 hover:text-white">
                  Cancel
                </button>
                <button
                  onClick={startVideo}
                  className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium"
                >
                  Open / Start Video
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
