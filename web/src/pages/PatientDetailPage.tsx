/** Patient profile – same header, tabs and cards as V2 PAGES.patient (overview, history, appointments, tests, care journey, AI summary, consultation). */
import { useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useChangePriority, useMe, usePatient, usePriorityHistory, useUsers } from '../api/hooks'
import { downloadFile } from '../api/phase3'
import type { PatientDetail, Priority, Task, TestItem } from '../api/types'
import { useReferralStatus, useTests } from '../api/workflows'
import { usePatientSummary } from '../api/assistant'
import { BriefView } from '../components/assistant'
import { AppointmentDetailDialog, TaskDetailDialog, TestDetailDialog } from '../components/details'
import { BookAppointmentDialog, CallDialog, ConsultationForm, Field, ReferralDialog, ReminderDialog, RequestTestDialog, TaskDialog } from '../components/dialogs'
import { Icon } from '../components/Icon'
import { useToast } from '../components/Toast'
import { Avatar, Banner, Empty, ErrorBanner, Loading, Modal, PriorityBadge, StatusBadge, Table } from '../components/ui'
import { todayIso } from '../lib/dates'
import { PRIORITY_LABEL, ROLE_LABEL, age, fmtDate, fmtDateTime, fmtDS } from '../lib/format'

const PRI_FULL: Record<Priority, string> = { high: 'High priority', med: 'Medium priority', low: 'Low priority' }
type Dlg = { k: 'book' } | { k: 'call' } | { k: 'remind' } | { k: 'task' } | { k: 'test' } | { k: 'ref' } | { k: 'priority' }
  | { k: 'appt'; id: string } | { k: 'testd'; t: TestItem } | { k: 'taskd'; t: Task } | null

