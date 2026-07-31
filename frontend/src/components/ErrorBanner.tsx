export function ErrorBanner({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-red-700/50 bg-red-500/10 p-3 text-sm text-red-300">
      <span>{message}</span>
      <button
        type="button"
        onClick={onDismiss}
        className="shrink-0 text-red-400 hover:text-red-200"
        aria-label="Zamknij"
      >
        ✕
      </button>
    </div>
  )
}
