import type { IncidentCategory, Severity } from '../api/types'
import type { StageId } from '../state/stages'

/**
 * All UI copy lives here, not inline in JSX — one place to add a language switch later
 * (key -> text becomes key -> Record<Locale, text> without touching any component).
 */
export const strings = {
  appTitle: 'SecureOps Copilot',

  errorGeneric: 'Wystąpił nieoczekiwany błąd. Spróbuj ponownie.',
  errorRateLimited: 'Limit modelu został osiągnięty — spróbuj ponownie za kilka minut.',
  errorNotFound: 'Nie znaleziono zgłoszenia o podanym identyfikatorze.',
  errorConflict: 'Ta operacja nie jest teraz możliwa dla tego zgłoszenia.',

  newCaseHeading: 'Nowe zgłoszenie',
  descriptionLabel: 'Opis incydentu',
  descriptionPlaceholder:
    'Opisz, co zaobserwowano — kiedy, na jakich systemach, jakie są objawy...',
  saveDescriptionButton: 'Zapisz opis i przejdź do dowodów',
  startAnalysisButton: 'Rozpocznij analizę',

  evidenceHeading: 'Dowody',
  evidenceDropHint: 'Przeciągnij pliki tutaj lub kliknij, aby wybrać',
  evidenceUploadedListHeading: 'Wgrane pliki',
  evidenceClosedHint: 'Upload dowodów jest zamknięty — analiza przeszła już do kolejnego etapu.',

  clarificationHeading: 'Pytania doprecyzowujące',
  clarificationSubmitButton: 'Wyślij odpowiedzi',
  answerPlaceholder: 'Twoja odpowiedź...',

  planHeading: 'Plan diagnostyki',
  planCaveatsHeading: 'Zastrzeżenia',
  priorityLabel: 'Priorytet',
  expectedEvidenceLabel: 'Oczekiwany dowód',

  approvalHeading: 'Wymagana zgoda',
  approvalJustification: 'Uzasadnienie',
  approvalRiskNote: 'Uwaga o ryzyku',
  approvalCommandsHeading: 'Wygenerowane polecenia',
  approvalNoPreview: 'Brak podglądu poleceń dla tego narzędzia.',
  approveButton: 'Zatwierdź',
  rejectButton: 'Odrzuć',
  commentPlaceholder: 'Komentarz (opcjonalnie)',
  submitDecisionsButton: 'Wyślij decyzje',
  decisionRequiredHint: 'Zdecyduj o każdej z akcji przed wysłaniem.',

  reportHeading: 'Raport końcowy',
  copyReportButton: 'Kopiuj',
  copiedLabel: 'Skopiowano',
  downloadReportButton: 'Pobierz .md',
  reportWarningsLabel: 'Ostrzeżenia raportu',

  classificationHeading: 'Klasyfikacja',
  confidenceLabel: 'Pewność',

  toolResultsHeading: 'Wyniki narzędzi',
  toolFindingsHeading: 'Ustalenia',
  toolWarningsHeading: 'Ostrzeżenia',

  auditLogHeading: 'Dziennik decyzji',
  auditExecuted: 'Wykonano',
  auditRejected: 'Odrzucono',
  auditFailed: 'Nie wykonano',

  stepperHeading: 'Postęp analizy',

  loadingRestoring: 'Wczytywanie sesji...',
  loadingStarting: 'Trwa klasyfikacja i analiza — może to potrwać kilkanaście sekund...',
  loadingFinalizing: 'Wykonywanie decyzji i generowanie raportu...',
  loadingUploading: 'Wysyłanie pliku...',
} as const

export type StringKey = keyof typeof strings

export const severityLabels: Record<Severity, string> = {
  low: 'niski',
  medium: 'średni',
  high: 'wysoki',
  critical: 'krytyczny',
}

export const stageLabels: Record<StageId, string> = {
  classify: 'Klasyfikacja',
  knowledge: 'Wiedza (RAG)',
  questions: 'Pytania',
  tools: 'Narzędzia',
  plan: 'Plan',
  approvals: 'Zgody',
  report: 'Raport',
}

export const categoryLabels: Record<IncidentCategory, string> = {
  malware: 'Złośliwe oprogramowanie',
  ransomware: 'Ransomware',
  phishing: 'Phishing',
  unauthorized_access: 'Nieautoryzowany dostęp',
  denial_of_service: 'Odmowa usługi (DoS)',
  data_breach: 'Wyciek danych',
  insider_threat: 'Zagrożenie wewnętrzne',
  other: 'Inne',
}