export function PatientDetailPage() {
  const { id = '' } = useParams()
  const [sp, setSp] = useSearchParams()
  const nav = useNavigate()
  const me = useMe().data
  const q = usePatient(id)
  const tests = useTests('all', id)
  const users = useUsers().data ?? []
  const [dlg, setDlg] = useState<Dlg>(null)
  const tab = sp.get('tab') ?? 'overview'
  const setTab = (t: string) => setSp(t === 'overview' ? {} : { tab: t }, { replace: true })

  if (q.isLoading) return <Loading />
  if (q.error) return (
    <div className="card" style={{ maxWidth: 560, margin: '40px auto', textAlign: 'center' }}>
      <div style={{ color: 'var(--blue)' }}><Icon name="shield" /></div><h2 style={{ justifyContent: 'center' }}>{q.error instanceof ApiError && q.error.status === 404 ? 'Patient not found' : 'Access restricted'}</h2>
      <p className="mut">{q.error instanceof ApiError && q.error.status === 404 ? 'It may not exist, or it is not assigned to you.' : q.error.message}</p>
      <button className="btn" onClick={() => nav('/')}>Back to dashboard</button>
    </div>
  )
  const p = q.data!
  const name = `${p.firstName} ${p.lastName}`
  const doctor = me?.role === 'doctor', ownDoctor = doctor && p.doctorId === me?.id
  const docName = (uid: string | null) => users.find((u) => u.id === uid)?.name ?? '—'
  const close = () => setDlg(null)
  const tabs: [string, string][] = [['overview', 'Overview'], ['history', 'Medical History'], ['appts', 'Appointments'], ['tests', 'Diagnostic Tests'], ['journey', 'Care Journey'], ['ai', 'AI Summary'],
    ...(ownDoctor ? [['consult', 'Consultation'] as [string, string]] : [])]
  const testItems = tests.data ?? []
  const openTest = (tid: string) => { const t = testItems.find((x) => x.id === tid); if (t) setDlg({ k: 'testd', t }) }
  const nextAppt = p.nextAppt ? { id: p.nextAppt.id, date: p.nextAppt.date, time: p.nextAppt.time, doctorName: p.doctorName } : null

  return (
    <>
      <div className="row" style={{ marginBottom: 8 }}><button className="btn ghost s" onClick={() => nav(-1)}><Icon name="chevl" small /> Back</button></div>
      <div className="card">
        <div className="row" style={{ alignItems: 'flex-start', gap: 16 }}>
          <Avatar name={name} lg />
          <div className="grow" style={{ flex: 1, minWidth: 260 }}>
            <div className="row"><h1 style={{ margin: 0 }}>{name}</h1><span className={`badge b-${p.priority}`}>{PRI_FULL[p.priority]}</span>
              {p.canChangePriority && <button className="btn ghost s" title="Change priority (comment required)" onClick={() => setDlg({ k: 'priority' })}>Change priority</button>}
              <StatusBadge s={p.status} /></div>
            <div className="sm mut" style={{ margin: '2px 0 8px' }}>{p.id} · {age(p.dob)} years · {p.gender} · DOB {fmtDate(p.dob)}</div>
            <div className="grid g3 sm">
              <div><span className="mut">Contact</span><br />{p.mobile}<br />{p.email || 'No email recorded'}</div>
              <div><span className="mut">Address</span><br />{p.address || '—'}</div>
              <div><span className="mut">Emergency contact</span><br />{p.ecName} · {p.ecPhone}</div>
              <div><span className="mut">Primary condition</span><br /><b>{p.primaryCondition}</b></div>
              <div><span className="mut">Assigned doctor</span><br />{p.doctorName ?? '—'}</div>
              <div><span className="mut">Care coordinator</span><br />{p.coordinatorName ?? '—'}</div>
            </div>
          </div>
        </div>
        <div className="row mt">
          {doctor ? <>
            {ownDoctor && <button className="btn" onClick={() => setTab('consult')}><Icon name="stetho" small /> Start consultation</button>}
            <button className={ownDoctor ? 'btn sec' : 'btn'} onClick={() => setDlg({ k: 'book' })}><Icon name="cal" small /> Schedule appointment</button>
            <button className="btn sec" onClick={() => setDlg({ k: 'task' })}>Create task</button>
          </> : <>
            <button className="btn" onClick={() => setDlg({ k: 'book' })}><Icon name="cal" small /> Schedule appointment</button>
            <button className="btn sec" onClick={() => setDlg({ k: 'call' })}><Icon name="phone" small /> Call</button>
            <button className="btn sec" onClick={() => setDlg({ k: 'remind' })}><Icon name="send" small /> Send reminder</button>
            <button className="btn sec" onClick={() => setDlg({ k: 'task' })}><Icon name="task" small /> Create task</button>
          </>}
        </div>
      </div>
      <div className="tabs" role="tablist">{tabs.map(([k, l]) => <button key={k} role="tab" className={'tab' + (tab === k ? ' on' : '')} onClick={() => setTab(k)}>{l}</button>)}</div>

      {tab === 'overview' && <><Overview p={p} docName={docName} onAppt={(aid) => setDlg({ k: 'appt', id: aid })} onTest={openTest} onTask={(t) => setDlg({ k: 'taskd', t })}
        onAddRef={() => setDlg({ k: 'ref' })} onAddTask={() => setDlg({ k: 'task' })} /><PriorityCard p={p} onChange={() => setDlg({ k: 'priority' })} /><DocsCard p={p} /></>}
      {tab === 'history' && <History p={p} docName={docName} />}
      {tab === 'appts' && <Appts p={p} docName={docName} onOpen={(aid) => setDlg({ k: 'appt', id: aid })} onBook={() => setDlg({ k: 'book' })} />}
      {tab === 'tests' && <>
        <div className="row sp"><h2>Diagnostic tests</h2>{ownDoctor && <button className="btn" onClick={() => setDlg({ k: 'test' })}><Icon name="plus" small /> Request test</button>}</div><div className="mt2" />
        {testItems.length ? <Table head={['Test', 'Test date', 'Ordering doctor', 'Status', 'Result availability']}>{testItems.map((t) => (
          <tr key={t.id} className="click" onClick={() => setDlg({ k: 'testd', t })}><td><b>{t.name}</b></td><td>{fmtDate(t.completedOn || t.scheduledDate)}</td><td>{t.orderedByName ?? docName(t.orderedBy)}</td>
            <td><StatusBadge s={t.status} />{t.abnormal && t.status === 'Result Available' && <> <span className="badge b-high">Flagged</span></>}</td>
            <td>{t.resultSummary ? `Available ${fmtDate(t.resultOn)}` : 'Not yet available'}</td></tr>))}</Table>
          : <div className="card"><Empty title="No diagnostic tests recorded" /></div>}
        <p className="sm mut mt2">Click a test to open its detailed report.</p>
      </>}
      {tab === 'journey' && <Journey p={p} docName={docName} />}
      {tab === 'ai' && <AiSummary pid={p.id} />}
      {tab === 'consult' && ownDoctor && <Consult p={p} docName={docName} onTest={openTest} extra={<>
        <button className="btn sec" onClick={() => setDlg({ k: 'task' })}>Create Follow-up Task</button>
        <button className="btn sec" onClick={() => setDlg({ k: 'test' })}>Request Diagnostic Test</button>
        <button className="btn sec" onClick={() => setDlg({ k: 'book' })}>Schedule Appointment</button>
        <button className="btn sec" onClick={() => setDlg({ k: 'remind' })}>Send Reminder</button>
      </>} onAddRef={() => setDlg({ k: 'ref' })} />}

      {dlg?.k === 'book' && <BookAppointmentDialog patientId={p.id} defaultDoctor={p.doctorId} onClose={close} />}
      {dlg?.k === 'call' && <CallDialog patientId={p.id} name={name} mobile={p.mobile} onClose={close} />}
      {dlg?.k === 'remind' && <ReminderDialog patientId={p.id} name={name} appt={nextAppt} onClose={close} />}
      {dlg?.k === 'task' && <TaskDialog patientId={p.id} onClose={close} />}
      {dlg?.k === 'test' && <RequestTestDialog patientId={p.id} onClose={close} />}
      {dlg?.k === 'ref' && <ReferralDialog patientId={p.id} onClose={close} />}
      {dlg?.k === 'priority' && <ChangePriorityDialog p={p} onClose={close} />}
      {dlg?.k === 'appt' && <AppointmentDetailDialog id={dlg.id} onClose={close} />}
      {dlg?.k === 'testd' && <TestDetailDialog test={dlg.t} onClose={close} />}
      {dlg?.k === 'taskd' && <TaskDetailDialog task={dlg.t} onClose={close} />}
    </>
  )
}

