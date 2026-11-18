/** Settings – Profile (everyone) and, for the Operations Manager (administrator), the AI agent pipeline monitor:
 *  the recorded multi-agent runs with their timed steps, KPIs, per-agent health and the background jobs.
 *  Read-only: nothing here starts an AI run; every run shown was started by a person's click. No patient references. */
import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { User } from '../api/types'
import { BarChart } from '../components/charts'
import { Icon } from '../components/Icon'
import { Banner, Empty, ErrorBanner, Kpi, Loading, PageHead, Table } from '../components/ui'
import { ROLE_LABEL, fmtDateTime } from '../lib/format'

interface Step { name: string; kind: 'code' | 'llm' | 'person'; status: string; ms: number | null; detail: string }
interface Run {
  id: number; ts: string; agent: string; label: string; status: string; model: string | null; durationMs: number | null
  attempts: { model: string; outcome: string }[]; issues: string[]; error: string | null; user: string | null; role: string | null
  steps: Step[] | null; humanStep: string
}
interface Pipeline {
  range: string; generatedAt: string; onDemandOnly: boolean
  kpis: Record<'runs' | 'aiCalls' | 'accepted' | 'withheld' | 'failed' | 'blocked' | 'limited' | 'disabled' | 'autonomousActions', number> &
    { acceptanceRate: number | null; fallbackRate: number | null; avgLlmMs: number | null; p95TotalMs: number | null; avgCodeMs: number | null }
  agents: { name: string; label: string; enabled: boolean; runs: number; ok: number; withheld: number; failed: number; blocked: number
    avgMs: number | null; p95Ms: number | null; lastRun: string | null; humanStep: string }[]
  byDay: { labels: string[]; series: Record<string, number[]> }
  topIssues: { issue: string; count: number }[]
  models: { model: string; answered: number }[]
  runs: Run[]
  jobs: Record<string, { ok: boolean; at: string; trigger: string; result?: Record<string, unknown>; error?: string }>
}

