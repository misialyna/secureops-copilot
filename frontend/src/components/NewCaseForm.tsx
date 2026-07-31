import { useState } from 'react'
import { EvidenceUpload } from './EvidenceUpload'
import { strings } from '../ui/strings'

export function NewCaseForm({
  threadId,
  evidenceFiles,
  busy,
  onSubmitDescription,
  onUpload,
  onStart,
}: {
  threadId: string | null
  evidenceFiles: string[]
  busy: boolean
  onSubmitDescription: (description: string) => void
  onUpload: (file: File) => void
  onStart: () => void
}) {
  const [description, setDescription] = useState('')
  const hasDraft = threadId !== null

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
        {strings.newCaseHeading}
      </h2>

      <label htmlFor="incident-description" className="mb-1 block text-sm text-slate-300">
        {strings.descriptionLabel}
      </label>
      <textarea
        id="incident-description"
        rows={5}
        value={description}
        disabled={hasDraft || busy}
        onChange={(event) => setDescription(event.target.value)}
        placeholder={strings.descriptionPlaceholder}
        className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-cyan-600 focus:outline-none disabled:opacity-60"
      />

      {!hasDraft && (
        <button
          type="button"
          disabled={description.trim().length === 0 || busy}
          onClick={() => onSubmitDescription(description.trim())}
          className="mt-3 rounded bg-slate-700 px-3 py-1.5 text-sm font-medium text-slate-100 hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {strings.saveDescriptionButton}
        </button>
      )}

      {hasDraft && (
        <div className="mt-4 space-y-4">
          <EvidenceUpload files={evidenceFiles} disabled={busy} onUpload={onUpload} />
          <button
            type="button"
            disabled={busy}
            onClick={onStart}
            className="rounded bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {strings.startAnalysisButton}
          </button>
        </div>
      )}
    </div>
  )
}
