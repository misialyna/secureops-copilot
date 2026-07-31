import type { StageInfo } from '../state/stages'
import { stageLabels, strings } from '../ui/strings'

function StageDot({ status }: { status: StageInfo['status'] }) {
  if (status === 'done') {
    return (
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-500 text-xs font-bold text-emerald-950">
        ✓
      </span>
    )
  }
  if (status === 'active') {
    return (
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 border-cyan-400">
        <span className="h-2 w-2 animate-pulse rounded-full bg-cyan-400" />
      </span>
    )
  }
  return <span className="h-5 w-5 shrink-0 rounded-full border-2 border-slate-700" />
}

export function Stepper({ stages }: { stages: StageInfo[] }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
        {strings.stepperHeading}
      </h2>
      <ol className="space-y-3">
        {stages.map((stage) => (
          <li key={stage.id} className="flex items-center gap-3">
            <StageDot status={stage.status} />
            <span
              className={
                stage.status === 'pending'
                  ? 'text-sm text-slate-500'
                  : stage.status === 'active'
                    ? 'text-sm font-medium text-cyan-300'
                    : 'text-sm text-slate-200'
              }
            >
              {stageLabels[stage.id]}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}
