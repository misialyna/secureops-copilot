import { strings } from '../ui/strings'

export function ReportWarningsBadge({ count }: { count: number }) {
  if (count <= 0) return null
  return (
    <div className="rounded-lg border border-amber-600/40 bg-amber-500/10 p-3 text-sm text-amber-300">
      {strings.reportWarningsLabel}: <span className="font-semibold">{count}</span>
    </div>
  )
}
