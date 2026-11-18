/** Renderers for assistant output – same markup as V2 chatBlock() / briefHTML(): labelled facts, numbered source chips, evidence list. */
import { Link } from 'react-router-dom'
import { useAssistantActions, type Block, type Brief, type Fact, type Proposal } from '../api/assistant'
import { useAlertActions } from '../api/phase3'
import type { Alert } from '../api/types'
import { fmtDate, fmtDateTime } from '../lib/format'
import { Icon } from './Icon'
import { useToast } from './Toast'

const TAG = { fact: ['f', 'Recorded fact'], suggestion: ['s', 'AI suggestion'], missing: ['m', 'Missing information'] } as const

function FactRow({ f, b, card }: { f: Fact; b: Brief; card?: boolean }) {
  const toast = useToast()
  const { approve } = useAlertActions()
  return (
    <div className={`fact ${f.kind}`}>
      <span className={`tag ${TAG[f.kind][0]}`}>{TAG[f.kind][1]}</span>{f.text}
      {f.sources.map((n) => { const e = b.evidence[n - 1]; return <span key={n} className="chip" title={`${e?.label ?? ''} ${e?.ref ?? ''} · ${fmtDateTime(e?.ts)}`}>{n}</span> })}
      {f.alertId && card && <div className="row mt2"><button className="btn s" disabled={approve.isPending}
        onClick={() => approve.mutate({ id: f.alertId! }, { onSuccess: (r) => toast(`Approved – task ${r.taskId} created and tracked`), onError: (e) => toast(e.message, true) })}>
        Approve &amp; create task</button></div>}
    </div>
  )
}

/** Patient brief. `cards` = profile tab layout (one card per section); otherwise the compact chat layout.
 *  `useAi` shows the stored LLM summary's overview and narrative sections; next steps always come from the rule engine. */
export function BriefView({ b, cards, useAi }: { b: Brief; cards?: boolean; useAi?: boolean }) {
  const ai = useAi && b.ai?.status === 'ready' ? b.ai : null
  const s = ai ? { ...b.sections, context: ai.context ?? [], history: ai.history ?? [], gaps: ai.gaps ?? [], appointments: ai.appointments ?? [], results: ai.results ?? [] } : b.sections
  const sections: [string, Fact[]][] = cards
    ? [...(ai ? [['Overview', ai.overview ?? []] as [string, Fact[]]] : []),
       ['Current patient context', s.context], ['Relevant medical history', s.history], ['Outstanding care gaps', s.gaps], ['Upcoming appointments', s.appointments],
       ['Pending results & referrals', s.results]]
    : [['1. Patient context', s.context], ['2. Relevant history', s.history], ['3. Outstanding activities', [...s.gaps, ...s.appointments, ...s.results]]]
  const evidence = (
    <div className="list">{b.evidence.map((e) => (
      <div key={e.n}><span className="chip" style={{ margin: 0 }}>{e.n}</span>
        <span className="grow">{/^PT-/.test(e.ref) ? <Link className="b" to={`/patients/${e.ref}`}>{e.label} {e.ref}</Link> : <b style={{ color: 'var(--blue)' }}>{e.label} {e.ref}</b>}</span>
        <span className="sm mut">{fmtDateTime(e.ts)}</span></div>))}</div>
  )
  const Wrap = ({ t, children }: { t: string; children: React.ReactNode }) => cards ? <div className="card mt2"><h2>{t}</h2>{children}</div> : <div className="mt2"><h3>{t}</h3>{children}</div>
  return (
    <>
      {sections.map(([t, items]) => <Wrap key={t} t={t}>{items.map((f, i) => <FactRow key={i} f={f} b={b} card={cards} />)}</Wrap>)}
      <Wrap t={cards ? 'Relevant evidence & sources' : '4. Evidence and source references'}>{evidence}</Wrap>
      <Wrap t={cards ? 'Suggested next steps' : '5. Suggested next actions'}>{s.next.map((f, i) => <FactRow key={i} f={f} b={b} card={cards} />)}</Wrap>
    </>
  )
}

