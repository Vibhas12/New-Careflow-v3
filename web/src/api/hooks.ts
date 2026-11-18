/** Server-state hooks (TanStack Query). Pages fetch only what they show – there is no client-side copy of the database. */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { DemoAccount, Page, PatientDetail, PatientListItem, Priority, PriorityEntry, User, UserBrief } from './types'

export const keys = {
  me: ['me'] as const,
  patients: (q: object) => ['patients', q] as const,
  patient: (id: string) => ['patient', id] as const,
  priorityHistory: (id: string) => ['priority-history', id] as const,
}

export const useMe = () =>
  useQuery({ queryKey: keys.me, queryFn: () => api<User>('/api/auth/me'), retry: false, staleTime: 5 * 60_000 })

export const useDemoAccounts = () =>
  useQuery({ queryKey: ['demo-accounts'], queryFn: () => api<DemoAccount[]>('/api/auth/demo-accounts'), retry: false, staleTime: Infinity })

export const useUsers = () => useQuery({ queryKey: ['users'], queryFn: () => api<UserBrief[]>('/api/users'), staleTime: 10 * 60_000 })

export function useLogin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: { email: string; password: string }) => api<User>('/api/auth/login', { method: 'POST', body: b }),
    onSuccess: (u) => { qc.clear(); qc.setQueryData(keys.me, u) },
  })
}

export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<void>('/api/auth/logout', { method: 'POST' }),
    onSettled: () => { qc.clear(); qc.setQueryData(keys.me, null) },
  })
}

export interface PatientQuery {
  search?: string; department?: string; priority?: Priority | ''; doctorId?: string; mine?: boolean; status?: string
  sort?: 'priority' | 'name' | 'id' | 'reviewDue' | 'nextAppt'; page?: number; pageSize?: number
}

export const usePatients = (q: PatientQuery) =>
  useQuery({ queryKey: keys.patients(q), queryFn: () => api<Page<PatientListItem>>('/api/patients', { query: { ...q } }), placeholderData: keepPreviousData })

export const usePatient = (id: string) => useQuery({ queryKey: keys.patient(id), enabled: !!id, queryFn: () => api<PatientDetail>(`/api/patients/${encodeURIComponent(id)}`) })

export const usePriorityHistory = (id: string) =>
  useQuery({ queryKey: keys.priorityHistory(id), queryFn: () => api<PriorityEntry[]>(`/api/patients/${encodeURIComponent(id)}/priority-history`) })

export function useChangePriority(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: { newPriority: Priority; comment: string }) =>
      api<PriorityEntry>(`/api/patients/${encodeURIComponent(id)}/priority`, { method: 'POST', body: b }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.patient(id) })
      qc.invalidateQueries({ queryKey: keys.priorityHistory(id) })
      qc.invalidateQueries({ queryKey: ['patients'] })
    },
  })
}
