import { useCallback, useEffect, useState } from 'react'
import {
  ApiError,
  createIncident,
  getIncident,
  listEvidence,
  resumeWithAnswers,
  resumeWithApprovals,
  startIncident,
  uploadEvidence,
} from '../api/client'
import type { ApprovalDecision, IncidentResponse } from '../api/types'
import { strings } from '../ui/strings'

export type PendingAction =
  | 'restore'
  | 'create'
  | 'upload'
  | 'start'
  | 'resumeAnswers'
  | 'resumeApprovals'
  | null

const THREAD_PARAM = 'thread'

function readThreadFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get(THREAD_PARAM)
}

function writeThreadToUrl(threadId: string | null): void {
  const url = new URL(window.location.href)
  if (threadId) {
    url.searchParams.set(THREAD_PARAM, threadId)
  } else {
    url.searchParams.delete(THREAD_PARAM)
  }
  window.history.replaceState({}, '', url)
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 429) return strings.errorRateLimited
    if (err.status === 404) return strings.errorNotFound
    if (err.status === 409) return strings.errorConflict
    return err.message || strings.errorGeneric
  }
  return strings.errorGeneric
}

export function useIncidentSession() {
  const [threadId, setThreadId] = useState<string | null>(() => readThreadFromUrl())
  const [incident, setIncident] = useState<IncidentResponse | null>(null)
  const [evidenceFiles, setEvidenceFiles] = useState<string[]>([])
  const [pending, setPending] = useState<PendingAction>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    writeThreadToUrl(threadId)
  }, [threadId])

  // Restore session on first load only, e.g. after a page refresh that landed on ?thread=...
  useEffect(() => {
    const initialThreadId = readThreadFromUrl()
    if (!initialThreadId) return
    let cancelled = false
    setPending('restore')
    Promise.all([getIncident(initialThreadId), listEvidence(initialThreadId)])
      .then(([incidentRes, evidenceRes]) => {
        if (cancelled) return
        setIncident(incidentRes)
        setEvidenceFiles(evidenceRes.files)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(describeError(err))
      })
      .finally(() => {
        if (!cancelled) setPending(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const submitDraft = useCallback(async (description: string) => {
    setPending('create')
    setError(null)
    try {
      const res = await createIncident(description)
      setThreadId(res.thread_id)
      setIncident(res)
    } catch (err) {
      setError(describeError(err))
    } finally {
      setPending(null)
    }
  }, [])

  const addEvidence = useCallback(
    async (file: File) => {
      if (!threadId) return
      setPending('upload')
      setError(null)
      try {
        const res = await uploadEvidence(threadId, file)
        setEvidenceFiles((prev) => [...prev, res.filename])
      } catch (err) {
        setError(describeError(err))
      } finally {
        setPending(null)
      }
    },
    [threadId],
  )

  const start = useCallback(async () => {
    if (!threadId) return
    setPending('start')
    setError(null)
    try {
      const res = await startIncident(threadId)
      setIncident(res)
    } catch (err) {
      setError(describeError(err))
    } finally {
      setPending(null)
    }
  }, [threadId])

  const submitAnswers = useCallback(
    async (answers: Record<string, string>) => {
      if (!threadId) return
      setPending('resumeAnswers')
      setError(null)
      try {
        const res = await resumeWithAnswers(threadId, answers)
        setIncident(res)
      } catch (err) {
        setError(describeError(err))
      } finally {
        setPending(null)
      }
    },
    [threadId],
  )

  const submitApprovals = useCallback(
    async (approvals: ApprovalDecision[]) => {
      if (!threadId) return
      setPending('resumeApprovals')
      setError(null)
      try {
        const res = await resumeWithApprovals(threadId, approvals)
        setIncident(res)
      } catch (err) {
        setError(describeError(err))
      } finally {
        setPending(null)
      }
    },
    [threadId],
  )

  const clearError = useCallback(() => setError(null), [])

  return {
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
  }
}
