import type { Citation, DiagnosticPlan } from '../api/types'
import { strings } from '../ui/strings'

function CitationBadges({ citations, numberOf }: { citations: Citation[]; numberOf: Map<Citation, number> }) {
  if (citations.length === 0) return null
  return (
    <span className="ml-1 inline-flex gap-1">
      {citations.map((citation, index) => (
        <abbr
          key={index}
          title={`${citation.source_id}, s. ${citation.page}`}
          className="cursor-help rounded bg-slate-800 px-1 text-xs font-medium text-cyan-300 no-underline"
        >
          [{numberOf.get(citation)}]
        </abbr>
      ))}
    </span>
  )
}

export function DiagnosticPlanView({ plan }: { plan: DiagnosticPlan }) {
  const sortedSteps = [...plan.steps].sort((a, b) => a.priority - b.priority)

  const numberOf = new Map<Citation, number>()
  let nextNumber = 1
  for (const step of sortedSteps) {
    for (const citation of step.citations) {
      numberOf.set(citation, nextNumber)
      nextNumber += 1
    }
  }

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
        {strings.planHeading}
      </h2>
      <ol className="space-y-3">
        {sortedSteps.map((step, index) => (
          <li key={index} className="rounded border border-slate-800 bg-slate-950 p-3">
            <div className="mb-1 flex items-center gap-2">
              <span className="rounded bg-slate-800 px-1.5 py-0.5 text-xs font-medium text-slate-300">
                {strings.priorityLabel} {step.priority}
              </span>
            </div>
            <p className="text-sm text-slate-200">
              {step.description}
              <CitationBadges citations={step.citations} numberOf={numberOf} />
            </p>
            <p className="mt-1 text-xs text-slate-500">{step.rationale}</p>
            <p className="mt-1 text-xs text-slate-600">
              {strings.expectedEvidenceLabel}: {step.expected_evidence}
            </p>
          </li>
        ))}
      </ol>

      {plan.caveats.length > 0 && (
        <div className="mt-4 rounded border border-amber-600/40 bg-amber-500/10 p-3">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-amber-400">
            {strings.planCaveatsHeading}
          </p>
          <ul className="list-inside list-disc space-y-1 text-sm text-amber-200">
            {plan.caveats.map((caveat, index) => (
              <li key={index}>{caveat}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
