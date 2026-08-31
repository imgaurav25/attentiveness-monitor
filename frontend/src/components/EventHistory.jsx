function fmtTime(ts) {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleString()
}

export default function EventHistory({ events }) {
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
      <h2 className="text-sm font-semibold text-slate-200 mb-3">Attentiveness event history</h2>
      {events.length === 0 ? (
        <p className="text-sm text-slate-500">No events logged yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-400 border-b border-slate-800">
                <th className="py-1.5 pr-3 font-medium">Time</th>
                <th className="py-1.5 pr-3 font-medium">Person</th>
                <th className="py-1.5 pr-3 font-medium">Reason</th>
                <th className="py-1.5 pr-3 font-medium">Duration</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e, i) => (
                <tr key={i} className="border-b border-slate-900">
                  <td className="py-1.5 pr-3 whitespace-nowrap text-slate-400">{fmtTime(e.timestamp)}</td>
                  <td className="py-1.5 pr-3 font-medium">{e.who}</td>
                  <td className="py-1.5 pr-3 text-amber-300">{e.reason}</td>
                  <td className="py-1.5 pr-3 font-mono text-slate-300">{e.duration}s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
