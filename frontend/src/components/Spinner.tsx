export function Spinner({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900 p-3 text-sm text-slate-400">
      <span className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-slate-600 border-t-cyan-400" />
      {label}
    </div>
  )
}
