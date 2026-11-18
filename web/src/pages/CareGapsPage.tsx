/** Care gaps – same KPIs, filters, alert cards and side panels as V2 PAGES.caregaps (administrators: counts only). */
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useUsers } from '../api/hooks'
import { useAlertActions, useAlertActivity, useAlerts, useAlertSummary, useJobs, useRunJobs } from '../api/phase3'
import type { Alert, Priority, User } from '../api/types'
import { Field } from '../components/dialogs'
import { Icon } from '../components/Icon'
import { useToast } from '../components/Toast'
import { Banner, Empty, ErrorBanner, Kpi, Loading, Modal, PageHead, PriorityBadge, StatusBadge } from '../components/ui'
import { fmtDate, fmtDateTime } from '../lib/format'

export function CareGapsPage({ user }: { user: User }) {
  const admin = user.role === 'admin'
  const nav = useNavigate()
  const staff = (useUsers().data ?? []).filter((u) => u.role !== 'admin')
  const [f, setF] = useState({ q: '', rule: '', priority: '' as Priority | '', status: 'Open', who: '', scope: user.role === 'coordinator' ? 'mine' : 'all' })
  const [dlg, setDlg] = useState<{ kind: 'approve' | 'modify' | 'dismiss'; a: Alert } | null>(null)
  const mine = f.scope === 'mine' && user.role === 'coordinator'
  const sum = useAlertSummary(mine && !admin)
  const list = useAlerts({ status: f.status, rule: f.rule || undefined, priority: f.priority || undefined, mine: mine || undefined }, !admin)
  const logs = useAlertActivity()
  const rows = (list.data ?? []).filter((a) => (!f.who || a.assignee === f.who) && (!f.q || `${a.patientName}${a.patientId}${a.reason}`.toLowerCase().includes(f.q.toLowerCase())))

  return (
    <>
      <PageHead title="Patients Requiring Attention" sub="Care gaps detected by explainable, configurable rules. AI explains findings; people decide what to do."
        actions={admin && <button className="btn sec" onClick={() => nav('/settings')}>Configure rules</button>} />
      {admin && <Banner icon="shield">Read-only operational view. Counts are shown without patient detail; approving or dismissing alerts is done by care coordinators and doctors.</Banner>}
      <div className="grid g4" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))' }}>
        {sum.data?.categories.map((c) => <Kpi key={c.rule} label={c.category} value={c.open} tone={c.high ? 'red' : undefined} onClick={admin ? undefined : () => setF({ ...f, rule: c.rule, status: 'Open' })} />)}
      </div>
      {!admin && <>
        <div className="filters">
          <label>Search<input type="text" placeholder="Patient or reason" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} /></label>
          <label>Category<select value={f.rule} onChange={(e) => setF({ ...f, rule: e.target.value })}><option value="">All categories</option>{sum.data?.categories.map((c) => <option key={c.rule} value={c.rule}>{c.category}</option>)}</select></label>
          <label>Priority<select value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value as Priority | '' })}><option value="">All</option><option value="high">High</option><option value="med">Medium</option><option value="low">Low</option></select></label>
          <label>Status<select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>{['Open', 'Actioned', 'Dismissed', 'Resolved', 'All'].map((s) => <option key={s}>{s}</option>)}</select></label>
          <label>Team member<select value={f.who} onChange={(e) => setF({ ...f, who: e.target.value })}><option value="">All</option>{staff.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select></label>
          {user.role === 'coordinator' && <label>Scope<select value={f.scope} onChange={(e) => setF({ ...f, scope: e.target.value })}><option value="mine">My assigned patients</option><option value="all">All patients</option></select></label>}
          <span className="sm mut" style={{ marginBottom: 8 }}>{rows.length} alert(s)</span>
        </div>
        <ErrorBanner error={list.error} />
        {list.isLoading ? <Loading /> : rows.length ? rows.map((a) => <AlertCard key={a.id} a={a} onAct={(kind) => setDlg({ kind, a })} />)
          : <div className="card"><Empty title="No alerts match" hint="Try a different status or category filter." /></div>}
      </>}
      <div className="grid g2 mt">
        <div className="card"><h2><Icon name="clock" />Activity log</h2>
          <div className="list">{logs.data?.length ? logs.data.map((a, i) => <div key={i}><span className="mut nowrap sm" style={{ width: 120 }}>{fmtDateTime(a.ts)}</span><span><b>{a.action}</b> – {a.detail} <span className="mut">({a.user})</span></span></div>)
            : <Empty title="No alert actions yet" />}</div></div>
        <div className="card"><h2><Icon name="info" />How detection works</h2>
          <details><summary className="b" style={{ cursor: 'pointer' }}>Rules in use (deterministic, versioned, configurable)</summary>
            <ul style={{ paddingLeft: 18 }}>{sum.data?.categories.map((c) => <li key={c.rule} className="sm"><b>{c.category}</b> – {c.description}</li>)}</ul></details>
          <p className="sm mut">Rules re-run after every relevant action and on a schedule. AI never sets clinical risk or overrides these rules.</p>
        </div>
      </div>
      {admin && <JobsCard />}
      {dlg?.kind === 'dismiss' && <DismissDialog a={dlg.a} onClose={() => setDlg(null)} />}
      {dlg && dlg.kind !== 'dismiss' && <ApproveDialog a={dlg.a} modify={dlg.kind === 'modify'} onClose={() => setDlg(null)} />}
    </>
  )
}