const TABS = [['profile', 'User Profile'], ['pipeline', 'AI agent pipeline']] as const
const ms = (v: number | null | undefined) => v == null ? '—' : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v * 10) / 10} ms`
const STATUS: Record<string, [string, string]> = {
  ok: ['b-low', 'Accepted'], withheld: ['b-med', 'Withheld by verifier'], failed: ['b-high', 'Provider failed'], blocked: ['b-high', 'Blocked – identifiers'],
  limited: ['b-grey', 'Limited'], disabled: ['b-grey', 'Switched off'], skipped: ['b-grey', 'Skipped'],
}
const Chip = ({ s }: { s: string }) => <span className={`badge ${STATUS[s]?.[0] ?? 'b-grey'}`}>{STATUS[s]?.[1] ?? s}</span>

export function SettingsPage({ user }: { user: User }) {
  const [sp, setSp] = useSearchParams()
  const tabs = TABS.filter(([id]) => id !== 'pipeline' || user.role === 'admin')
  const tab = tabs.some(([id]) => id === sp.get('tab')) ? sp.get('tab') : 'profile'
  return (
    <>
      <PageHead title="Settings" sub="Profile, access, configuration and audit." />
      <div className="tabs">{tabs.map(([id, l]) => <button key={id} className={'tab' + (tab === id ? ' on' : '')} onClick={() => setSp({ tab: id })}>{l}</button>)}</div>
      {tab === 'pipeline' ? <PipelineTab /> : <Profile user={user} />}
    </>
  )
}

function Profile({ user }: { user: User }) {
  return (
    <div className="card mt" style={{ maxWidth: 640 }}>
      <h2>{user.name}</h2>
      <dl className="kv" style={{ gridTemplateColumns: '120px 1fr' }}>
        <dt>Role</dt><dd>{ROLE_LABEL[user.role]}</dd><dt>Job title</dt><dd>{user.title ?? '—'}</dd><dt>Email</dt><dd>{user.email}</dd>
      </dl>
      <p className="sm mut mt2">Other settings (role management, departments, notification and reminder configuration) are being moved to the new API.</p>
    </div>
  )
}

// ---------------------------------------------------------------- AI agent pipeline (administrators)
function PipelineTab() {
  const [range, setRange] = useState('7')
  const [live, setLive] = useState(true)
  const q = useQuery({ queryKey: ['agents', 'pipeline', range], queryFn: () => api<Pipeline>('/api/agents/pipeline', { query: { range } }),
    refetchInterval: live ? 10_000 : false })                                     // reads the run log only – never starts a run
  const d = q.data
  const [sel, setSel] = useState<number | null>(null)
  const run = d?.runs.find((r) => r.id === sel) ?? d?.runs.find((r) => r.steps) ?? d?.runs[0]
  if (!d) return q.error ? <ErrorBanner error={q.error} /> : <Loading />
  const k = d.kpis
  return (
    <>
      <div className="filters">
        <label>Period<select value={range} onChange={(e) => setRange(e.target.value)}>
          {[['1', 'Last 24 hours'], ['7', 'Last 7 days'], ['30', 'Last 30 days'], ['90', 'Last 90 days'], ['all', 'All recorded']].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <span className="row sm" style={{ gap: 6, alignSelf: 'center' }}><input type="checkbox" id="pipeLive" style={{ width: 'auto' }} checked={live} onChange={(e) => setLive(e.target.checked)} />
          <label htmlFor="pipeLive">Auto-refresh every 10 s</label></span>
        <span className="sm mut">Updated {fmtDateTime(d.generatedAt)}</span>
      </div>
      <Banner icon="shield"><b>Every AI run here was started by a person</b> (Generate / Ask AI / Explain / Extract / Map / Safety check) – the AI never runs in the
        background. Steps are timed by the orchestrator as they happen. Patient references are not shown. Background jobs (reminders, care-gap scan) are plain code.</Banner>
      <div className="grid mt" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))' }}>
        <Kpi label="Agent runs" value={k.runs} hint="All requests, including those not sent" />
        <Kpi label="AI calls" value={k.aiCalls} hint="Requests that reached the model" />
        <Kpi label="Accepted by checks" value={k.acceptanceRate == null ? '—' : `${k.acceptanceRate}%`} tone="grn" hint={`${k.accepted} of ${k.aiCalls} AI calls`} />
        <Kpi label="Withheld by verifier" value={k.withheld} tone={k.withheld ? 'amb' : undefined} hint="Output discarded, template shown" />
        <Kpi label="Not sent" value={k.blocked + k.limited + k.disabled} hint={`${k.blocked} blocked · ${k.limited} limited · ${k.disabled} switched off`} />
        <Kpi label="Provider failures" value={k.failed} tone={k.failed ? 'red' : undefined} hint="Busy / quota on every model" />
        <Kpi label="Model fallback rate" value={k.fallbackRate == null ? '—' : `${k.fallbackRate}%`} hint="Calls needing a backup model" />
        <Kpi label="Avg model time" value={ms(k.avgLlmMs)} hint={`p95 end-to-end ${ms(k.p95TotalMs)}`} />
        <Kpi label="Avg code steps" value={ms(k.avgCodeMs)} hint="Context, switch, limits, privacy, verifier" />
        <Kpi label="Autonomous actions" value={k.autonomousActions} tone="grn" hint="Every output waits for a person" />
      </div>
      {!d.runs.length ? <div className="card mt"><Empty title="No agent runs in this period" hint="Runs appear here when someone clicks an AI button (for example Generate with AI on a care gap)." /></div> : (
        <div className="grid mt" style={{ gridTemplateColumns: 'minmax(0,2.2fr) minmax(260px,1fr)', alignItems: 'start' }}>
          <div>{run && <RunTrace key={run.id} r={run} />}</div>
          <div>
            {run && <RunSummary r={run} />}
            <div className="card mt"><h2>Recent runs</h2>
              <div className="list">{d.runs.slice(0, 15).map((r) => (
                <button key={r.id} className="cl" style={{ textAlign: 'left', background: r.id === run?.id ? '#eef4fb' : undefined, width: '100%' }} onClick={() => setSel(r.id)}>
                  <span className="grow"><b className="sm">{r.label}</b><br /><span className="sm mut">#{r.id} · {fmtDateTime(r.ts)}</span></span><Chip s={r.status} /></button>))}</div>
            </div>
          </div>
        </div>
      )}
      <div className="card mt"><h2>Agents</h2>
        <Table head={['Agent', 'Switch', 'Runs', 'Accepted', 'Withheld', 'Failed', 'Blocked', 'Avg time', 'p95', 'Last run', 'Next step (always a person)']}>
          {d.agents.map((a) => <tr key={a.name}><td><b>{a.label}</b><br /><span className="sm mut">{a.name}</span></td>
            <td>{a.enabled ? <span className="badge b-low">On</span> : <span className="badge b-grey">Off</span>}</td>
            <td>{a.runs}</td><td>{a.ok}</td><td>{a.withheld}</td><td>{a.failed}</td><td>{a.blocked}</td><td>{ms(a.avgMs)}</td><td>{ms(a.p95Ms)}</td>
            <td className="sm">{a.lastRun ? fmtDateTime(a.lastRun) : '—'}</td><td className="sm">{a.humanStep}</td></tr>)}
        </Table>
      </div>
      <div className="grid g2 mt">
        <div className="card"><h2>Runs per day</h2><BarChart title="Agent runs per day" labels={d.byDay.labels} series={Object.entries(d.byDay.series).map(([name, values]) => ({ name, values }))} /></div>
        <div className="card"><h2>Verifier findings (why output was withheld or blocked)</h2>
          {d.topIssues.length ? <div className="list">{d.topIssues.map((x) => <div key={x.issue}><span className="grow sm">{x.issue}</span><b>{x.count}</b></div>)}</div>
            : <Empty title="No findings in this period" />}
          <h3 className="mt2">Models that answered</h3>
          {d.models.length ? <div className="list">{d.models.map((x) => <div key={x.model}><span className="grow sm">{x.model}</span><b>{x.answered}</b></div>)}</div> : <p className="sm mut">No AI calls yet.</p>}
        </div>
      </div>
      <div className="card mt"><h2>Background jobs <span className="sm mut" style={{ fontWeight: 400 }}>– plain code, never call the AI</span></h2>
        <Table head={['Job', 'Last run', 'Trigger', 'Result']}>
          {Object.entries(d.jobs).map(([name, j]) => <tr key={name}><td><b>{name === 'deliver_reminders' ? 'Reminder delivery (simulated)' : name === 'scan_care_gaps' ? 'Care-gap rule scan' : name}</b></td>
            <td>{fmtDateTime(j.at)}</td><td className="sm">{j.trigger}</td>
            <td className="sm">{j.ok ? Object.entries(j.result ?? {}).map(([k2, v]) => `${k2}: ${v}`).join(' · ') : <span style={{ color: 'var(--red)' }}>{j.error}</span>}</td></tr>)}
        </Table>
        {!Object.keys(d.jobs).length && <p className="sm mut">No scheduler run recorded yet (the embedded scheduler runs every 5 minutes).</p>}
      </div>
    </>
  )
}

/** One run's pipeline as a stepper. Replay reveals the recorded steps in order; the pace is for readability, the times are real. */
function RunTrace({ r }: { r: Run }) {
  const steps = useMemo(() => r.steps ?? [], [r.steps])
  const [speed, setSpeed] = useState(1)
  const [shown, setShown] = useState(steps.length)
  useEffect(() => {
    if (shown >= steps.length) return
    const s = steps[shown]
    const t = setTimeout(() => setShown(shown + 1), Math.min(1500, Math.max(350, (s?.ms ?? 0) * 0.6 + 350)) / speed)
    return () => clearTimeout(t)
  }, [shown, steps, speed])
  const done = steps.filter((s) => s.status !== 'skipped').length
  const total = steps.reduce((n, s) => n + (s.ms ?? 0), 0)
  const llmCalls = steps.some((s) => s.kind === 'llm' && s.status !== 'skipped') ? 1 : 0
  return (
    <>
      <div className="card" style={{ background: '#0f2236', color: '#fff', borderColor: '#0f2236' }}>
        <div className="row sp" style={{ alignItems: 'flex-start', flexWrap: 'wrap', gap: 10 }}>
          <div>
            <div className="sm b" style={{ color: '#7fe3d4', letterSpacing: '.04em' }}><Icon name="spark" small /> PIPELINE EXECUTION · RUN-{r.id}</div>
            <div style={{ fontSize: 19, fontWeight: 700, marginTop: 4 }}>{r.label}</div>
            <div className="sm" style={{ color: '#b8c7d6' }}>Trigger: on request by {r.user ?? 'unknown'}{r.role ? ` (${ROLE_LABEL[r.role as User['role']] ?? r.role})` : ''} · {fmtDateTime(r.ts)}</div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 28, fontWeight: 700, fontFamily: 'monospace' }}>{ms(r.durationMs)}</div>
            <div className="sm" style={{ color: '#b8c7d6' }}>MEASURED END-TO-END TIME</div>
          </div>
        </div>
        <div style={{ height: 6, background: '#22384f', borderRadius: 4, margin: '12px 0 8px', overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${steps.length ? (100 * Math.min(shown, steps.length)) / steps.length : 100}%`, background: 'linear-gradient(90deg,#2ec4b6,#6f8cff)', transition: 'width .3s' }} /></div>
        <div className="row sp sm" style={{ color: '#b8c7d6', flexWrap: 'wrap', gap: 8 }}>
          <span>{done}/{steps.length || '—'} steps · {llmCalls} AI call · step total {ms(total)}</span>
          <span>Result <Chip s={r.status} /></span>
          <span className="row" style={{ gap: 4 }}>{[1, 2, 4].map((x) => <button key={x} className="btn s" style={{ padding: '2px 8px', background: speed === x ? '#2ec4b6' : '#22384f', borderColor: '#22384f' }} onClick={() => setSpeed(x)}>{x}×</button>)}
            <button className="btn s" style={{ background: '#22384f', borderColor: '#22384f' }} disabled={!steps.length} onClick={() => setShown(0)}><Icon name="play" small /> Replay</button></span>
        </div>
        <div className="sm mt2" style={{ color: '#8aa0b5' }}>Step times are measured by the orchestrator. The replay pace is only for readability.</div>
      </div>
      {!steps.length ? <div className="card mt"><Empty title="Step detail not recorded" hint="This run was made before step timing was added (v3.7). New runs show every step." /></div> : (
        <div className="mt">
          {steps.slice(0, shown).map((s, i) => <StepCard key={i} n={i + 1} s={s} />)}
          {shown >= steps.length && <StepCard n={steps.length + 1} s={{ name: 'Human decision', kind: 'person', status: r.status === 'ok' ? 'awaiting' : 'n/a', ms: null, detail: r.status === 'ok' ? r.humanStep : 'Nothing to decide – the rule / template text is shown instead.' }} />}
        </div>
      )}
    </>
  )
}

