/** Phase 6: Doctor Performance / Executive Overview (aggregates only), "Explain with AI" and the advisory "AI safety check". */
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from './client'

export interface Metric { key: string; label: string; value: number | null; display: string; unit: '%' | 'count' | 'days'; n: number | null; definition: string }
export interface Weekly { labels: string[]; series: Record<string, (number | null)[]> }
export interface PerformanceData {
  range: string; doctorId: string | null; dept: string | null; kpis: Metric[]; weekly: Weekly
  doctors: { id: string; name: string }[]; departments: string[]
}
export interface DeptRow { department: string; attendance: number | null; attendanceN: number; testCompletion: number | null; testN: number; followupCompletion: number | null; followupN: number; openGaps: number }
export interface ExecutiveData { range: string; kpis: Metric[]; weekly: Weekly; departments: DeptRow[]; aiUsage: { label: string; value: number }[] }
export interface Insight { text: string; kind: 'observation' | 'caveat' | 'question'; metrics: string[] }
export interface InsightsOut { ok: true; model: string; generatedAt: string; statements: Insight[] }
export interface SafetyReview { ok: true; verdict: 'no concerns' | 'concerns'; concerns: { issue: string; severity: 'low' | 'high'; quote: string }[]; model: string; checkedAt: string }

export interface PerfFilter { doctorId?: string; dept?: string; range: string }
export const usePerformance = (f: PerfFilter) =>
  useQuery({ queryKey: ['metrics', 'performance', f], queryFn: () => api<PerformanceData>('/api/metrics/performance', { query: { ...f } }) })
export const useExecutive = (range: string) =>
  useQuery({ queryKey: ['metrics', 'executive', range], queryFn: () => api<ExecutiveData>('/api/metrics/executive', { query: { range } }) })

/** One click → one request; the server recomputes the figures and sends only aggregates. */
export const useExplain = (page: 'performance' | 'executive') =>
  useMutation({ mutationFn: (f: PerfFilter) => api<InsightsOut>(`/api/metrics/${page}/explain`, { method: 'POST', body: f }) })

export const useSafetyCheck = () =>
  useMutation({ mutationFn: (path: string) => api<SafetyReview>(path, { method: 'POST' }) })
