import { strings } from '../ui/strings'

export function FailedView({ onReset }: { onReset: () => void }) {
  return (
    <div className="rounded-lg border border-red-700/50 bg-red-500/10 p-4">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-red-400">
        {strings.failedHeading}
      </h2>
      <p className="mb-3 text-sm text-red-200">{strings.failedMessage}</p>
      <button
        type="button"
        onClick={onReset}
        className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-500"
      >
        {strings.newIncidentButton}
      </button>
    </div>
  )
}