/** AI Summary tab – generated on request (and audited), from the patient's current records. */
function AiSummary({ pid }: { pid: string }) {
  const [asked, setAsked] = useState(false)
  const q = usePatientSummary(pid, asked)
  return (
    <>
      <Banner warn icon="spark"><b>Prototype summary agent – template-based, no language model connected.</b> It only restates recorded data, cites the source record and timestamp for each statement, and labels suggestions separately. It does not diagnose, prescribe or act on its own.</Banner>
      <div className="row sp mt2">
        <div className="sm mut">{q.data ? `Generated ${fmtDateTime(q.data.generatedAt)} from the current records` : 'Not yet generated for this patient'}</div>
        <button className="btn" disabled={q.isFetching} onClick={() => (asked ? q.refetch() : setAsked(true))}><Icon name="spark" small /> {q.isFetching ? 'Generating…' : q.data ? 'Regenerate summary' : 'Generate summary'}</button>
      </div>
      <ErrorBanner error={q.error} />
      {q.data ? <BriefView b={q.data} cards /> : <div className="card mt2"><Empty title="No summary yet" hint="Select Generate summary to assemble a grounded summary from this patient’s records." /></div>}
    </>
  )
}

const Card = ({ title, right, children, full }: { title: ReactNode; right?: ReactNode; children: ReactNode; full?: boolean }) =>
  <div className="card" style={full ? { gridColumn: '1/-1' } : undefined}><h2>{title}{right && <span className="r sm">{right}</span>}</h2>{children}</div>