function AlertCard({ a, onAct }: { a: Alert; onAct: (k: 'approve' | 'modify' | 'dismiss') => void }) {
  const toast = useToast()
  const { approve, reword } = useAlertActions()
  const quick = () => approve.mutate({ id: a.id }, { onSuccess: (r) => toast(`Approved – task ${r.taskId} created and tracked`), onError: (e) => toast(e.message, true) })
  const ai = a.aiStatus === 'ready' && a.aiText
  const regen = () => reword.mutate(a.id, { onSuccess: (r) => toast(`Recommendation worded by ${r.aiModel}`), onError: (e) => toast(e.message, true) })
  return (
    <div className="card mt2">
      <div className="row sp">
        <div className="row"><b style={{ fontSize: 15 }}><Link className="b" to={`/patients/${a.patientId}`}>{a.patientName}</Link></b><span className="mut sm">{a.patientId}</span><PriorityBadge p={a.priority} /><span className="badge b-blue">{a.category}</span></div>
        <StatusBadge s={a.status} />
      </div>
      <div className="grid g2 mt2">
        <div>
          <div className="sm mut b">Reason for alert</div><div>{a.reason}</div>
          <div className="sm mut b mt2">Supporting evidence</div>
          <ul style={{ margin: '4px 0', paddingLeft: 18 }}>{a.evidence.map((e, i) => <li key={i} className="sm"><Link to={`/patients/${a.patientId}`} style={{ textDecoration: 'underline' }}>{e.ref}</Link> – {e.text} <span className="mut">({fmtDateTime(a.firstSeen)})</span></li>)}</ul>
          <div className="sm mut">Detected {fmtDateTime(a.firstSeen)} · Assigned: <b>{a.assigneeName ?? '—'}</b> · Rule: {a.ruleName}</div>
        </div>
        <div className="prop">
          <div className="sm b" style={{ color: '#6b45bd' }}><Icon name="spark" small /> Recommended next action <span className="tag s" style={{ marginLeft: 6 }}>Suggestion – requires approval</span></div>
          <div className="mt2">{ai ? a.aiText : a.action.text}</div>
          {ai && a.aiRationale && <div className="sm mt2"><span className="mut">Why:</span> {a.aiRationale}</div>}
          <div className="sm mut mt2">Proposed task: “{ai ? a.aiTaskTitle : a.action.title}”, due {fmtDate(a.action.due)}. Detection is rule-based; AI only words the recommendation.</div>
          {a.status === 'Open' && a.aiStatus !== 'off' && (
            <div className="sm mut mt2 row" style={{ gap: 8, flexWrap: 'wrap' }}>
              {a.aiStatus === 'ready' && <span><Icon name="spark" small /> Worded by Gemini · {a.aiModel} · {fmtDateTime(a.aiGeneratedAt)}</span>}
              {a.aiStatus === 'none' && <span>Showing the rule template · AI wording runs only when you ask</span>}
              {a.aiStatus === 'stale' && <span style={{ color: 'var(--amb)' }}>Alert facts changed since the AI wording – showing the rule template</span>}
              {a.aiStatus === 'error' && <span style={{ color: 'var(--amb)' }} title={a.aiError ?? ''}>AI wording unavailable – showing the rule template</span>}
              <button className="btn ghost s" disabled={reword.isPending} onClick={regen}>{reword.isPending ? 'Asking Gemini…' : a.aiStatus === 'ready' || a.aiStatus === 'stale' ? 'Regenerate with AI' : 'Generate with AI'}</button>
            </div>
          )}
          {a.taskId && <div className="sm mt2">Task <b>{a.taskId}</b> created from this alert.</div>}
          {a.dismissReason && <div className="sm mut mt2">Dismissed: {a.dismissReason}</div>}
          {a.status === 'Resolved' && a.resolvedAt && <div className="sm mut mt2">Resolved automatically {fmtDateTime(a.resolvedAt)} – the rule no longer fires because the underlying records changed.</div>}
          {a.status === 'Open' && (
            <div className="row mt2">
              <button className="btn s" disabled={approve.isPending} onClick={quick}><Icon name="check" small /> Approve Recommendation</button>
              <button className="btn sec s" onClick={() => onAct('modify')}>Modify Recommendation</button>
              <button className="btn dng s" onClick={() => onAct('dismiss')}>Dismiss Alert</button>
              <button className="btn sec s" onClick={() => onAct('modify')}>Create Follow-up Task</button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ApproveDialog({ a, modify, onClose }: { a: Alert; modify: boolean; onClose: () => void }) {
  const toast = useToast()
  const { approve } = useAlertActions()
  const staff = (useUsers().data ?? []).filter((u) => u.role !== 'admin')
  const ai = a.aiStatus === 'ready' && a.aiText
  const [f, setF] = useState({ title: `${ai ? a.aiTaskTitle : a.action.title} – ${a.patientName}`, text: (ai ? a.aiText : a.action.text) ?? '', assignee: a.assignee ?? '', due: a.action.due, priority: a.priority })
  const [err, setErr] = useState('')
  const submit = () => {
    if (modify && !f.title.trim()) return setErr('Title is required')
    approve.mutate(modify ? { id: a.id, ...f } : { id: a.id }, { onSuccess: (r) => { toast(`${modify ? 'Modified recommendation approved' : 'Approved'} – task ${r.taskId} created`); onClose() }, onError: (e) => setErr(e.message) })
  }
  return (
    <Modal title="Modify recommendation" onClose={onClose} submit="Approve modified recommendation" onSubmit={submit} busy={approve.isPending}>
      <div className="hl sm">{a.reason}</div>
      <div className="fg mt">
        <Field label="Task title" req full error={err}><input type="text" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
        <Field label="Action details" full><textarea rows={3} value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} /></Field>
        <Field label="Assign to"><select value={f.assignee} onChange={(e) => setF({ ...f, assignee: e.target.value })}>{staff.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select></Field>
        <Field label="Due date"><input type="date" value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })} /></Field>
        <Field label="Priority"><select value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value as Priority })}><option value="high">High</option><option value="med">Medium</option><option value="low">Low</option></select></Field>
      </div>
    </Modal>
  )
}

