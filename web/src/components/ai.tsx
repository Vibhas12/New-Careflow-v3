/** Phase 6 AI panels: "Explain with AI" (insights agent – aggregates only) and the advisory "AI safety check" (reviewer agent). */
import { useState } from 'react'
import { useAgents } from '../api/assistant'
import { useExplain, useSafetyCheck, type InsightsOut, type Metric, type PerfFilter, type SafetyReview } from '../api/metrics'
import { fmtDateTime } from '../lib/format'
import { Icon } from './Icon'
import { useToast } from './Toast'

export const useAgentOn = (name: string) => !!useAgents().data?.agents.find((a) => a.name === name && a.enabled)

const KIND = { observation: ['f', 'Observation'], caveat: ['m', 'Caveat'], question: ['s', 'Worth asking'] } as const

export function InsightsPanel({ page, filter, kpis }: { page: 'performance' | 'executive'; filter: PerfFilter; kpis: Metric[] }) {
  const on = useAgentOn('insights')
  const toast = useToast()
  const explain = useExplain(page)
  const [out, setOut] = useState<InsightsOut | null>(null)
  const label = new Map(kpis.map((k) => [k.key, k.label]))
  if (!on) return null
  return (
    <div className="card mt">
      <div className="row sp" style={{ flexWrap: 'wrap', gap: 8 }}>
        <h2 style={{ margin: 0 }}><Icon name="spark" /> Explain these figures</h2>
        <button className="btn s" disabled={explain.isPending} onClick={() => explain.mutate(filter, { onSuccess: setOut, onError: (e) => toast(e.message, true) })}>
          <Icon name="spark" small /> {explain.isPending ? 'Asking Gemini…' : out ? 'Explain again with AI' : 'Explain with AI'}</button>
      </div>
      <p className="sm mut mt2">Gemini receives only the aggregate figures on this page (values, sample sizes, definitions) – no patient records and no names. The
        explanation is shown only if every number matches a figure here, and it may not rank people, claim causes or read too much into small samples.</p>
      {out && <div className="mt2">
        {out.statements.map((s, i) => (
          <div key={i} className={`fact ${s.kind === 'caveat' ? 'missing' : s.kind === 'question' ? 'suggestion' : 'fact'}`}>
            <span className={`tag ${KIND[s.kind][0]}`}>{KIND[s.kind][1]}</span>{s.text}
            {s.metrics.map((k) => <span key={k} className="chip" title={label.get(k) ?? k}>{label.get(k) ?? k}</span>)}
          </div>
        ))}
        <div className="sm mut mt2"><Icon name="spark" small /> Written by Gemini · {out.model} · {fmtDateTime(out.generatedAt)} · checked against the figures</div>
      </div>}
    </div>
  )
}

/** Optional second opinion on an AI output that is already shown. Advisory: it never changes, hides or approves anything. */
export function SafetyCheck({ path }: { path: string }) {
  const on = useAgentOn('reviewer')
  const toast = useToast()
  const check = useSafetyCheck()
  const [r, setR] = useState<SafetyReview | null>(null)
  if (!on) return null
  return (
    <span style={{ display: 'contents' }}>
      <button className="btn ghost s" disabled={check.isPending} title="Ask a second AI reviewer to check this AI text against the records (advisory)"
        onClick={() => check.mutate(path, { onSuccess: setR, onError: (e) => toast(e.message, true) })}>
        <Icon name="shield" small /> {check.isPending ? 'Checking…' : 'AI safety check'}</button>
      {r && <div className="mt2" style={{ flexBasis: '100%' }}>
        {r.verdict === 'no concerns'
          ? <div className="sm" style={{ color: 'var(--grn)' }}><Icon name="check" small /> Second-opinion review: no concerns found ({r.model}). You still decide.</div>
          : <div className="hl sm"><b style={{ color: 'var(--amb)' }}>Second-opinion review raised {r.concerns.length} concern(s)</b> ({r.model}) – advisory only, nothing was changed:
            <ul style={{ margin: '4px 0', paddingLeft: 18 }}>{r.concerns.map((c, i) => <li key={i}><span className={`badge ${c.severity === 'high' ? 'b-high' : 'b-med'}`}>{c.severity}</span> {c.issue}
              {c.quote && <span className="mut"> – “{c.quote}”</span>}</li>)}</ul>
            Consider editing (Modify) or regenerating the AI text.</div>}
      </div>}
    </span>
  )
}