function Overview({ p, docName, onAppt, onTest, onTask, onAddRef, onAddTask }: { p: PatientDetail; docName: (u: string | null) => string; onAppt: (id: string) => void
  onTest: (id: string) => void; onTask: (t: Task) => void; onAddRef: () => void; onAddTask: () => void }) {
  const toast = useToast()
  const ref = useReferralStatus()
  const T = todayIso()
  const up = p.appointments.filter((a) => ['Scheduled', 'Confirmed'].includes(a.status) && a.apptDate >= T).sort((a, b) => (a.apptDate + a.apptTime).localeCompare(b.apptDate + b.apptTime))
  const tests = p.tests.filter((t) => t.status !== 'Reviewed')
  const refs = p.referrals.filter((r) => !['Completed', 'Cancelled'].includes(r.status))
  const tasks = p.tasks.filter((k) => k.status !== 'Completed')
  const setRef = (rid: string, st: 'Booked' | 'Completed') => ref.mutate({ id: rid, status: st }, { onSuccess: () => toast(`Referral marked ${st.toLowerCase()}`), onError: (e) => toast(e.message, true) })
  return (
    <div className="grid g2">
      <Card title={<>Current condition &amp; treatment plan</>}>
        <dl className="kv"><dt>Primary</dt><dd>{p.primaryCondition}</dd><dt>Secondary</dt><dd>{p.secondaryConditions || 'None'}</dd><dt>Treatment plan</dt><dd>{p.carePlan?.planText ?? '—'}</dd>
          <dt>Allergies</dt><dd>{p.allergies.length ? p.allergies.join('; ') : 'None recorded'}</dd><dt>Medication (as recorded)</dt><dd>{p.medications.length ? p.medications.join('; ') : 'None'}</dd>
          <dt>Review due</dt><dd>{fmtDate(p.reviewDue)}</dd><dt>Insurance</dt><dd>{p.insProvider || '—'} · {p.policy || ''} · {p.coverage || ''}</dd></dl>
      </Card>
      <Card title={<><Icon name="alert" />Care gaps &amp; alerts</>} right={<Link to="/care-gaps">All alerts</Link>}>
        {p.careGaps.length ? <div className="list">{p.careGaps.map((g) => <div key={g.id}><span className="grow"><b>{g.category}</b><br /><span className="sm mut">{g.reason}</span></span><PriorityBadge p={g.priority} /><StatusBadge s={g.status} /></div>)}</div>
          : <Empty title="No outstanding care gaps" hint="Detected by explainable rules." />}
      </Card>
      <Card title="Upcoming appointments">{up.length ? <div className="list">{up.map((a) => (
        <div key={a.id} className="cl" onClick={() => onAppt(a.id)}><span className="b nowrap" style={{ width: 48 }}>{a.apptTime}</span>
          <span className="grow"><span className="t b">{fmtDS(a.apptDate)}</span><br /><span className="sm mut">{a.type} · {docName(a.doctorId)}</span></span><StatusBadge s={a.status} /></div>))}</div>
        : <Empty title="No upcoming appointments" />}</Card>
      <Card title="Pending investigations">{tests.length ? <div className="list">{tests.map((t) => (
        <div key={t.id} className="cl" onClick={() => onTest(t.id)}><span className="grow"><span className="t b">{t.name}</span><br /><span className="sm mut">Ordered {fmtDate(t.orderedOn)}</span></span><StatusBadge s={t.status} /></div>))}</div>
        : <Empty title="No pending investigations" />}</Card>
      <Card title="Active referrals" right={<button className="btn sec s" onClick={onAddRef}><Icon name="plus" small /> Add</button>}>
        {refs.length ? <div className="list">{refs.map((r) => (
          <div key={r.id}><span className="grow"><b>{r.referredTo}</b><br /><span className="sm mut">{r.reason} · since {fmtDate(r.createdOn)}</span></span><StatusBadge s={r.status} />
            {r.status === 'Pending' ? <button className="btn sec s" onClick={() => setRef(r.id, 'Booked')}>Mark booked</button> : <button className="btn sec s" onClick={() => setRef(r.id, 'Completed')}>Mark completed</button>}</div>))}</div>
          : <Empty title="No active referrals" />}
      </Card>
      <Card title="Open tasks" right={<button className="btn sec s" onClick={onAddTask}><Icon name="plus" small /> Add</button>}>
        {tasks.length ? <div className="list">{tasks.map((k) => (
          <div key={k.id} className="cl" onClick={() => onTask(k)}><span className="grow"><span className="t b">{k.title}</span><br /><span className="sm mut">{k.assigneeName} · due {fmtDate(k.due)}</span></span><StatusBadge s={k.status} /></div>))}</div>
          : <Empty title="No open tasks" />}
      </Card>
      <Card title="Recent care activities" full>
        <div className="list">{p.activity.length ? p.activity.map((a, i) => (
          <div key={i}><span className="mut nowrap sm" style={{ width: 130 }}>{fmtDateTime(a.ts)}</span><span><b>{a.action}</b> <span className="mut">– {a.detail} ({a.userName})</span></span></div>))
          : <Empty title="No recorded activity yet" />}</div>
      </Card>
    </div>
  )
}

