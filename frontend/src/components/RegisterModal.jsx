import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

const emptyForm = { name: '', roll_no: '', student_class: '', department: '', year: '' }

export default function RegisterModal({ open, onClose, onTrained }) {
  const [form, setForm] = useState(emptyForm)
  const [phase, setPhase] = useState('form') // form | capturing | done | error
  const [progress, setProgress] = useState({ captured: 0, target: 0 })
  const [error, setError] = useState('')
  const pollRef = useRef(null)

  useEffect(() => {
    if (!open) {
      setForm(emptyForm)
      setPhase('form')
      setError('')
      clearInterval(pollRef.current)
    }
    return () => clearInterval(pollRef.current)
  }, [open])

  if (!open) return null

  const submit = async (e) => {
    e.preventDefault()
    if (!form.name.trim()) {
      setError('Name is required.')
      return
    }
    setError('')
    try {
      await api.registerStart(form)
      setPhase('capturing')
      pollRef.current = setInterval(async () => {
        try {
          const st = await api.registerStatus()
          setProgress({ captured: st.captured, target: st.target })
          if (!st.capturing && st.finalized) {
            clearInterval(pollRef.current)
            setPhase('done')
          }
        } catch {
          // transient poll error, keep trying
        }
      }, 400)
    } catch (err) {
      setError(err.message)
    }
  }

  const trainNow = async () => {
    try {
      const result = await api.train()
      onTrained && onTrained(result)
      onClose()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 w-full max-w-md">
        <h2 className="text-lg font-semibold text-slate-100 mb-4">Register New Person</h2>

        {phase === 'form' && (
          <form onSubmit={submit} className="space-y-3">
            {[
              ['name', 'Name'],
              ['roll_no', 'Roll No'],
              ['student_class', 'Class'],
              ['department', 'Department'],
              ['year', 'Year'],
            ].map(([key, label]) => (
              <div key={key}>
                <label className="block text-xs text-slate-400 mb-1">{label}</label>
                <input
                  value={form[key]}
                  onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                  className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-500"
                />
              </div>
            ))}
            {error && <p className="text-sm text-red-400">{error}</p>}
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="px-3 py-2 rounded-lg text-sm text-slate-300 hover:text-white"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium"
              >
                Start Capturing Faces
              </button>
            </div>
          </form>
        )}

        {phase === 'capturing' && (
          <div className="space-y-3 text-sm text-slate-300">
            <p>
              Ask <span className="font-medium text-slate-100">{form.name}</span> to look at the
              camera and slowly turn their head slightly left / right / up / down.
            </p>
            <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
              <div
                className="bg-emerald-500 h-2 transition-all"
                style={{
                  width: `${progress.target ? Math.min(100, (progress.captured / progress.target) * 100) : 0}%`,
                }}
              />
            </div>
            <p className="text-xs text-slate-500">
              {progress.captured} / {progress.target || '…'} images captured
            </p>
            {error && <p className="text-sm text-red-400">{error}</p>}
          </div>
        )}

        {phase === 'done' && (
          <div className="space-y-4 text-sm text-slate-300">
            <p>
              Saved face images for <span className="font-medium text-slate-100">{form.name}</span>.
              Train the model now to include them in recognition.
            </p>
            {error && <p className="text-sm text-red-400">{error}</p>}
            <div className="flex justify-end gap-2">
              <button
                onClick={onClose}
                className="px-3 py-2 rounded-lg text-sm text-slate-300 hover:text-white"
              >
                Later
              </button>
              <button
                onClick={trainNow}
                className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium"
              >
                Train Model Now
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
