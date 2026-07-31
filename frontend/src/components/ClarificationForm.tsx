import { useState } from 'react'
import { EvidenceUpload } from './EvidenceUpload'
import { strings } from '../ui/strings'

export function ClarificationForm({
  questions,
  evidenceFiles,
  busy,
  onUpload,
  onSubmit,
}: {
  questions: string[]
  evidenceFiles: string[]
  busy: boolean
  onUpload: (file: File) => void
  onSubmit: (answers: Record<string, string>) => void
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({})

  const allAnswered = questions.every((question) => (answers[question] ?? '').trim().length > 0)

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
        {strings.clarificationHeading}
      </h2>
      <div className="space-y-3">
        {questions.map((question) => (
          <div key={question}>
            <p className="mb-1 text-sm text-slate-200">{question}</p>
            <input
              type="text"
              value={answers[question] ?? ''}
              disabled={busy}
              onChange={(event) =>
                setAnswers((prev) => ({ ...prev, [question]: event.target.value }))
              }
              placeholder={strings.answerPlaceholder}
              className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-cyan-600 focus:outline-none disabled:opacity-60"
            />
          </div>
        ))}
      </div>

      <button
        type="button"
        disabled={!allAnswered || busy}
        onClick={() => onSubmit(answers)}
        className="mt-4 rounded bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {strings.clarificationSubmitButton}
      </button>

      <div className="mt-4 border-t border-slate-800 pt-4">
        <EvidenceUpload files={evidenceFiles} disabled={busy} onUpload={onUpload} />
      </div>
    </div>
  )
}
