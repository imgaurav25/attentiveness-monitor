export default function Controls({
  status,
  onStart,
  onStop,
  onModeChange,
  onDelayChange,
  onOpenRegister,
  onTrain,
  busy,
}) {
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 flex flex-wrap items-center gap-4">
      <div className="flex items-center gap-2">
        {status.running ? (
          <button
            onClick={onStop}
            className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-white text-sm font-medium transition"
          >
            Stop
          </button>
        ) : (
          <button
            onClick={onStart}
            disabled={busy}
            className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium transition disabled:opacity-50"
          >
            Start Monitoring
          </button>
        )}
      </div>

      <div className="flex items-center gap-2 text-sm">
        <span className="text-slate-400">Mode:</span>
        <div className="inline-flex rounded-lg border border-slate-700 overflow-hidden">
          <button
            onClick={() => onModeChange('unknown')}
            className={`px-3 py-1.5 text-xs font-medium transition ${
              status.mode === 'unknown' ? 'bg-slate-200 text-slate-900' : 'bg-transparent text-slate-300'
            }`}
          >
            Unknown environment
          </button>
          <button
            onClick={() => onModeChange('known')}
            className={`px-3 py-1.5 text-xs font-medium transition ${
              status.mode === 'known' ? 'bg-slate-200 text-slate-900' : 'bg-transparent text-slate-300'
            }`}
          >
            Known / classroom
          </button>
        </div>
      </div>

      <div className="flex items-center gap-2 text-sm">
        <span className="text-slate-400">Delay:</span>
        <input
          type="range"
          min={status.min_delay || 5}
          max={status.max_delay || 25}
          value={status.delay_seconds || 7}
          onChange={(e) => onDelayChange(Number(e.target.value))}
          className="accent-emerald-500"
        />
        <span className="font-mono text-slate-200 w-10">{status.delay_seconds}s</span>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <span className="text-xs text-slate-400">
          Roster: <span className="text-slate-200 font-medium">{status.roster_size}</span>
        </span>
        <button
          onClick={onOpenRegister}
          className="px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-100 text-xs font-medium transition"
        >
          Register New Person
        </button>
        <button
          onClick={onTrain}
          className="px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-100 text-xs font-medium transition"
        >
          Train Model
        </button>
      </div>
    </div>
  )
}
