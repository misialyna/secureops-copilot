import type { AuditEntry } from '../api/types'
import { strings } from '../ui/strings'

function statusIcon(entry: AuditEntry): { icon: string; label: string; className: string } {
  if (entry.executed) {
    return { icon: '✓', label: strings.auditExecuted, className: 'text-emerald-400' }
  }
  if (!entry.decision.approved) {
    return { icon: '✕', label: strings.auditRejected, className: 'text-slate-500' }
  }
  return { icon: '!', label: strings.auditFailed, className: 'text-red-400' }
}

export function AuditLog({ entries }: { entries: AuditEntry[] }) {
  if (entries.length === 0) return null
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
        {strings.auditLogHeading}
      </h2>
      <ul className="space-y-3">
        {entries.map((entry) => {
          const { icon, label, className } = statusIcon(entry)
          return (
            <li key={entry.action.id} className="text-sm">
              <div className="flex items-center gap-2">
                <span className={`font-bold ${className}`}>{icon}</span>
                <span className="font-medium text-slate-200">{entry.action.tool_name}</span>
                <span className={`text-xs ${className}`}>{label}</span>
              </div>
              <p className="ml-6 text-xs text-slate-500">{entry.result_summary}</p>
              <p className="ml-6 text-xs text-slate-600">
                {new Date(entry.timestamp).toLocaleString()}
              </p>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
