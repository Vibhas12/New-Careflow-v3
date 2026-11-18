/** AI Care Assistant hooks (template-based agents on the server – no language model). */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { Alert, Priority } from './types'

export interface Fact { text: string; kind: 'fact' | 'suggestion' | 'missing'; sources: number[]; alertId?: string; priority?: Priority }
export interface Brief {
  patientId: string; patientName: string; generatedAt: string
  sections: { context: Fact[]; history: Fact[]; gaps: Fact[]; appointments: Fact[]; results: Fact[]; next: Fact[] }
  evidence: { n: number; ref: string; label: string; ts: string | null }[]
}
export interface Proposal {
  id: string; type: 'task' | 'reminder'; patientId: string; title: string; assignee: string | null; assigneeName: string | null
  due: string | null; priority: Priority; channel: string | null; message: string | null; status: 'Proposed' | 'Approved' | 'Rejected'; resultRef: string | null
}
export type Block =
  | { type: 'table'; head: string[]; rows: { t: string; pid: string | null }[][] }
  | { type: 'brief'; brief: Brief }
  | { type: 'gapActions'; alerts: Alert[] }
  | { type: 'proposals'; proposals: Proposal[] }
export interface ChatMessage { id: number; ts: string; role: 'user' | 'ai'; text: string; patientId: string | null; blocks: Block[]; trace: string[] }

export const usePrompts = () => useQuery({ queryKey: ['assistant', 'prompts'], queryFn: () => api<string[]>('/api/assistant/prompts') })
export const useChat = () => useQuery({ queryKey: ['assistant', 'messages'], queryFn: () => api<ChatMessage[]>('/api/assistant/messages') })

/** Explicit "Generate / Regenerate summary" – fetched on demand (and audited), not on page load. */
export const usePatientSummary = (pid: string, enabled: boolean) =>
  useQuery({ queryKey: ['assistant', 'summary', pid], enabled, queryFn: () => api<Brief>(`/api/assistant/patients/${pid}/summary`), staleTime: Infinity })

function useRefresh() {
  const qc = useQueryClient()
  return () => { for (const k of ['assistant', 'tasks', 'care-gaps', 'patient', 'patients', 'dashboard', 'notifications']) qc.invalidateQueries({ queryKey: [k] }) }
}

export function useAssistantActions() {
  const qc = useQueryClient()
  const refresh = useRefresh()
  return {
    ask: useMutation({
      mutationFn: (b: { text: string; patientId?: string }) => api<ChatMessage>('/api/assistant/messages', { method: 'POST', body: b }),
      onSuccess: () => qc.invalidateQueries({ queryKey: ['assistant', 'messages'] }),
    }),
    clear: useMutation({ mutationFn: () => api<void>('/api/assistant/messages', { method: 'DELETE' }), onSuccess: () => qc.invalidateQueries({ queryKey: ['assistant', 'messages'] }) }),
    decide: useMutation({
      mutationFn: ({ id, approve }: { id: string; approve: boolean }) => api<Proposal>(`/api/assistant/proposals/${id}/${approve ? 'approve' : 'reject'}`, { method: 'POST' }),
      onSuccess: refresh,
    }),
  }
}
