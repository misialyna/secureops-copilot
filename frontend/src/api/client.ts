import type {
  ApprovalDecision,
  EvidenceListResponse,
  EvidenceUploadResponse,
  IncidentResponse,
  ReportResponse,
} from './types'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new ApiError(response.status, body?.detail ?? response.statusText)
  }
  return response.json() as Promise<T>
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function createIncident(description: string): Promise<IncidentResponse> {
  return postJson('/incidents', { description })
}

export function startIncident(threadId: string): Promise<IncidentResponse> {
  return postJson(`/incidents/${threadId}/start`, undefined)
}

export function getIncident(threadId: string): Promise<IncidentResponse> {
  return apiFetch(`/incidents/${threadId}`)
}

export function getReport(threadId: string): Promise<ReportResponse> {
  return apiFetch(`/incidents/${threadId}/report`)
}

export function resumeWithAnswers(
  threadId: string,
  answers: Record<string, string>,
): Promise<IncidentResponse> {
  return postJson(`/incidents/${threadId}/resume`, { answers })
}

export function resumeWithApprovals(
  threadId: string,
  approvals: ApprovalDecision[],
): Promise<IncidentResponse> {
  return postJson(`/incidents/${threadId}/resume`, { approvals })
}

export function uploadEvidence(threadId: string, file: File): Promise<EvidenceUploadResponse> {
  const formData = new FormData()
  formData.append('file', file)
  return apiFetch(`/incidents/${threadId}/evidence`, { method: 'POST', body: formData })
}

export function listEvidence(threadId: string): Promise<EvidenceListResponse> {
  return apiFetch(`/incidents/${threadId}/evidence`)
}
