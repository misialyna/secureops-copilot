import { ApprovalPanel } from './components/ApprovalPanel'
import { AuditLog } from './components/AuditLog'
import { ClarificationForm } from './components/ClarificationForm'
import { ClassificationCard } from './components/ClassificationCard'
import { DiagnosticPlanView } from './components/DiagnosticPlanView'
import { ErrorBanner } from './components/ErrorBanner'
import { NewCaseForm } from './components/NewCaseForm'
import { ReportView } from './components/ReportView'
import { ReportWarningsBadge } from './components/ReportWarningsBadge'
import { Spinner } from './components/Spinner'
import { Stepper } from './components/Stepper'
import { ToolResultsAccordion } from './components/ToolResultsAccordion'
import { deriveStages } from './state/stages'
import { useIncidentSession } from './state/useIncidentSession'
import { strings } from './ui/strings'

function App() {
  const {
    threadId,
    incident,
    evidenceFiles,
    pending,
    error,
    submitDraft,
    addEvidence,
    start,
    submitAnswers,
    submitApprovals,
    clearError,
  } = useIncidentSession()

  const busy = pending !== null
  const stages = deriveStages(incident, pending)

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <header className="border-b border-slate-800 px-6 py-4">
        <h1 className="text-lg font-semibold tracking-tight text-slate-100">
          {strings.appTitle}
        </h1>
      </header>

      <main className="mx-auto grid max-w-6xl grid-cols-1 gap-4 p-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          {error && <ErrorBanner message={error} onDismiss={clearError} />}

          {pending === 'restore' && <Spinner label={strings.loadingRestoring} />}

          {pending !== 'restore' && (!incident || incident.status === 'draft') && (
            <NewCaseForm
              threadId={threadId}
              evidenceFiles={evidenceFiles}
              busy={busy}
              onSubmitDescription={submitDraft}
              onUpload={addEvidence}
              onStart={start}
            />
          )}

          {incident?.status === 'awaiting_clarification' && (
            <ClarificationForm
              questions={incident.pending_questions ?? []}
              evidenceFiles={evidenceFiles}
              busy={busy}
              onUpload={addEvidence}
              onSubmit={submitAnswers}
            />
          )}

          {(pending === 'start' || pending === 'resumeAnswers') && (
            <Spinner label={strings.loadingStarting} />
          )}

          {incident?.plan && <DiagnosticPlanView plan={incident.plan} />}

          {incident?.status === 'awaiting_approval' && incident.proposed_actions && (
            <ApprovalPanel
              actions={incident.proposed_actions}
              busy={busy}
              onSubmit={submitApprovals}
            />
          )}

          {pending === 'resumeApprovals' && <Spinner label={strings.loadingFinalizing} />}

          {incident?.status === 'completed' && incident.report && (
            <ReportView markdown={incident.report} />
          )}
        </div>

        <aside className="space-y-4 lg:sticky lg:top-6 lg:self-start">
          <Stepper stages={stages} />
          {incident?.classification && (
            <ClassificationCard classification={incident.classification} />
          )}
          {incident?.tool_results && <ToolResultsAccordion results={incident.tool_results} />}
          {incident?.audit_log && <AuditLog entries={incident.audit_log} />}
          <ReportWarningsBadge count={incident?.report_warnings?.length ?? 0} />
        </aside>
      </main>
    </div>
  )
}

export default App
