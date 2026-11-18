/** Types mirroring the API schemas (api/app/schemas.py). */
export type Role = 'coordinator' | 'doctor' | 'admin'
export type Priority = 'high' | 'med' | 'low'

export interface User {
  id: string
  name: string
  role: Role
  title: string | null
  email: string
  departments: string[]
  mustChangePassword: boolean
}

export interface DemoAccount { name: string; role: Role; title: string | null; email: string }
export interface UserBrief { id: string; name: string; role: Role; title: string | null; departments: string[] }

export interface PatientListItem {
  id: string
  firstName: string
  lastName: string
  dob: string | null
  gender: string | null
  department: string | null
  primaryCondition: string | null
  doctorId: string | null
  doctorName: string | null
  coordId: string | null
  priority: Priority
  suggestedPriority: Priority | null
  reviewDue: string | null
  discharged: boolean
  mobile: string | null; lastVisit: string | null; nextAppt: { date: string; time: string; id: string } | null
  status: string; followUpStatus: string | null; attention: string | null; attentionKind: string | null
}

export interface Page<T> { items: T[]; total: number; page: number; pageSize: number }

export interface Appointment { id: string; doctorId: string | null; dept: string | null; apptDate: string; apptTime: string | null; type: string | null; status: string; notes: string | null }
export interface TestValue { analyte: string | null; value: string | null; unit: string | null; refRange: string | null; flag: string | null }
export interface DiagnosticTest {
  id: string; name: string; orderedBy: string | null; orderedOn: string | null; scheduledDate: string | null; status: string
  resultOn: string | null; reviewedOn: string | null; reviewNote: string | null; abnormal: boolean; resultSummary: string | null; values: TestValue[]
}
export interface Referral { id: string; referredTo: string | null; reason: string | null; status: string; createdOn: string | null }
export interface Prescription { id: string; drug: string | null; rxDate: string | null; refillDue: string | null; status: string | null }
export interface Consultation { id: string; doctorId: string | null; consultDate: string | null; notes: string | null; diagnosis: string | null; plan: string | null; followUp: string | null }
export interface HistoryEvent { id: string; eventDate: string | null; type: string | null; title: string | null; detail: string | null }

export interface PatientDetail extends PatientListItem {
  email: string | null; mobile: string | null; address: string | null; ecName: string | null; ecPhone: string | null
  secondaryConditions: string | null; previousSurgeries: string | null; familyHistory: string | null
  insProvider: string | null; policy: string | null; coverage: string | null; registeredOn: string | null
  priorityUpdatedAt: string | null; coordinatorName: string | null
  allergies: string[]; medications: string[]; diagnoses: string[]
  carePlan: { planText: string | null; startDate: string | null } | null
  appointments: Appointment[]; tests: DiagnosticTest[]; referrals: Referral[]; prescriptions: Prescription[]
  consultations: Consultation[]; history: HistoryEvent[]; tasks: Task[]
  careGaps: Alert[]; activity: { ts: string; userName: string | null; action: string; detail: string | null }[]
  documents: { id: string; filename: string; fileType: string | null; docType: string | null; extractionMethod: string | null; batchId: string | null; uploadedAt: string }[]
  canChangePriority: boolean
}

export interface PriorityEntry {
  id: number; patientId: string; previousPriority: Priority | null; newPriority: Priority; comment: string
  userId: string | null; userName: string; userRole: string; changedAt: string
}

// ---------------------------------------------------------------- phase 2
export interface Catalog { departments: string[]; appointmentTypes: string[]; testTypes: string[]; slots: string[]; taskStatuses: TaskStatus[] }
export type ApptStatus = 'Scheduled' | 'Confirmed' | 'Completed' | 'Missed' | 'Cancelled'
export interface AppointmentItem extends Appointment { patientId: string; patientName: string; doctorName: string | null }
export interface TestItem extends DiagnosticTest { patientId: string; patientName: string; department: string | null; orderedByName: string | null; priority: string | null; notes: string | null; completedOn: string | null }
export type TaskStatus = 'New' | 'In Progress' | 'Waiting for Patient' | 'Completed'
export interface TaskEvent { ts: string | null; byName: string | null; text: string | null }
export interface Task {
  id: string; title: string; patientId: string | null; patientName: string | null; priority: Priority | null; assignee: string | null
  assigneeName: string | null; created: string | null; due: string | null; status: TaskStatus; kind: string | null; source: string | null
  description: string | null; completedOn: string | null; testId: string | null; events: TaskEvent[]
}
export interface Notification { id: string; ts: string | null; title: string | null; text: string | null; route: string | null; patientId: string | null; isRead: boolean; level: string | null }

// ---------------------------------------------------------------- phase 3
export interface Issue { level: 'error' | 'warning' | 'info'; msg: string }
export interface Candidate { id: string; name: string; dob: string | null; reason: string; strength: number }
export interface IngestRecord {
  id: number; row: number | null; kind: string; mapped: Record<string, string>; status: 'matched' | 'new' | 'uncertain' | 'duplicate' | 'invalid'
  patientId: string | null; candidates: Candidate[]; issues: Issue[]; decision: 'pending' | 'import' | 'skip'; result: string | null; message: string | null; saved: string | null
  /** Phase 5: document-extraction agent suggestion – applied only when the reviewer selects Apply */
  aiSuggestion: AiImportState & { fields?: Record<string, string>; notes?: string } | null
}
export interface AiImportState { status: 'ready' | 'withheld' | 'failed' | 'blocked'; model?: string; at?: string; applied?: boolean; error?: string; issues?: string[] }
export interface UnknownColumn { header: string; kinds: string[]; shape: string; filled: string }
export interface Batch {
  id: string; filename: string; type: string | null; size: number | null; sha256: string | null; status: string; message: string | null
  uploadedBy: string | null; uploadedAt: string; confirmedAt: string | null; method: string | null; records: number; imported: number; skipped: number; failed: number
}
export interface BatchDetail extends Batch {
  recordList: IngestRecord[]; document: { id: string; text: string; method: string | null; patientId: string | null } | null; pending: number
  unknownColumns: UnknownColumn[]
  aiMapping: AiImportState & { mappings?: { header: string; field: string; reason: string }[] } | null
}
export interface DemoDataset { id: string; file: string; title: string; summary: string; effect: string; records: number }
export interface Alert {
  id: string; rule: string; category: string; ruleName: string; patientId: string; patientName: string; entity: string; priority: Priority
  reason: string; evidence: { ref: string; text: string }[]; action: { title: string; text: string; kind: string; due: string }
  assignee: string | null; assigneeName: string | null; status: 'Open' | 'Actioned' | 'Dismissed' | 'Resolved'
  firstSeen: string; lastSeen: string; resolvedAt: string | null; actionedAt: string | null; taskId: string | null; dismissReason: string | null
  /** LLM wording (Gemini) of the recommended action – only present when it matches the alert's current facts */
  aiText: string | null; aiRationale: string | null; aiTaskTitle: string | null; aiModel: string | null; aiGeneratedAt: string | null
  aiStatus: 'ready' | 'none' | 'stale' | 'withheld' | 'error' | 'off'; aiError: string | null
}
export interface AlertSummary { categories: { rule: string; category: string; description: string; open: number; high: number }[]; totalOpen: number; byStatus: Record<string, number> }
export interface JobRun { ok: boolean; at: string; trigger: string; result?: Record<string, number>; error?: string }