function History({ p, docName }: { p: PatientDetail; docName: (u: string | null) => string }) {
  const items = [...p.history.map((h) => ({ date: h.eventDate, type: h.type ?? '', title: h.title ?? '', detail: h.detail ?? '' })),
    ...p.consultations.map((c) => ({ date: c.consultDate, type: 'Consultation', title: `Consultation – ${docName(c.doctorId)}`,
      detail: `${c.notes ?? ''}${c.diagnosis ? ` Diagnosis: ${c.diagnosis}.` : ''}` }))].sort((a, b) => (b.date ?? '0000').localeCompare(a.date ?? '0000'))
  return (
    <div className="card"><h2>Medical history timeline</h2><p className="sub">Most recent first. Includes diagnoses, surgeries, hospital visits, consultations and treatments.</p>
      <div className="tl">{items.map((i, k) => <div key={k} className="ev"><div className="d">{i.date ? fmtDate(i.date) : 'Date not recorded'} · {i.type}</div><div className="ti">{i.title}</div><div className="sm mut">{i.detail}</div></div>)}</div></div>
  )
}

function Appts({ p, docName, onOpen, onBook }: { p: PatientDetail; docName: (u: string | null) => string; onOpen: (id: string) => void; onBook: () => void }) {
  const T = todayIso(), all = p.appointments
  const desc = (l: typeof all) => [...l].sort((a, b) => (b.apptDate + b.apptTime).localeCompare(a.apptDate + a.apptTime))
  const grp = (t: string, l: typeof all, empt: string) => (
    <div className="card mt2" key={t}><h2>{t} <span className="badge b-grey">{l.length}</span></h2>
      {l.length ? <Table head={['Date', 'Time', 'Doctor', 'Type', 'Status']}>{l.map((a) => (
        <tr key={a.id} className="click" onClick={() => onOpen(a.id)}><td>{fmtDS(a.apptDate)} {a.apptDate.slice(0, 4)}</td><td>{a.apptTime}</td><td>{docName(a.doctorId)}</td><td>{a.type}</td><td><StatusBadge s={a.status} /></td></tr>))}</Table>
        : <div className="sm mut">{empt}</div>}</div>
  )
  return (
    <>
      <div className="row sp"><h2>Appointments</h2><button className="btn" onClick={onBook}><Icon name="plus" small /> Book appointment</button></div>
      {grp('Upcoming', all.filter((a) => ['Scheduled', 'Confirmed'].includes(a.status) && a.apptDate >= T).sort((a, b) => (a.apptDate + a.apptTime).localeCompare(b.apptDate + b.apptTime)), 'None scheduled.')}
      {grp('Past (completed)', desc(all.filter((a) => a.status === 'Completed')), 'None.')}
      {grp('Missed', desc(all.filter((a) => a.status === 'Missed')), 'None.')}
      {grp('Cancelled', desc(all.filter((a) => a.status === 'Cancelled')), 'None.')}
    </>
  )
}

