import { useState } from 'react'
import type { ApprovalDecision, ProposedAction } from '../api/types'
import { strings } from '../ui/strings'

interface DecisionDraft {
  approved: boolean | null
  comment: string
}

function ActionCard({
  action,
  draft,
  busy,
  onChange,
}: {
  action: ProposedAction
  draft: DecisionDraft
  busy: boolean
  onChange: (next: DecisionDraft) => void
}) {
  return (
    <div className="rounded border border-slate-800 bg-slate-950 p-3">
      <p className="text-sm font-medium text-slate-100">{action.tool_name}</p>
      <p className="mt-1 text-xs text-slate-500">
        <span className="font-semibold text-slate-400">{strings.approvalJustification}: </span>
        {action.justification}
      </p>
      <p className="mt-1 text-xs text-amber-300">
        <span className="font-semibold">{strings.approvalRiskNote}: </span>
        {action.risk_note}
      </p>

      <div className="mt-2">
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
          {strings.approvalCommandsHeading}
        </p>
        {action.preview ? (
          <pre className="overflow-x-auto rounded bg-slate-900 p-2 text-xs text-slate-300">
            {JSON.stringify(action.preview.findings, null, 2)}
          </pre>
        ) : (
          <p className="text-xs text-slate-600">{strings.approvalNoPreview}</p>
        )}
      </div>

      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => onChange({ ...draft, approved: true })}
          className={`rounded px-3 py-1 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${
            draft.approved === true
              ? 'bg-emerald-600 text-white'
              : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
          }`}
        >
          {strings.approveButton}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => onChange({ ...draft, approved: false })}
          className={`rounded px-3 py-1 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${
            draft.approved === false
              ? 'bg-red-600 text-white'
              : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
          }`}
        >
          {strings.rejectButton}
        </button>
      </div>

      <input
        type="text"
        value={draft.comment}
        disabled={busy}
        onChange={(event) => onChange({ ...draft, comment: event.target.value })}
        placeholder={strings.commentPlaceholder}
        className="mt-2 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100 placeholder:text-slate-600 focus:border-cyan-600 focus:outline-none disabled:opacity-60"
      />
    </div>
  )
}

export function ApprovalPanel({
  actions,
  busy,
  onSubmit,
}: {
  actions: ProposedAction[]
  busy: boolean
  onSubmit: (decisions: ApprovalDecision[]) => void
}) {
  const [drafts, setDrafts] = useState<Record<string, DecisionDraft>>(() =>
    Object.fromEntries(actions.map((action) => [action.id, { approved: null, comment: '' }])),
  )

  const allDecided = actions.every((action) => drafts[action.id]?.approved !== null)

  function handleSubmit() {
    const decisions: ApprovalDecision[] = actions.map((action) => ({
      action_id: action.id,
      approved: drafts[action.id]?.approved ?? false,
      decided_at: new Date().toISOString(),
      comment: drafts[action.id]?.comment || null,
    }))
    onSubmit(decisions)
  }

  return (
    <div className="rounded-lg border border-cyan-700/50 bg-slate-900 p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-cyan-400">
        {strings.approvalHeading}
      </h2>
      <div className="space-y-3">
        {actions.map((action) => (
          <ActionCard
            key={action.id}
            action={action}
            draft={drafts[action.id] ?? { approved: null, comment: '' }}
            busy={busy}
            onChange={(next) => setDrafts((prev) => ({ ...prev, [action.id]: next }))}
          />
        ))}
      </div>

      {!allDecided && <p className="mt-3 text-xs text-slate-500">{strings.decisionRequiredHint}</p>}

      <button
        type="button"
        disabled={!allDecided || busy}
        onClick={handleSubmit}
        className="mt-4 rounded bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {strings.submitDecisionsButton}
      </button>
    </div>
  )
}