function DismissDialog({ a, onClose }: { a: Alert; onClose: () => void }) {
  const toast = useToast()
  const { dismiss } = useAlertActions()
  const [reason, setReason] = useState('')
  const [err, setErr] = useState('')
  return (
    <Modal title="Dismiss alert" onClose={onClose} submit="Dismiss alert" danger busy={dismiss.isPending} onSubmit={() => {
      if (!reason.trim()) return setErr('A reason is required')
      dismiss.mutate({ id: a.id, reason }, { onSuccess: () => { toast('Alert dismissed and logged'); onClose() }, onError: (e) => setErr(e.message) })
    }}>
      <p><b>{a.category}</b> – {a.patientName} ({a.patientId})</p><p className="mut">{a.reason}</p>
      <div className="fg"><Field label="Reason for dismissing (recorded in audit log)" req full error={err}><textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} /></Field></div>
    </Modal>
  )
}

function JobsCard() {
  const jobs = useJobs(true)
  const run = useRunJobs()
  const toast = useToast()
  const names: Record<string, string> = { deliver_reminders: 'Reminder delivery (simulated)', scan_care_gaps: 'Care-gap scan' }
  return (
    <div className="card mt">
      <div className="row sp"><h2><Icon name="clock" />Background jobs</h2>
        <button className="btn sec s" disabled={run.isPending} onClick={() => run.mutate(undefined, { onSuccess: () => toast('Jobs run completed'), onError: (e) => toast(e.message, true) })}>Run now</button></div>
      {jobs.isLoading ? <Loading /> : (
        <table className="tbl mt2"><thead><tr><th>Job</th><th>Last run</th><th>Trigger</th><th>Result</th></tr></thead>
          <tbody>{Object.entries(names).map(([k, label]) => {
            const j = jobs.data?.[k]
            return <tr key={k}><td>{label}</td><td>{j ? fmtDateTime(j.at) : 'Never'}</td><td>{j?.trigger ?? '—'}</td>
              <td className="sm">{!j ? '—' : j.ok ? Object.entries(j.result ?? {}).map(([x, y]) => `${x}: ${y}`).join(' · ') : <span style={{ color: 'var(--red)' }}>{j.error}</span>}</td></tr>
          })}</tbody></table>
      )}
    </div>
  )
}