function Journey({ p, docName }: { p: PatientDetail; docName: (u: string | null) => string }) {
  const [asc, setAsc] = useState(true)
  const hist = usePriorityHistory(p.id).data ?? []
  type Ev = { date: string; ts: string; type: string; title: string; detail: string }
  const ev: Ev[] = []
  const add = (date: string | null, type: string, title: string, detail = '', tm = '09:00') => date && ev.push({ date: date.slice(0, 10), ts: `${date.slice(0, 10)}T${tm}`, type, title, detail })
  add(p.registeredOn, 'Registration', 'Registered with Bupa CareFlow', `Patient ID ${p.id} · ${p.department}`, '08:00')
  p.appointments.forEach((a) => { const d = docName(a.doctorId), tm = a.apptTime ?? '09:00'
    if (a.status === 'Completed') add(a.apptDate, 'Consultation', `${a.type} completed`, `With ${d}`, tm)
    else if (a.status === 'Missed') add(a.apptDate, 'Missed', 'Missed appointment', `With ${d} (${a.type})`, tm)
    else if (a.status === 'Cancelled') add(a.apptDate, 'Cancelled', 'Appointment cancelled', a.type ?? '', tm)
    else add(a.apptDate, 'Scheduled', `Appointment ${a.status.toLowerCase()}`, `${fmtDS(a.apptDate)} ${a.apptTime} with ${d}`, tm) })
  p.consultations.forEach((c) => { if (c.diagnosis) add(c.consultDate, 'Diagnosis', `Diagnosis recorded: ${c.diagnosis}`, `By ${docName(c.doctorId)}`, '10:00')
    if (c.plan) add(c.consultDate, 'Treatment', 'Treatment plan updated', c.plan, '10:05'); if (c.followUp) add(c.consultDate, 'Follow-up', `Follow-up planned for ${fmtDate(c.followUp)}`, '', '10:10') })
  p.referrals.forEach((r) => add(r.createdOn, 'Referral', `Referral to ${r.referredTo}`, `${r.reason} · ${r.status}`, '11:00'))
  p.tests.forEach((t) => { add(t.orderedOn, 'Diagnostic Test', `${t.name} ordered`, `By ${docName(t.orderedBy)}`, '12:00')
    if (t.resultOn) add(t.resultOn, 'Result', `${t.name} result available`, t.abnormal ? 'Values outside reference range' : '', '13:00')
    if (t.reviewedOn) add(t.reviewedOn, 'Result', `${t.name} reviewed`, t.reviewNote ?? '', '14:00') })
  p.tasks.filter((k) => ['followup', 'contact', 'referral', 'test', 'medication'].includes(k.kind ?? '')).forEach((k) => {
    add(k.created, 'Follow-up', `Task created: ${k.title}`, `Assigned to ${k.assigneeName}`, '15:00'); if (k.completedOn) add(k.completedOn, 'Follow-up', `Task completed: ${k.title}`, '', '16:00') })
  hist.forEach((h) => add(h.changedAt, 'Priority', h.previousPriority ? `Priority changed: ${PRIORITY_LABEL[h.previousPriority]} → ${PRIORITY_LABEL[h.newPriority]}` : `Initial priority: ${PRIORITY_LABEL[h.newPriority]}`,
    `${h.userName} (${ROLE_LABEL[h.userRole as 'doctor'] ?? h.userRole}): “${h.comment}”`, h.changedAt.slice(11, 16)))
  p.documents.forEach((d) => add(d.uploadedAt, 'Import', `Document imported: ${d.filename}`, `${d.docType ?? ''} · extracted via ${d.extractionMethod ?? '—'}`, d.uploadedAt.slice(11, 16)))
  ev.sort((a, b) => a.ts.localeCompare(b.ts))
  if (!asc) ev.reverse()
  return (
    <div className="card">
      <div className="row sp"><h2>Care journey</h2><label className="sm">Order <select style={{ width: 'auto' }} value={asc ? 'asc' : 'desc'} onChange={(e) => setAsc(e.target.value === 'asc')}>
        <option value="asc">Oldest first (chronological)</option><option value="desc">Newest first</option></select></label></div>
      <p className="sub">Assembled from appointments, consultations, referrals, tests, tasks and recorded outcomes – the same records used everywhere else.</p>
      <div className="tl">{ev.map((e, i) => <div key={i} className={`ev t-${e.type.split(' ')[0]}`}><div className="d">{fmtDate(e.date)} · {e.type}</div><div className="ti">{e.title}</div>{e.detail && <div className="sm mut">{e.detail}</div>}</div>)}</div>
    </div>
  )
}

