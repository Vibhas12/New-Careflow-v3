/** Phase 3 hooks: Data Import, care gaps & alerts, background jobs. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, upload } from './client'
import type { Alert, AlertSummary, Batch, BatchDetail, DemoDataset, JobRun, Priority } from './types'

function useRefreshAll() {
  const qc = useQueryClient()
  return () => { for (const k of ['ingest', 'care-gaps', 'patients', 'patient', 'tasks', 'appointments', 'tests', 'notifications', 'jobs', 'dashboard']) qc.invalidateQueries({ queryKey: [k] }) }
}

// ---------------------------------------------------------------- data import
export const useDemoDatasets = () => useQuery({ queryKey: ['ingest', 'demo'], queryFn: () => api<DemoDataset[]>('/api/ingest/demo'), staleTime: Infinity })
export const useBatches = () => useQuery({ queryKey: ['ingest', 'batches'], queryFn: () => api<Batch[]>('/api/ingest/batches') })
export const useBatch = (id: string | null) =>
  useQuery({ queryKey: ['ingest', 'batch', id], enabled: !!id, queryFn: () => api<BatchDetail>(`/api/ingest/batches/${id}`) })

export function useIngestActions() {
  const qc = useQueryClient()
  const refresh = useRefreshAll()
  const setBatch = (b: BatchDetail) => { qc.setQueryData(['ingest', 'batch', b.id], b); qc.invalidateQueries({ queryKey: ['ingest', 'batches'] }) }
  return {
    upload: useMutation({ mutationFn: (f: File) => upload<BatchDetail>('/api/ingest/upload', f), onSuccess: setBatch, onSettled: () => qc.invalidateQueries({ queryKey: ['ingest', 'batches'] }) }),
    loadDemo: useMutation({ mutationFn: (id: string) => api<BatchDetail>(`/api/ingest/demo/${id}/load`, { method: 'POST' }), onSuccess: setBatch, onSettled: () => qc.invalidateQueries({ queryKey: ['ingest', 'batches'] }) }),
    review: useMutation({
      mutationFn: ({ rid, ...b }: { rid: number; fields?: Record<string, string | null>; patientId?: string; decision?: 'import' | 'skip' }) =>
        api<BatchDetail>(`/api/ingest/records/${rid}`, { method: 'PATCH', body: b }),
      onSuccess: setBatch,
    }),
    confirm: useMutation({
      mutationFn: (bid: string) => api<{ result: { status: string; imported: number; skipped: number; failed: number }; batch: BatchDetail }>(`/api/ingest/batches/${bid}/confirm`, { method: 'POST' }),
      onSuccess: (r) => { setBatch(r.batch); refresh() },
    }),
    cancel: useMutation({ mutationFn: (bid: string) => api<BatchDetail>(`/api/ingest/batches/${bid}/cancel`, { method: 'POST' }), onSuccess: setBatch }),
  }
}

/** Download through fetch so the session cookie and access checks apply. */
export async function downloadFile(url: string, name: string) {
  const r = await fetch(url, { credentials: 'same-origin' })
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail ?? `Download failed (${r.status})`)
  const a = document.createElement('a')
  a.href = URL.createObjectURL(await r.blob())
  a.download = name
  document.body.appendChild(a); a.click()
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove() }, 500)
}

// ---------------------------------------------------------------- care gaps
export interface AlertQuery { status?: string; rule?: string; priority?: Priority | ''; patientId?: string; mine?: boolean }
export const useAlerts = (q: AlertQuery, enabled = true) =>
  // no polling: AI wording is generated only when the user clicks "Generate with AI" (the mutation below refreshes the list)
  useQuery({ queryKey: ['care-gaps', 'list', q], enabled, queryFn: () => api<Alert[]>('/api/care-gaps', { query: { ...q } }) })
export const useAlertSummary = (mine?: boolean) =>
  useQuery({ queryKey: ['care-gaps', 'summary', mine], queryFn: () => api<AlertSummary>('/api/care-gaps/summary', { query: { mine } }) })

export function useAlertActions() {
  const refresh = useRefreshAll()
  return {
    approve: useMutation({
      mutationFn: ({ id, ...b }: { id: string; title?: string; text?: string; assignee?: string; due?: string; priority?: Priority }) =>
        api<Alert>(`/api/care-gaps/${encodeURIComponent(id)}/approve`, { method: 'POST', body: b }),
      onSuccess: refresh,
    }),
    dismiss: useMutation({
      mutationFn: ({ id, reason }: { id: string; reason: string }) => api<Alert>(`/api/care-gaps/${encodeURIComponent(id)}/dismiss`, { method: 'POST', body: { reason } }),
      onSuccess: refresh,
    }),
    scan: useMutation({ mutationFn: () => api<Record<string, number>>('/api/care-gaps/scan', { method: 'POST' }), onSuccess: refresh }),
    reword: useMutation({ mutationFn: (id: string) => api<Alert>(`/api/care-gaps/${encodeURIComponent(id)}/recommendation`, { method: 'POST' }), onSuccess: refresh }),
  }
}

// ---------------------------------------------------------------- jobs
export const useJobs = (enabled: boolean) => useQuery({ queryKey: ['jobs'], enabled, queryFn: () => api<Record<string, JobRun>>('/api/jobs') })
export function useRunJobs() {
  const refresh = useRefreshAll()
  return useMutation({ mutationFn: () => api<Record<string, JobRun>>('/api/jobs/run', { method: 'POST' }), onSuccess: refresh })
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const useAlertActivity = () => useQuery({ queryKey: ['care-gaps', 'activity'], queryFn: () => api<{ ts: string; action: string; detail: string | null; user: string | null }[]>('/api/care-gaps/activity') })
