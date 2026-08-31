import { meetingApi } from '../meetingApi'

function fmtTime(ts) {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleTimeString()
}

const STYLES = {
  attentiveness_event: 'border-amber-700 bg-amber-950/30 text-amber-200',
  impersonation_alert: 'border-red-700 bg-red-950/40 text-red-200',
  extra_person_alert: 'border-fuchsia-700 bg-fuchsia-950/30 text-fuchsia-200',
}

function describe(item) {
  const { type, data } = item
  if (type === 'attentiveness_event') {
    return `${data.who} — ${data.reason} (${data.duration}s)`
  }
  if (type === 'impersonation_alert') {
    return data.message
  }
  if (type === 'extra_person_alert') {
    return data.message
  }
  return type
}

export default function MeetingAlertsFeed({ events }) {
  const visible = events.filter((e) => e.type !== 'attentiveness_alert')

  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
      <h2 className="text-sm font-semibold text-slate-200 mb-3">Meeting activity</h2>
      {visible.length === 0 ? (
        <p className="text-sm text-slate-500">No events yet.</p>
      ) : (
        <ul className="space-y-2 max-h-[28rem] overflow-y-auto pr-1">
          {visible.map((item, i) => (
            <li
              key={i}
              className={`rounded-lg border px-3 py-2 text-sm ${STYLES[item.type] || 'border-slate-700 bg-slate-800/40 text-slate-300'}`}
            >
              <div className="flex justify-between items-start gap-2">
                <span className="font-medium">{describe(item)}</span>
                <span className="text-xs opacity-70 whitespace-nowrap">{fmtTime(item.data.timestamp)}</span>
              </div>
              {(item.data.face_snapshot || item.data.full_snapshot) && (
                <div className="mt-2 flex gap-2">
                  {item.data.face_snapshot && (
                    <a href={meetingApi.snapshotUrl(item.data.face_snapshot)} download={item.data.face_snapshot} target="_blank" rel="noreferrer">
                      <img
                        src={meetingApi.snapshotUrl(item.data.face_snapshot)}
                        alt="Face"
                        className="w-16 h-16 object-cover rounded-md border border-slate-700"
                      />
                    </a>
                  )}
                  {item.data.full_snapshot && (
                    <a href={meetingApi.snapshotUrl(item.data.full_snapshot)} download={item.data.full_snapshot} target="_blank" rel="noreferrer">
                      <img
                        src={meetingApi.snapshotUrl(item.data.full_snapshot)}
                        alt="Full frame"
                        className="w-24 h-16 object-cover rounded-md border border-slate-700"
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