function Consult({ p, docName, onTest, extra, onAddRef }: { p: PatientDetail; docName: (u: string | null) => string; onTest: (id: string) => void; extra: ReactNode; onAddRef: () => void }) {
  const recent = p.appointments.filter((a) => a.status === 'Completed').slice(0, 3)
  return (
    <div className="grid g23">
      <div>
        <div className="card"><h2><Icon name="stetho" />Consultation form</h2><ConsultationForm patientId={p.id} extra={extra} /></div>
        <div className="card mt"><h2>Referrals</h2><p className="sm mut">Refer the patient to another service; the coordinator tracks it until it is completed.</p>
          <div className="row"><button className="btn sec" onClick={onAddRef}>Add referral</button></div></div>
        <div className="card mt"><h2>Previous consultations</h2><div className="list">{p.consultations.map((c) => (
          <div key={c.id}><span className="nowrap sm mut" style={{ width: 90 }}>{fmtDate(c.consultDate)}</span><span><b>{docName(c.doctorId)}</b><br /><span className="sm">{c.notes}</span>
            {c.diagnosis && <><br /><span className="sm mut">Diagnosis: {c.diagnosis}</span></>}</span></div>))}</div></div>
      </div>
      <div>
        <div className="card"><h2>Patient summary</h2><dl className="kv" style={{ gridTemplateColumns: '110px 1fr' }}>
          <dt>Patient</dt><dd>{p.firstName} {p.lastName} · {age(p.dob)} · {p.gender}</dd><dt>Condition</dt><dd>{p.primaryCondition}</dd>
          <dt>History</dt><dd>{p.diagnoses.join('; ') || 'None'}; {p.previousSurgeries}</dd><dt>Allergies</dt><dd>{p.allergies.join('; ') || 'None recorded'}</dd>
          <dt>Medication</dt><dd>{p.medications.join('; ') || 'None'}</dd><dt>Plan</dt><dd>{p.carePlan?.planText ?? '—'}</dd></dl></div>
        <div className="card mt"><h2>Recent appointments</h2><div className="list">{recent.length ? recent.map((a) => <div key={a.id}><span className="grow">{fmtDate(a.apptDate)} · {a.type}</span><StatusBadge s={a.status} /></div>) : <div className="sm mut">None completed.</div>}</div>
          <h2 className="mt">Recent diagnostic results</h2><div className="list">{p.tests.slice(0, 4).map((t) => (
            <div key={t.id} className="cl" onClick={() => onTest(t.id)}><span className="grow t">{t.name}</span><StatusBadge s={t.status} />{t.abnormal && t.status === 'Result Available' && <span className="badge b-high">Flagged</span>}</div>))}
            {!p.tests.length && <div className="sm mut">None.</div>}</div></div>
      </div>
    </div>
  )
}

function PriorityCard({ p, onChange }: { p: PatientDetail; onChange: () => void }) {
  const log = [...(usePriorityHistory(p.id).data ?? [])].reverse()
  return (
    <div className="card mt">
      <div className="row sp"><h2><Icon name="shield" />Priority &amp; history</h2>{p.canChangePriority && <button className="btn s" onClick={onChange}>Change priority</button>}</div>
      <div className="row" style={{ marginBottom: 8 }}><span className="mut">Current priority</span><PriorityBadge p={p.priority} />
        {p.suggestedPriority && p.suggestedPriority !== p.priority && <span className="sm mut">Care-gap suggestion (advisory, not applied): <PriorityBadge p={p.suggestedPriority} /></span>}</div>
      {log.length ? <Table head={['Date & time', 'Change', 'Comment', 'By']}>{log.map((h) => (
        <tr key={h.id}><td>{fmtDateTime(h.changedAt)}</td><td>{h.previousPriority ? <><PriorityBadge p={h.previousPriority} /> → </> : <span className="mut">Initial </span>}<PriorityBadge p={h.newPriority} /></td>
          <td>{h.comment}</td><td>{h.userName}<br /><span className="sm mut">{ROLE_LABEL[h.userRole as 'doctor'] ?? h.userRole}</span></td></tr>))}</Table>
        : <p className="mut">No priority history recorded.</p>}
      <p className="sm mut mt2">History entries are append-only: they cannot be edited or deleted from the application.</p>
    </div>
  )
}

function DocsCard({ p }: { p: PatientDetail }) {
  const toast = useToast()
  if (!p.documents.length) return null
  return (
    <div className="card mt"><h2><Icon name="task" />Imported documents</h2><div className="list">{p.documents.map((d) => (
      <div key={d.id} className="cl"><span className="grow"><b>{d.filename}</b><br /><span className="sm mut">{d.docType ?? d.fileType} · imported {fmtDateTime(d.uploadedAt)} · extracted via {d.extractionMethod ?? '—'} · batch {d.batchId}</span></span>
        <button className="btn sec s" onClick={() => downloadFile(`/api/documents/${d.id}/file`, d.filename).catch((e) => toast(e.message, true))}>Open original</button></div>))}</div></div>
  )
}

