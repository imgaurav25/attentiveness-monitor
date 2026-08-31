export default function LiveFeed({ frame, running, wsStatus, mode }) {
  return (
    <div className="relative rounded-xl overflow-hidden bg-black border border-slate-800 aspect-video flex items-center justify-center">
      {frame ? (
        <img
          src={`data:image/jpeg;base64,${frame}`}
          alt="Live camera feed"
          className="w-full h-full object-contain"
        />
      ) : (
        <div className="text-slate-500 text-sm">
          {running ? 'Waiting for frames…' : 'Monitoring is stopped'}
        </div>
      )}

      <div className="absolute top-3 left-3 flex items-center gap-2">
        <span
          className={`inline-block w-2.5 h-2.5 rounded-full ${
            running ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'
          }`}
        />
        <span className="text-xs font-medium bg-black/60 px-2 py-1 rounded-md text-slate-200">
          {running ? 'Monitoring' : 'Idle'}
        </span>
        <span className="text-xs font-medium bg-black/60 px-2 py-1 rounded-md text-slate-200 uppercase">
          {mode === 'known' ? 'Classroom mode' : 'Open room mode'}
        </span>
      </div>

      <div className="absolute top-3 right-3">
        <span
          className={`text-xs font-medium px-2 py-1 rounded-md ${
            wsStatus === 'connected'
              ? 'bg-emerald-900/70 text-emerald-300'
              : 'bg-red-900/70 text-red-300'
          }`}
        >
          {wsStatus === 'connected' ? 'Live' : 'Reconnecting…'}
        </span>
      </div>
    </div>
  )
}
