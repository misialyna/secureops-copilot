import { strings } from '../ui/strings'

export function FailedView() {
  return (
    <div className="rounded-lg border border-red-700/50 bg-red-500/10 p-4">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-red-400">
        {strings.failedHeading}
      </h2>
      <p className="text-sm text-red-200">{strings.failedMessage}</p>
    </div>
  )
}