/** select → mandatory comment → review old/new → confirm (V2 priority modal). The API enforces the same rules. */
function ChangePriorityDialog({ p, onClose }: { p: PatientDetail; onClose: () => void }) {
  const toast = useToast()
  const me = useMe().data
  const change = useChangePriority(p.id)
  const [step, setStep] = useState<'form' | 'confirm'>('form')
  const [next, setNext] = useState<Priority | ''>('')
  const [comment, setComment] = useState('')
  const [err, setErr] = useState<Record<string, string>>({})
  const review = () => {
    const e: Record<string, string> = {}
    if (!next) e.newP = 'Select the new priority'
    if (comment.trim().length < 5) e.comment = 'A comment explaining the reason is mandatory (at least 5 characters)'
    setErr(e)
    if (!Object.keys(e).length) setStep('confirm')
  }
  const confirm = () => change.mutate({ newPriority: next as Priority, comment: comment.trim() }, {
    onSuccess: (r) => { toast(`Priority changed: ${PRIORITY_LABEL[r.previousPriority ?? 'med']} → ${PRIORITY_LABEL[r.newPriority]} for ${p.firstName} ${p.lastName}`); onClose() } })
  return (
    <Modal title={`Change priority – ${p.firstName} ${p.lastName}`} onClose={onClose} footer={false}>
      {step === 'confirm' ? <>
        <p className="sub">Please confirm this change. It is recorded permanently in the priority history and cannot be edited afterwards.</p>
        <div className="card" style={{ background: 'var(--lb)', borderColor: '#c9dff3' }}>
          <div className="row" style={{ gap: 14, fontSize: 16 }}><span className="mut">Current</span><PriorityBadge p={p.priority} /><span style={{ fontSize: 20 }}>→</span><span className="mut">New</span><PriorityBadge p={next as Priority} /></div>
          <dl className="kv mt"><dt>Patient</dt><dd>{p.firstName} {p.lastName} <span className="mut">{p.id}</span></dd><dt>Reason</dt><dd>“{comment.trim()}”</dd>
            <dt>Changed by</dt><dd>{me?.name} ({me ? ROLE_LABEL[me.role] : ''})</dd></dl>
        </div>
        <ErrorBanner error={change.error} />
        <div className="row mt" style={{ justifyContent: 'flex-end' }}><button className="btn sec" onClick={() => setStep('form')}>Back</button>
          <button className="btn" onClick={confirm} disabled={change.isPending}>{change.isPending ? 'Saving…' : 'Confirm priority change'}</button></div>
      </> : <>
        <p className="sub">Current priority: <PriorityBadge p={p.priority} />. Priority is set by people only – the care-gap rules and the AI assistant can suggest, but never change it.</p>
        {p.suggestedPriority && p.suggestedPriority !== p.priority && <div className="banner warn" style={{ marginBottom: 10 }}>Care-gap rules currently suggest <b>{PRIORITY_LABEL[p.suggestedPriority]}</b> priority (advisory only).</div>}
        <div className="fg"><Field label="New priority" req full error={err.newP}><select value={next} onChange={(e) => setNext(e.target.value as Priority)}>
          <option value="">Select new priority…</option>{(['high', 'med', 'low'] as Priority[]).filter((x) => x !== p.priority).map((x) => <option key={x} value={x}>{PRIORITY_LABEL[x]}</option>)}</select></Field></div>
        {next && <div className="row" style={{ margin: '2px 0 10px', fontSize: 15 }}><PriorityBadge p={p.priority} /><span>→</span><PriorityBadge p={next} /></div>}
        <div className="fg"><Field label="Reason for the change (mandatory)" req full error={err.comment} hint="Recorded in the audit trail with your name, role and the time.">
          <textarea rows={3} placeholder="e.g. Missed review and abnormal result pending – escalating" value={comment} onChange={(e) => setComment(e.target.value)} /></Field></div>
        <div className="row mt" style={{ justifyContent: 'flex-end' }}><button className="btn sec" onClick={onClose}>Cancel</button><button className="btn" onClick={review}>Review change</button></div>
      </>}
    </Modal>
  )
}
