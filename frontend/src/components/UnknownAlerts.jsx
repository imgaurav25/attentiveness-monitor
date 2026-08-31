import { api } from '../api'

function fmtTime(ts) {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleString()
}

export default function UnknownAlerts({ events }) {
  return (
    <div className="bg-slate-900/60 border border-fuchsia-900/50 rounded-xl p-4">
      <h2 className="text-sm font-semibold text-fuchsia-300 mb-3 flex items-center gap-2">
        <span>⚠ Unknown person alerts</span>
      </h2>
      {events.length === 0 ? (
        <p className="text-sm text-slate-500">No unknown-person events yet.</p>
      ) : (
        <ul className="space-y-3 max-h-96 overflow-y-auto pr-1">
          {events.map((e, i) => (
            <li key={i} className="rounded-lg border border-fuchsia-900/40 bg-fuchsia-950/20 p-3">
              <div className="flex justify-between items-start text-sm">
                <div>
                  <div className="font-semibold text-fuchsia-300">{e.unknown_id}</div>
                  <div className="text-xs text-slate-400">{fmtTime(e.timestamp)}</div>
                </div>
                <div className="text-xs text-slate-300 font-mono">{e.duration}s</div>
              </div>

              <div className="mt-1 text-sm text-slate-200 font-medium">
                {e.message || (e.nearby_student ? `Unknown present with ${e.nearby_student.name}` : 'Unknown')}
              </div>

              {e.nearby_student?.roll_no && (
                <div className="text-xs text-slate-400">{e.nearby_student.roll_no}</div>
              )}

              {(e.face_snapshot || e.full_snapshot) && (
                <div className="mt-2 flex gap-2">
                  {e.face_snapshot && (
                    <a href={api.snapshotUrl(e.face_snapshot)} target="_blank" rel="noreferrer">
                      <img
                        src={api.snapshotUrl(e.face_snapshot)}
                        alt="Unknown face"
                        className="w-20 h-20 object-cover rounded-md border border-slate-700"
                      />
                    </a>
                  )}
                  {e.full_snapshot && (
                    <a href={api.snapshotUrl(e.full_snapshot)} target="_blank" rel="noreferrer">
                      <img
                        src={api.snapshotUrl(e.full_snapshot)}
                        alt="Full frame"
                        className="w-32 h-20 object-cover rounded-md border border-slate-700"
                      />
                    </a>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
