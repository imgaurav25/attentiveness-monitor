function statusColor(m) {
  if (m.known === false) return 'border-fuchsia-500 bg-fuchsia-950/40 text-fuchsia-300'
  if (m.status === 'Attentive') return 'border-emerald-600 bg-emerald-950/40 text-emerald-300'
  if (m.status && m.status.includes('(')) {
    // "Reason (Ns)" -- orange while counting, handled the same visually here;
    // red-vs-orange distinction happens via the boxed color on the video feed.
    return 'border-amber-500 bg-amber-950/40 text-amber-300'
  }
  return 'border-slate-700 bg-slate-900/40 text-slate-300'
}

export default function StudentsPanel({ members }) {
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
      <h2 className="text-sm font-semibold text-slate-200 mb-3">People in frame</h2>
      {members.length === 0 ? (
        <p className="text-sm text-slate-500">No one detected right now.</p>
      ) : (
        <ul className="space-y-2">
          {members.map((m) => (
            <li
              key={m.member_id}
              className={`flex items-center justify-between rounded-lg border px-3 py-2 text-sm ${statusColor(m)}`}
            >
              <div className="flex flex-col">
                <span className="font-medium">{m.who}</span>
                {m.identity?.roll_no && (
                  <span className="text-xs opacity-75">
                    {m.identity.roll_no} · {m.identity.class || m.identity.department || ''}
                  </span>
                )}
              </div>
              <span className="text-xs font-mono">{m.known === false ? 'UNKNOWN' : m.status}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
