import type { IncidentClassification } from '../api/types'
import { categoryLabels, severityLabels, strings } from '../ui/strings'

const SEVERITY_CLASSES: Record<IncidentClassification['severity'], string> = {
  low: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
  medium: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
  high: 'bg-orange-500/15 text-orange-300 border-orange-500/40',
  critical: 'bg-red-500/15 text-red-300 border-red-500/40',
}

export function ClassificationCard({
  classification,
}: {
  classification: IncidentClassification
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
        {strings.classificationHeading}
      </h2>
      <dl className="space-y-2 text-sm">
        <div className="flex items-center justify-between">
          <dt className="text-slate-500">{categoryLabels[classification.category]}</dt>
          <dd
            className={`rounded border px-2 py-0.5 text-xs font-medium ${SEVERITY_CLASSES[classification.severity]}`}
          >
            {severityLabels[classification.severity]}
          </dd>
        </div>
        <div className="flex items-center justify-between text-slate-400">
          <dt>{strings.confidenceLabel}</dt>
          <dd>{Math.round(classification.confidence * 100)}%</dd>
        </div>
      </dl>
      <p className="mt-3 text-sm text-slate-400">{classification.reasoning}</p>
    </div>
  )
}
