/** Phase 2 hooks: appointments, diagnostic tests, tasks, referrals, consultations, notifications. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { AppointmentItem, Catalog, Consultation, Notification, Priority, Referral, Task, TaskStatus, TestItem } from './types'

/** After any workflow action, refresh everything it can affect (lists, the patient page, notifications). */
function useInvalidateAll() {
  const qc = useQueryClient()
  return () => {
    for (const k of ['appointments', 'tests', 'tasks', 'patient', 'patients', 'notifications', 'slots', 'dashboard', 'care-gaps']) qc.invalidateQueries({ queryKey: [k] })
  }
}

function useAction<TBody, TResult>(fn: (b: TBody) => Promise<TResult>) {
  const refresh = useInvalidateAll()
  return useMutation({ mutationFn: fn, onSuccess: refresh })
}

export const useCatalog = () => useQuery({ queryKey: ['catalog'], queryFn: () => api<Catalog>('/api/catalog'), staleTime: Infinity })

// ---------------------------------------------------------------- appointments
export interface ApptQuery { from?: string; to?: string; doctorId?: string; status?: string; patientId?: string }
export const useAppointments = (q: ApptQuery) =>
  useQuery({ queryKey: ['appointments', q], queryFn: () => api<{ items: AppointmentItem[]; total: number }>('/api/appointments', { query: { ...q } }) })

export const useSlots = (doctorId: string, date: string, ignore?: string) =>
  useQuery({
    queryKey: ['slots', doctorId, date, ignore], enabled: !!doctorId && !!date,
    queryFn: () => api<{ slots: string[] }>('/api/appointments/slots', { query: { doctorId, date, ignore } }),
  })

export interface BookBody { patientId: string; doctorId: string; date: string; time: string; type: string; notes?: string }
export const useBookAppointment = () => useAction((b: BookBody) => api<AppointmentItem>('/api/appointments', { method: 'POST', body: b }))
export const useApptAction = () =>
  useAction(({ id, action, body }: { id: string; action: 'confirm' | 'complete' | 'miss' | 'cancel' | 'reschedule'; body?: object }) =>
    api<AppointmentItem>(`/api/appointments/${id}/${action}`, { method: 'POST', body }))

// ---------------------------------------------------------------- diagnostic tests
export type TestStage = 'requested' | 'scheduled' | 'awaiting-result' | 'review' | 'reviewed' | 'all'
export const useTests = (stage: TestStage, patientId?: string) =>
  useQuery({ queryKey: ['tests', stage, patientId], queryFn: () => api<TestItem[]>('/api/tests', { query: { stage, patientId } }) })
export const useRequestTest = () =>
  useAction((b: { patientId: string; name: string; priority: 'Routine' | 'Urgent'; notes?: string }) => api<TestItem>('/api/tests', { method: 'POST', body: b }))
export const useTestAction = () =>
  useAction(({ id, action, body }: { id: string; action: 'schedule' | 'complete' | 'result' | 'review'; body?: object }) =>
    api<TestItem>(`/api/tests/${id}/${action}`, { method: 'POST', body }))

// ---------------------------------------------------------------- tasks
export interface TaskQuery { assignee?: string; status?: TaskStatus; patientId?: string; overdue?: boolean; includeCompleted?: boolean }
export const useTasks = (q: TaskQuery) => useQuery({ queryKey: ['tasks', q], queryFn: () => api<Task[]>('/api/tasks', { query: { ...q } }) })
export interface TaskBody { title: string; patientId?: string; assignee: string; due: string; priority: Priority; kind: string; description?: string }
export const useCreateTask = () => useAction((b: TaskBody) => api<Task>('/api/tasks', { method: 'POST', body: b }))
export const useUpdateTask = () =>
  useAction(({ id, ...b }: { id: string; status?: TaskStatus; assignee?: string; due?: string; priority?: Priority; note?: string }) =>
    api<Task>(`/api/tasks/${id}`, { method: 'PATCH', body: b }))

// ---------------------------------------------------------------- referrals & consultations
export const useCreateReferral = (patientId: string) =>
  useAction((b: { referredTo: string; reason: string }) => api<Referral>(`/api/patients/${patientId}/referrals`, { method: 'POST', body: b }))
export const useReferralStatus = () =>
  useAction(({ id, status }: { id: string; status: 'Booked' | 'Completed' | 'Cancelled' }) => api<Referral>(`/api/referrals/${id}/status`, { method: 'POST', body: { status } }))
export interface ConsultBody { date: string; notes: string; diagnosis?: string; prescription?: string; plan?: string; followUp?: string; instructions?: string; createFollowUpTask: boolean }
export const useRecordConsultation = (patientId: string) =>
  useAction((b: ConsultBody) => api<Consultation>(`/api/patients/${patientId}/consultations`, { method: 'POST', body: b }))

// ---------------------------------------------------------------- notifications
export const useNotifications = () =>
  useQuery({ queryKey: ['notifications'], queryFn: () => api<{ items: Notification[]; unread: number }>('/api/notifications'), refetchInterval: 60_000 })
export function useReadNotifications() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id?: string) => api<void>(id ? `/api/notifications/${id}/read` : '/api/notifications/read-all', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  })
}

// ---------------------------------------------------------------- look-and-feel support (dashboards, appointment dialog, calls, reminders)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const useDashboard = () => useQuery({ queryKey: ['dashboard'], queryFn: () => api<any>('/api/dashboard') })
export interface ApptReminder { id: string; label: string | null; channel: string | null; status: string | null; scheduledFor: string | null; sentAt: string | null }
export const useAppointment = (id: string | null) =>
  useQuery({ queryKey: ['appointments', 'one', id], enabled: !!id, queryFn: () => api<AppointmentItem & { reminders: ApptReminder[] }>(`/api/appointments/${id}`) })
export const useLogCall = (patientId: string) =>
  useAction((b: { outcome: string; notes?: string }) => api<void>(`/api/patients/${patientId}/calls`, { method: 'POST', body: b }))
export const useSendReminder = (patientId: string) =>
  useAction((b: { type: string; channel: string; message: string; appointmentId?: string; testId?: string }) =>
    api<{ id: string; status: string }>(`/api/patients/${patientId}/reminders`, { method: 'POST', body: b }))