function GapActions({ alerts }: { alerts: Alert[] }) {
  const toast = useToast()
  const { approve } = useAlertActions()
  return (
    <div className="prop">
      <div className="sm b" style={{ color: '#6b45bd' }}><Icon name="spark" small /> Suggested next actions <span className="tag s" style={{ marginLeft: 6 }}>AI suggestion – requires approval</span></div>
      {alerts.slice(0, 5).map((a) => (
        <div key={a.id} className="row sp mt2"><span className="sm"><b>{a.patientName} ({a.patientId})</b>: {a.aiStatus === 'ready' && a.aiText ? a.aiText : a.action.text}</span>
          <button className="btn s" disabled={approve.isPending} onClick={() => approve.mutate({ id: a.id }, { onSuccess: (r) => toast(`Approved – task ${r.taskId} created`), onError: (e) => toast(e.message, true) })}>
            Approve &amp; create task</button></div>
      ))}
    </div>
  )
}

function Proposals({ items }: { items: Proposal[] }) {
  const toast = useToast()
  const { decide } = useAssistantActions()
  const act = (x: Proposal, approve: boolean) => decide.mutate({ id: x.id, approve }, {
    onSuccess: (r) => toast(approve ? `Approved – ${r.type === 'task' ? `task ${r.resultRef} created` : 'simulated reminder recorded'}` : 'Proposal rejected – nothing was created'),
    onError: (e) => toast(e.message, true) })
  return <>{items.map((x) => (
    <div key={x.id} className="prop">
      <div className="sm b" style={{ color: '#6b45bd' }}>Proposed {x.type} <span className="tag s">{x.status}</span></div>
      <div className="mt2"><b>{x.title}</b> for <Link className="b" to={`/patients/${x.patientId}`}>{x.patientId}</Link></div>
      <div className="sm mut">{x.type === 'task' ? `Assigned to ${x.assigneeName ?? '—'} · due ${fmtDate(x.due)}` : `Channel ${x.channel} (simulated): ${x.message}`}</div>
      {x.status === 'Proposed' && <div className="row mt2">
        <button className="btn s" disabled={decide.isPending} onClick={() => act(x, true)}><Icon name="check" small /> Approve</button>
        <button className="btn dng s" disabled={decide.isPending} onClick={() => act(x, false)}>Reject</button></div>}
      {x.resultRef && <div className="sm mt2">Created <b>{x.resultRef}</b>.</div>}
    </div>
  ))}</>
}

/** LLM answer (phase 4): labelled statements with numbered source chips, then the cited records. */
function AnswerView({ b }: { b: Extract<Block, { type: 'answer' }> }) {
  const ev = new Map(b.evidence.map((e) => [e.n, e]))
  return (
    <div className="mt2">
      {b.statements.map((s, i) => (
        <div key={i} className={`fact ${s.kind}`}>
          <span className={`tag ${TAG[s.kind][0]}`}>{TAG[s.kind][1]}</span>{s.text}
          {s.sources.map((n) => { const e = ev.get(n); return <span key={n} className="chip" title={`${e?.label ?? ''} ${e?.ref ?? ''} · ${fmtDateTime(e?.ts)}`}>{n}</span> })}
          {s.patientId && <> <Link className="sm" to={`/patients/${s.patientId}`}>Open profile</Link></>}
        </div>
      ))}
      {b.evidence.length > 0 && <details className="mt2"><summary className="sm">Sources ({b.evidence.length})</summary><div className="list">{b.evidence.map((e) => (
        <div key={e.n}><span className="chip" style={{ margin: 0 }}>{e.n}</span><span className="grow sm"><b>{e.label}</b> {e.ref}</span><span className="sm mut">{fmtDateTime(e.ts)}</span></div>))}</div></details>}
    </div>
  )
}

export function ChatBlock({ b }: { b: Block }) {
  if (b.type === 'answer') return <AnswerView b={b} />
  if (b.type === 'table') return (
    <div className="tw mt2"><table className="tbl"><thead><tr>{b.head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
      <tbody>{b.rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c.pid ? <Link className="b" to={`/patients/${c.pid}`}>{c.t}</Link> : c.t}</td>)}</tr>)}</tbody></table></div>
  )
  if (b.type === 'brief') return <BriefView b={b.brief} />
  if (b.type === 'gapActions') return b.alerts.length ? <GapActions alerts={b.alerts} /> : null
  return <Proposals items={b.proposals} />
}
