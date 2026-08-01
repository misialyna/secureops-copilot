import type { IncidentResponse } from '../api/types'
import type { PendingAction } from './useIncidentSession'

export type StageId = 'classify' | 'knowledge' | 'questions' | 'tools' | 'plan' | 'approvals' | 'report'
export type StageStatus = 'pending' | 'active' | 'done'

export interface StageInfo {
  id: StageId
  status: StageStatus
}

const STAGE_ORDER: StageId[] = [
  'classify',
  'knowledge',
  'questions',
  'tools',
  'plan',
  'approvals',
  'report',
]

/**
 * The API only ever reports one of four coarse statuses (draft / awaiting_clarification /
 * awaiting_approval / completed) — it has no concept of "which graph node is running right
 * now". This derives a best-effort, coarse-grained stepper from that plus which request (if
 * any) is currently in flight: a whole group of stages is shown as "active" together while a
 * single long-running call (e.g. /start, which runs classify through plan in one shot) is
 * pending, since the frontend genuinely has no finer-grained signal than "waiting".
 */
export function deriveStages(
  incident: IncidentResponse | null,
  pending: PendingAction,
  sawClarification = false,
): StageInfo[] {
  const done = new Set<StageId>()
  const active = new Set<StageId>()
  const status = incident?.status

  if (status === 'awaiting_clarification') {
    done.add('classify')
  } else if (status === 'awaiting_approval') {
    done.add('classify')
    done.add('knowledge')
    done.add('tools')
    done.add('plan')
  } else if (status === 'completed') {
    for (const id of STAGE_ORDER) done.add(id)
  } else if (status === 'failed') {
    // Whatever the response still carries reflects real progress made before the crash —
    // e.g. classification/plan/audit_log can all be present even though report never ran.
    if (incident?.classification) done.add('classify')
    if (incident?.sources) done.add('knowledge')
    if (incident?.tool_results) done.add('tools')
    if (incident?.plan) done.add('plan')
    if (incident?.audit_log) done.add('approvals')
  }

  // ZNALEZISKO #10: once past awaiting_clarification, nothing in `incident` says clarification
  // ever happened — sawClarification is the caller's client-side memory of having seen that
  // status earlier this session (see useIncidentSession). Applied after the branches above so
  // it can't be overridden by them.
  if (sawClarification && status && status !== 'awaiting_clarification' && status !== 'draft') {
    done.add('questions')
  }

  if (pending === 'start' || pending === 'resumeAnswers') {
    for (const id of ['classify', 'knowledge', 'tools', 'plan'] as StageId[]) {
      if (!done.has(id)) active.add(id)
    }
  } else if (pending === 'resumeApprovals') {
    active.add('approvals')
    active.add('report')
  } else if (status === 'awaiting_clarification') {
    active.add('questions')
  } else if (status === 'awaiting_approval') {
    active.add('approvals')
  }

  return STAGE_ORDER.map((id) => ({
    id,
    status: done.has(id) ? 'done' : active.has(id) ? 'active' : 'pending',
  }))
}
