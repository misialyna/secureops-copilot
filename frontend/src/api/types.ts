/**
 * Manually mirrors backend/app/graph/schemas.py, backend/app/tools/{approval,registry}.py,
 * backend/app/rag/retriever.py and backend/app/main.py. Kept by hand (no codegen) — update
 * this file whenever those change.
 */

export type IncidentCategory =
  | "malware"
  | "ransomware"
  | "phishing"
  | "unauthorized_access"
  | "denial_of_service"
  | "data_breach"
  | "insider_threat"
  | "other"

export type Severity = "low" | "medium" | "high" | "critical"

export type IncidentStatus =
  | "draft"
  | "awaiting_clarification"
  | "awaiting_approval"
  | "completed"
  | "failed"

export interface IncidentClassification {
  category: IncidentCategory
  severity: Severity
  confidence: number
  reasoning: string
  missing_info: string[]
}

export interface Citation {
  source_id: string
  page: number
}

export interface DiagnosticStep {
  description: string
  rationale: string
  expected_evidence: string
  priority: number
  citations: Citation[]
}

export interface DiagnosticPlan {
  steps: DiagnosticStep[]
  caveats: string[]
}

export interface RetrievedChunk {
  text: string
  source_id: string
  title: string
  page: number
  score: number
}

export interface ToolResult {
  tool_name: string
  summary: string
  findings: Record<string, unknown>[]
  warnings: string[]
}

export interface ProposedAction {
  tool_name: string
  args: Record<string, unknown>
  justification: string
  risk_note: string
  id: string
  /** Populated server-side from the same function that would execute the tool — see
   * registry.preview_tool(). null when the tool has no preview_fn. */
  preview: ToolResult | null
}

export interface ApprovalDecision {
  action_id: string
  approved: boolean
  /** ISO 8601 datetime string. */
  decided_at: string
  comment?: string | null
}

export interface AuditEntry {
  action: ProposedAction
  decision: ApprovalDecision
  executed: boolean
  result_summary: string
  /** ISO 8601 datetime string. */
  timestamp: string
}

export interface IncidentResponse {
  thread_id: string
  status: IncidentStatus
  pending_questions?: string[] | null
  proposed_actions?: ProposedAction[] | null
  classification?: IncidentClassification | null
  plan?: DiagnosticPlan | null
  sources?: RetrievedChunk[] | null
  tool_results?: ToolResult[] | null
  audit_log?: AuditEntry[] | null
  report?: string | null
  report_warnings?: string[] | null
}

export interface ReportResponse {
  markdown: string
  /** ISO 8601 datetime string. */
  generated_at: string
  warnings: string[]
}

export interface EvidenceUploadResponse {
  thread_id: string
  filename: string
  size_bytes: number
}

export interface EvidenceListResponse {
  thread_id: string
  files: string[]
}