function StepCard({ n, s }: { n: number; s: Step }) {
  const color = s.status === 'ok' ? 'var(--grn)' : s.status === 'skipped' || s.status === 'n/a' ? '#9aa8b6' : s.status === 'awaiting' ? 'var(--amb)' : s.status === 'withheld' ? 'var(--amb)' : 'var(--red)'
  return (
    <div className="row" style={{ alignItems: 'stretch', gap: 10, marginBottom: 8 }}>
      <div style={{ width: 30, flex: 'none', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <div style={{ width: 28, height: 28, borderRadius: 8, background: color, color: '#fff', display: 'grid', placeItems: 'center' }}>
          <Icon name={s.status === 'ok' ? 'check' : s.status === 'awaiting' ? 'users' : s.status === 'skipped' || s.status === 'n/a' ? 'x' : 'alert'} small /></div>
        <div style={{ flex: 1, width: 2, background: 'var(--line)', marginTop: 4 }} />
      </div>
      <div className="card" style={{ flex: 1, padding: '10px 14px', borderStyle: s.status === 'skipped' ? 'dashed' : undefined }}>
        <div className="row sp" style={{ flexWrap: 'wrap', gap: 6 }}>
          <span className="row" style={{ gap: 6, flexWrap: 'wrap' }}><b>{n}. {s.name}</b>
            <span className="tag" style={{ background: s.kind === 'llm' ? '#efe8fb' : s.kind === 'person' ? '#fff4e0' : '#e7f4f1', color: s.kind === 'llm' ? '#6b45bd' : s.kind === 'person' ? '#9a5b00' : '#1d7c6b' }}>
              {s.kind === 'llm' ? 'AI · 1 request' : s.kind === 'person' ? 'Person' : 'Deterministic · no AI'}</span>
            {s.status === 'awaiting' ? <span className="badge b-med">Awaiting a person</span> : s.status === 'n/a' ? <span className="badge b-grey">Not needed</span>
              : s.status === 'ok' ? <span className="badge b-low">Complete</span> : <Chip s={s.status} />}</span>
          <span style={{ fontFamily: 'monospace', fontWeight: 700 }}>{ms(s.ms)}</span>
        </div>
        {s.detail && <div className="sm mut mt2">{s.detail}</div>}
      </div>
    </div>
  )
}

function RunSummary({ r }: { r: Run }) {
  const steps = r.steps ?? []
  const slow = steps.filter((s) => s.ms != null).sort((a, b) => (b.ms ?? 0) - (a.ms ?? 0))[0]
  const max = Math.max(1, ...steps.map((s) => s.ms ?? 0))
  const verifier = steps.find((s) => s.name === 'Verifier')
  return (
    <>
      <div className="card"><h2>Run summary</h2>
        <dl className="kv" style={{ gridTemplateColumns: '120px 1fr' }}>
          <dt>Run ID</dt><dd>RUN-{r.id}</dd><dt>Agent</dt><dd>{r.agent}</dd><dt>Result</dt><dd><Chip s={r.status} /></dd>
          <dt>Model</dt><dd>{r.model ?? '—'}</dd>
          <dt>Attempts</dt><dd className="sm">{r.attempts.length ? r.attempts.map((x) => `${x.model}: ${x.outcome}`).join(' → ') : '—'}</dd>
          <dt>Verifier</dt><dd>{verifier ? <Chip s={verifier.status} /> : '—'}</dd>
          <dt>Autonomous actions</dt><dd>0</dd><dt>Slowest step</dt><dd>{slow ? `${slow.name} (${ms(slow.ms)})` : '—'}</dd>
        </dl>
        {(r.issues.length > 0 || r.error) && <div className="hl sm mt2">{r.issues.length ? r.issues.join('; ') : r.error}</div>}
      </div>
      {steps.length > 0 && <div className="card mt"><h2>Timeline</h2>
        {steps.map((s, i) => <div key={i} style={{ margin: '7px 0' }}><div className="row sp sm"><span>{s.name}</span><span className="mut">{s.ms == null ? 'skipped' : ms(s.ms)}</span></div>
          <div className="bar"><i style={{ width: `${s.ms == null ? 0 : Math.max(2, (100 * s.ms) / max)}%`, background: s.kind === 'llm' ? '#6f8cff' : '#2ec4b6' }} /></div></div>)}
      </div>}
    </>
  )
}
