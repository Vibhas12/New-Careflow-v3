/** Dashboards – same layout as V2 dashCoord / dashDoctor / dashAdmin; data from GET /api/dashboard (scoped on the server). */
import { useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import type { Alert, AppointmentItem, PatientListItem, Task, TestItem, User } from '../api/types'
import { useDashboard, useNotifications } from '../api/workflows'
import { AppointmentDetailDialog, TaskDetailDialog, TestDetailDialog } from '../components/details'
import { BookAppointmentDialog, CallDialog, ReminderDialog } from '../components/dialogs'
import { Icon, type IconName } from '../components/Icon'
import { Empty, ErrorBanner, Kpi, Loading, PageHead, PriorityBadge, StatusBadge, Table } from '../components/ui'
import { todayIso } from '../lib/dates'
import { DOW, ROLE_LABEL, age, fmtDate, fmtDateTime, fmtDS } from '../lib/format'

type Open = { kind: 'appt'; id: string } | { kind: 'test'; t: TestItem } | { kind: 'task'; t: Task } | { kind: 'book'; pid?: string; doctor?: string | null }
  | { kind: 'call'; p: PatientListItem } | { kind: 'remind'; p: PatientListItem } | null

function useDialogs() {
  const [open, setOpen] = useState<Open>(null)
  const close = () => setOpen(null)
  const el = !open ? null
    : open.kind === 'appt' ? <AppointmentDetailDialog id={open.id} onClose={close} />
    : open.kind === 'test' ? <TestDetailDialog test={open.t} onClose={close} />
    : open.kind === 'task' ? <TaskDetailDialog task={open.t} onClose={close} />
    : open.kind === 'book' ? <BookAppointmentDialog patientId={open.pid} defaultDoctor={open.doctor} onClose={close} />
    : open.kind === 'call' ? <CallDialog patientId={open.p.id} name={`${open.p.firstName} ${open.p.lastName}`} mobile={open.p.mobile} onClose={close} />
    : <ReminderDialog patientId={open.p.id} name={`${open.p.firstName} ${open.p.lastName}`} onClose={close}
        appt={open.p.nextAppt ? { id: open.p.nextAppt.id, date: open.p.nextAppt.date, time: open.p.nextAppt.time, doctorName: open.p.doctorName } : null} />
  return { setOpen, el }
}

const H2 = ({ icon, children, right }: { icon?: IconName; children: ReactNode; right?: ReactNode }) =>
  <h2>{icon && <Icon name={icon} />}{children}{right && <span className="r sm">{right}</span>}</h2>

function ApptRow({ a, onOpen }: { a: AppointmentItem; onOpen: () => void }) {
  return <div className="cl" onClick={onOpen}><span className="b nowrap" style={{ width: 48 }}>{a.apptTime}</span>
    <span className="grow"><span className="t b">{a.patientName} ({a.patientId})</span><br /><span className="sm mut">{a.type} · {a.doctorName}</span></span><StatusBadge s={a.status} /></div>
}

function Notifications({ n }: { n: number }) {
  const q = useNotifications()
  const nav = useNavigate()
  const items = (q.data?.items ?? []).slice(0, n)
  return <div className="list">{items.length ? items.map((x) => (
    <div key={x.id} className="cl" onClick={() => nav(x.route?.startsWith('patient') ? `/patients/${x.patientId}` : `/${x.route ?? ''}`)}>
      <span className="grow"><span className="t b">{x.title}</span> <span className="sm mut">{fmtDateTime(x.ts)}</span><br /><span className="sm mut">{x.text}</span></span>
      {!x.isRead && <span className="badge b-blue">New</span>}</div>)) : <Empty title="No notifications" />}</div>
}

export function DashboardPage({ user }: { user: User }) {
  const q = useDashboard()
  if (q.isLoading) return <Loading />
  if (q.error) return <ErrorBanner error={q.error} />
  return user.role === 'admin' ? <AdminDash d={q.data} /> : user.role === 'doctor' ? <DoctorDash d={q.data} user={user} /> : <CoordDash d={q.data} />
}

// ---------------------------------------------------------------- care coordinator
function PatientCard({ p, onAct }: { p: PatientListItem; onAct: (o: Open) => void }) {
  const nav = useNavigate()
  const reason = p.attention ?? 'No outstanding coordination activities'
  return (
    <div className="pc">
      <div className="row sp"><span className="nm" onClick={() => nav(`/patients/${p.id}`)}>{p.firstName} {p.lastName}</span><PriorityBadge p={p.priority} /></div>
      <div className="sm mut">{p.id} · {age(p.dob)} yrs</div>
      <dl><dt>Condition</dt><dd>{p.primaryCondition}</dd><dt>Doctor</dt><dd>{p.doctorName ?? '—'}</dd><dt>Last visit</dt><dd>{fmtDate(p.lastVisit)}</dd>
        <dt>Next appt</dt><dd>{p.nextAppt ? `${fmtDS(p.nextAppt.date)} ${p.nextAppt.time}` : 'None booked'}</dd><dt>Contact</dt><dd>{p.mobile ?? '—'}</dd></dl>
      <div className="reason"><b>{p.priority === 'low' ? 'Status' : 'Reason for attention'}:</b> {reason}</div>
      <div className="row">
        <button className="btn s" onClick={() => nav(`/patients/${p.id}`)}>View Profile</button>
        <button className="btn sec s" onClick={() => onAct({ kind: 'call', p })}><Icon name="phone" small /> Call Patient</button>
        <button className="btn sec s" onClick={() => onAct({ kind: 'remind', p })}><Icon name="send" small /> Send Reminder</button>
        <button className="btn sec s" onClick={() => onAct({ kind: 'book', pid: p.id, doctor: p.doctorId })}>Schedule Follow-up</button>
      </div>
    </div>
  )
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function CoordDash({ d }: { d: any }) {
  const nav = useNavigate()
  const { setOpen, el } = useDialogs()
  const pats: PatientListItem[] = d.patients
  const bucket = { high: pats.filter((p) => p.priority === 'high'), med: pats.filter((p) => p.priority === 'med'), low: pats.filter((p) => p.priority === 'low') }
  const T = todayIso()
  const col = (k: 'high' | 'med' | 'low', title: string, icon: IconName) => (
    <div className={`col ${k}`}>
      <h3><Icon name={icon} />{title}<span className="cnt">{bucket[k].length}</span></h3>
      {bucket[k].length ? <>
        {bucket[k].slice(0, k === 'low' ? 3 : 50).map((p) => <PatientCard key={p.id} p={p} onAct={setOpen} />)}
        {k === 'low' && bucket.low.length > 3 && <button className="btn sec s" onClick={() => nav('/patients?priority=low&mine=1')}>View all {bucket.low.length} low-priority patients</button>}
      </> : <Empty title="No patients in this category" />}
    </div>
  )
  return (
    <>
      <PageHead title="Today's Patient Overview" sub="Your daily overview of patients who need attention."
        actions={<><button className="btn" onClick={() => nav('/import')}><Icon name="upload" small /> Import patient data</button>
          <button className="btn sec" onClick={() => setOpen({ kind: 'book' })}><Icon name="cal" small /> Book appointment</button></>} />
      <div className="grid g5">
        <Kpi label="Total Patients Assigned" value={d.kpis.assigned} onClick={() => nav('/patients?mine=1')} />
        <Kpi label="Requiring Immediate Attention" value={d.kpis.high} tone="red" onClick={() => nav('/care-gaps')} />
        <Kpi label="Upcoming Appointments (7 days)" value={d.kpis.upcoming7} onClick={() => nav('/appointments')} />
        <Kpi label="Pending Diagnostic Tests" value={d.kpis.pendingTests} tone="amb" onClick={() => nav('/tests')} />
        <Kpi label="Pending Follow-ups" value={d.kpis.openTasks} onClick={() => nav('/tasks')} />
      </div>
      <h2 className="mt" style={{ fontSize: 18 }}>Patient Attention Board</h2>
      <p className="sub">Priority is set by care coordinators and doctors (with a recorded reason); care-gap rules only suggest. See <Link to="/care-gaps">Care Gaps &amp; Alerts</Link> for the evidence behind each flag.</p>
      <div className="board">{col('high', 'High priority', 'alert')}{col('med', 'Medium priority', 'clock')}{col('low', 'Low priority', 'check')}</div>
      <div className="grid g2 mt">
        <div className="card"><H2 icon="cal" right={<Link to="/appointments">Calendar</Link>}> Today's Appointments</H2>
          <div className="list">{d.todayAppointments.length ? d.todayAppointments.map((a: AppointmentItem) => <ApptRow key={a.id} a={a} onOpen={() => setOpen({ kind: 'appt', id: a.id })} />) : <Empty title="No appointments today" />}</div></div>
        <div className="card"><H2 icon="flask" right={<Link to="/tests">All tests</Link>}>Pending Diagnostic Results</H2>
          <div className="list">{d.pendingTests.length ? d.pendingTests.map((t: TestItem) => (
            <div key={t.id} className="cl" onClick={() => setOpen({ kind: 'test', t })}><span className="grow"><span className="t b">{t.name}</span> – {t.patientName} ({t.patientId})<br /><span className="sm mut">Ordered {fmtDate(t.orderedOn)}</span></span><StatusBadge s={t.status} /></div>
          )) : <Empty title="Nothing pending" />}</div></div>
        <div className="card"><H2 icon="user">Recently Updated Patients</H2>
          <div className="list">{d.recentPatients.map((r: { patientId: string; patientName: string; action: string; ts: string }) => (
            <div key={r.patientId} className="cl" onClick={() => nav(`/patients/${r.patientId}`)}><span className="grow"><span className="t b">{r.patientName} ({r.patientId})</span><br /><span className="sm mut">{r.action} · {fmtDateTime(r.ts)}</span></span></div>
          ))}</div></div>
        <div className="card"><H2 icon="task" right={<Link to="/tasks">Task board</Link>}>Tasks Due Today</H2>
          <div className="list">{d.tasksDue.length ? d.tasksDue.map((k: Task) => (
            <div key={k.id} className="cl" onClick={() => setOpen({ kind: 'task', t: k })}><span className="grow"><span className="t b">{k.title}</span><br /><span className="sm mut">{k.patientId ? `${k.patientName} (${k.patientId}) · ` : ''}due {fmtDate(k.due)}</span></span>
              {k.due && k.due < T ? <span className="badge b-Overdue">Overdue</span> : <PriorityBadge p={k.priority} />}</div>
          )) : <Empty title="No tasks due today" />}</div></div>
        <div className="card" style={{ gridColumn: '1/-1' }}><H2 icon="bell">Latest Notifications</H2><Notifications n={5} /></div>
      </div>
      {el}
    </>
  )
}

// ---------------------------------------------------------------- doctor
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function DoctorDash({ d, user }: { d: any; user: User }) {
  const nav = useNavigate()
  const { setOpen, el } = useDialogs()
  const [f, setF] = useState({ name: '', illness: '', priority: '', dept: '', fu: '' })
  const rank = { high: 0, med: 1, low: 2 }
  const rows = (d.patients as PatientListItem[]).filter((p) => (!f.name || `${p.firstName} ${p.lastName}${p.id}`.toLowerCase().includes(f.name.toLowerCase()))
    && (!f.illness || (p.primaryCondition ?? '').toLowerCase().includes(f.illness.toLowerCase())) && (!f.priority || p.priority === f.priority)
    && (!f.dept || p.department === f.dept) && (!f.fu || p.followUpStatus === f.fu))
    .sort((a, b) => rank[a.priority] - rank[b.priority] || `${a.firstName} ${a.lastName}`.localeCompare(`${b.firstName} ${b.lastName}`))
  const gi = (x: Alert) => <div key={x.id} className="cl" onClick={() => nav(`/patients/${x.patientId}`)}><span className="grow"><span className="t b">{x.patientName} ({x.patientId})</span><br /><span className="sm mut">{x.reason}</span></span><PriorityBadge p={x.priority} /></div>
  const block = (t: string, items: ReactNode[]) => <div><h3 style={{ marginBottom: 6 }}>{t} <span className="badge b-grey">{items.length}</span></h3>{items.length ? <div className="list">{items}</div> : <div className="sm mut">None right now.</div>}</div>
  return (
    <>
      <PageHead title="Doctor Dashboard" sub={`Welcome, ${user.name}. Your assigned patients and items that need clinical review.`} />
      <div className="grid g4">
        <Kpi label="Assigned Patients" value={d.kpis.assigned} />
        <Kpi label="Appointments Today" value={d.kpis.appointmentsToday} onClick={() => nav('/appointments')} />
        <Kpi label="Pending Reviews" value={d.kpis.pendingReviews} tone="red" onClick={() => nav('/tests')} />
        <Kpi label="Follow-ups Due" value={d.kpis.followUpsDue} tone="amb" onClick={() => nav('/care-gaps')} />
      </div>
      <div className="card mt"><h2><Icon name="stetho" />Patients Requiring Doctor Review</h2>
        <div className="grid g3">
          {block('Diagnostic results awaiting review', d.review.results.map(gi))}
          {block('Abnormal results flagged for clinical review', d.review.abnormal.map(gi))}
          {block('Overdue consultations', d.review.overdue.map(gi))}
          {block('Pending treatment-plan updates', d.review.plan.map((p: { patientId: string; patientName: string; reason: string }) =>
            <div key={p.patientId} className="cl" onClick={() => nav(`/patients/${p.patientId}?tab=consult`)}><span className="grow"><span className="t b">{p.patientName}</span><br /><span className="sm mut">{p.reason}</span></span></div>))}
          {block('Outstanding referrals', d.review.referrals.map(gi))}
        </div>
      </div>
      <div className="grid g32 mt">
        <div className="card"><h2>My patients</h2>
          <div className="filters" style={{ marginTop: 0 }}>
            <label>Patient name<input type="text" placeholder="Search…" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
            <label>Illness<input type="text" placeholder="e.g. diabetes" value={f.illness} onChange={(e) => setF({ ...f, illness: e.target.value })} /></label>
            <label>Priority<select value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })}><option value="">All</option><option value="high">High</option><option value="med">Medium</option><option value="low">Low</option></select></label>
            <label>Department<select value={f.dept} onChange={(e) => setF({ ...f, dept: e.target.value })}><option value="">All</option>{user.departments.map((x) => <option key={x}>{x}</option>)}</select></label>
            <label>Follow-up status<select value={f.fu} onChange={(e) => setF({ ...f, fu: e.target.value })}><option value="">All</option>{['Follow-up overdue', 'Follow-up scheduled', 'No follow-up scheduled'].map((x) => <option key={x}>{x}</option>)}</select></label>
          </div>
          <Table head={['Patient', 'Condition', 'Department', 'Priority', 'Next appointment', 'Follow-up']}>{rows.map((p) => (
            <tr key={p.id} className="click" onClick={() => nav(`/patients/${p.id}`)}><td><b>{p.firstName} {p.lastName}</b><br /><span className="sm mut">{p.id}</span></td>
              <td>{p.primaryCondition}</td><td>{p.department}</td><td><PriorityBadge p={p.priority} /></td>
              <td>{p.nextAppt ? `${fmtDS(p.nextAppt.date)} ${p.nextAppt.time}` : '—'}</td><td><StatusBadge s={p.followUpStatus ?? '—'} /></td></tr>))}</Table>
          {!rows.length && <Empty title="No patients match the filters" />}
        </div>
        <div className="card"><h2><Icon name="cal" />Today's schedule</h2>
          <div className="list">{d.todayAppointments.length ? d.todayAppointments.map((a: AppointmentItem) => <ApptRow key={a.id} a={a} onOpen={() => setOpen({ kind: 'appt', id: a.id })} />) : <Empty title="No appointments today" />}</div>
          <h2 className="mt"><Icon name="bell" />Latest notifications</h2><Notifications n={4} />
        </div>
      </div>
      {el}
    </>
  )
}

// ---------------------------------------------------------------- administrator
function BarChart({ labels, values, name }: { labels: string[]; values: number[]; name: string }) {
  const W = 640, H = 190, L = 38, B = 26, Tp = 10, R = 26, n = labels.length
  const max = Math.max(1, ...values), step = Math.pow(10, Math.floor(Math.log10(max))), top = Math.ceil(max / step) * step || 1
  const iw = W - L - R, ih = H - B - Tp, gw = iw / n, bw = Math.min(34, gw * 0.7)
  return (
    <div className="chartbox"><svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={name}>
      {[0, 1, 2, 3, 4].map((i) => { const y = Tp + ih - (ih * i) / 4; return <g key={i}><line x1={L} x2={W - R} y1={y} y2={y} stroke="#e3eaf2" /><text x={L - 6} y={y + 4} textAnchor="end" fontSize="10.5" fill="#5b6b7c">{Math.round((top * i) / 4 * 10) / 10}</text></g> })}
      {labels.map((lb, i) => { const cx = L + gw * i + gw / 2, h = (ih * values[i]) / top; return <g key={i}>
        <text x={cx} y={H - 8} textAnchor="middle" fontSize="10.5" fill="#5b6b7c">{lb}</text>
        <rect x={cx - bw / 2} y={Tp + ih - h} width={bw} height={Math.max(h, values[i] ? 1 : 0)} rx="3" fill="var(--s1)"><title>{`${lb} · ${name}: ${values[i]}`}</title></rect></g> })}
    </svg></div>
  )
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function AdminDash({ d }: { d: any }) {
  const nav = useNavigate()
  const mx = Math.max(1, ...d.gapsByCategory.map((c: { open: number }) => c.open))
  return (
    <>
      <PageHead title="Operations Dashboard" sub="Aggregated operational view. Patients appear by ID only – clinical detail is restricted for your role."
        actions={<button className="btn sec" disabled title="Executive Overview is not available in this version">Executive overview</button>} />
      <div className="grid g5">
        <Kpi label="Active patients" value={d.kpis.activePatients} />
        <Kpi label="Appointments today" value={d.kpis.appointmentsToday} onClick={() => nav('/appointments')} />
        <Kpi label="Open high-priority care gaps" value={d.kpis.highGaps} tone="red" onClick={() => nav('/care-gaps')} />
        <Kpi label="Open tasks" value={d.kpis.openTasks} onClick={() => nav('/tasks')} />
        <Kpi label="Overdue tasks" value={d.kpis.overdueTasks} tone="amb" onClick={() => nav('/tasks')} />
      </div>
      <div className="grid g2 mt">
        <div className="card"><h2>Appointments – next 7 days</h2>
          <BarChart name="Booked" labels={d.next7.map((x: { date: string }) => DOW[new Date(x.date + 'T00:00:00').getDay()])} values={d.next7.map((x: { booked: number }) => x.booked)} /></div>
        <div className="card"><h2>Open care gaps by category</h2>
          {d.gapsByCategory.map((c: { rule: string; category: string; open: number }) => (
            <div key={c.rule} style={{ margin: '9px 0' }}><div className="row sp sm"><span>{c.category} ({c.open})</span><span className="b" /></div>
              <div className="bar"><i style={{ width: `${Math.min(100, Math.round((c.open * 100) / mx))}%`, background: 'var(--blue)' }} /></div></div>))}
        </div>
      </div>
      <div className="card mt"><h2><Icon name="users" />Team activity</h2>
        <Table head={['Team member', 'Role', 'Open tasks', 'Overdue', 'Completed (30 days)', 'On-time completion']}>
          {d.team.map((x: { name: string; role: 'coordinator' | 'doctor'; open: number; overdue: number; completed30: number; onTime: number | null }) => (
            <tr key={x.name}><td><b>{x.name}</b></td><td>{ROLE_LABEL[x.role]}</td><td>{x.open}</td><td>{x.overdue}</td><td>{x.completed30}</td><td>{x.onTime == null ? '—' : `${x.onTime}%`}</td></tr>))}
        </Table>
        <p className="sm mut mt2">Attendance (last 30 days): <b>{d.attendance.rate == null ? '—' : `${d.attendance.rate}%`}</b> of {d.attendance.n} appointments with a recorded attendance outcome.</p>
      </div>
    </>
  )
}
