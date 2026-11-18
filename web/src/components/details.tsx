/** Detail dialogs opened by clicking an appointment, test or task – same content as V2 apptDetail / testDetail / taskDetail. */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMe, useUsers } from '../api/hooks'
import type { Task, TestItem } from '../api/types'
import { useAppointment, useApptAction, useTestAction, useTests, useUpdateTask } from '../api/workflows'
import { todayIso } from '../lib/dates'
import { fmtDate, fmtDateTime } from '../lib/format'
import { CancelAppointmentDialog, ReassignDialog, ReminderDialog, RescheduleDialog, ReviewResultDialog, ScheduleTestDialog, SimulateResultDialog, TaskDialog } from './dialogs'
import { Icon } from './Icon'
import { useToast } from './Toast'
import { Banner, Loading, Modal, PriorityBadge, Sim, StatusBadge, Table } from './ui'

const Steps = ({ steps, done }: { steps: string[]; done: boolean[] }) => (
  <div className="row sm mt2">{steps.map((s, i) => <span key={s} className="row" style={{ gap: 6 }}>
    <span className={'badge ' + (done[i] ? 'b-low' : 'b-grey')}>{done[i] ? '✓ ' : ''}{s}</span>{i < steps.length - 1 && <span className="mut">→</span>}</span>)}</div>
)

export function AppointmentDetailDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const me = useMe().data
  const toast = useToast()
  const q = useAppointment(id)
  const act = useApptAction()
  const [sub, setSub] = useState<'reschedule' | 'cancel' | 'remind' | null>(null)
  const a = q.data
  if (!a) return <Modal title={`Appointment ${id}`} onClose={onClose} footer={false}><Loading /></Modal>
  const admin = me?.role === 'admin'
  const active = ['Scheduled', 'Confirmed'].includes(a.status)
  const run = (action: 'confirm' | 'complete' | 'miss', msg: string) => act.mutate({ id: a.id, action }, { onSuccess: () => { toast(msg); onClose() }, onError: (e) => toast(e.message, true) })
  if (sub === 'reschedule') return <RescheduleDialog appt={a} onClose={() => setSub(null)} />
  if (sub === 'cancel') return <CancelAppointmentDialog appt={a} onClose={onClose} />
  if (sub === 'remind') return <ReminderDialog patientId={a.patientId} name={a.patientName} appt={{ id: a.id, date: a.apptDate, time: a.apptTime, doctorName: a.doctorName }} onClose={() => setSub(null)} />
  return (
    <Modal title={`Appointment ${a.id}`} onClose={onClose} footer={false}>
      <div className="row sp"><div><b style={{ fontSize: 16 }}>{a.patientName}</b> <span className="mut">{a.patientId}</span></div><StatusBadge s={a.status} /></div>
      <dl className="kv mt2"><dt>Doctor</dt><dd>{a.doctorName}</dd><dt>Department</dt><dd>{a.dept}</dd><dt>When</dt><dd>{fmtDate(a.apptDate)} at {a.apptTime}</dd>
        <dt>Type</dt><dd>{a.type}</dd><dt>Notes</dt><dd>{a.notes || '—'}</dd></dl>
      <h3 className="mt">Workflow</h3>
      <Steps steps={['Booked', 'Reminder scheduled', 'Patient confirmed', 'Completed']} done={[true, a.reminders.length > 0, ['Confirmed', 'Completed'].includes(a.status), a.status === 'Completed']} />
      {a.reminders.length > 0 && !admin && <>
        <h3 className="mt">Reminders <Sim /></h3>
        <div className="list">{a.reminders.map((r) => <div key={r.id}><span className="grow">{r.label} · {r.channel}</span><StatusBadge s={r.status ?? 'Scheduled'} /></div>)}</div>
      </>}
      <div className="row mt" style={{ flexWrap: 'wrap', gap: 6 }}>
        {active && <>
          {a.status === 'Scheduled' && <button className="btn s" onClick={() => run('confirm', 'Appointment confirmed')}><Icon name="check" small /> Confirm</button>}
          <button className="btn sec s" onClick={() => setSub('reschedule')}>Reschedule</button>
          <button className="btn dng s" onClick={() => setSub('cancel')}>Cancel</button>
          {a.apptDate <= todayIso() && <><button className="btn sec s" onClick={() => run('complete', 'Appointment marked completed')}>Mark completed</button>
            <button className="btn dng s" onClick={() => run('miss', 'Marked missed – doctor notified, care-gap check re-run')}>Mark missed</button></>}
          {!admin && <button className="btn sec s" onClick={() => setSub('remind')}><Icon name="send" small /> Send reminder</button>}
        </>}
        {!admin && <Link className="btn ghost s" to={`/patients/${a.patientId}`} onClick={onClose}>View patient</Link>}
        <button className="btn ghost s" onClick={onClose}>Close</button>
      </div>
    </Modal>
  )
}

/** Looks the test up through the scoped tests list so it works from any page that only has an id. */
export function TestDetailById({ id, patientId, onClose }: { id: string; patientId?: string; onClose: () => void }) {
  const q = useTests('all', patientId)
  const t = q.data?.find((x) => x.id === id)
  if (!t) return <Modal title="Diagnostic test" onClose={onClose} footer={false}><Loading /></Modal>
  return <TestDetailDialog test={t} onClose={onClose} />
}

export function TestDetailDialog({ test, onClose }: { test: TestItem; onClose: () => void }) {
  const me = useMe().data
  const users = useUsers().data ?? []
  const toast = useToast()
  const [sub, setSub] = useState<'schedule' | 'result' | 'review' | 'remind' | null>(null)
  const act = useTestTransition(onClose, toast)
  const x = useTests('all', test.patientId).data?.find((t) => t.id === test.id) ?? test       // live copy after actions
  const steps = ['Ordered', 'Scheduled', 'Completed', 'Result Available', 'Reviewed'], ix = steps.indexOf(x.status)
  const name = (id: string | null) => users.find((u) => u.id === id)?.name ?? '—'
  const coord = me?.role === 'coordinator', doctor = me?.role === 'doctor'
  if (sub === 'schedule') return <ScheduleTestDialog test={x} onClose={() => setSub(null)} />
  if (sub === 'result') return <SimulateResultDialog test={x} onClose={() => setSub(null)} />
  if (sub === 'review') return <ReviewResultDialog test={x} onClose={() => setSub(null)} />
  if (sub === 'remind') return <ReminderDialog patientId={x.patientId} name={x.patientName} test={{ id: x.id, name: x.name, scheduledDate: x.scheduledDate }} type="Diagnostic test reminder" onClose={() => setSub(null)} />
  return (
    <Modal title={`${x.name} – ${x.patientName} (${x.patientId})`} size="lg" onClose={onClose} footer={false}>
      <Steps steps={steps} done={steps.map((_, i) => i <= ix)} />
      <dl className="kv mt"><dt>Patient</dt><dd><Link className="b" to={`/patients/${x.patientId}`} onClick={onClose}>{x.patientName}</Link> <span className="mut">{x.patientId}</span></dd>
        <dt>Ordering doctor</dt><dd>{x.orderedByName ?? name(x.orderedBy)}</dd><dt>Ordered</dt><dd>{fmtDate(x.orderedOn)} ({x.priority})</dd>
        <dt>Scheduled</dt><dd>{fmtDate(x.scheduledDate)}</dd><dt>Completed</dt><dd>{fmtDate(x.completedOn)}</dd>
        <dt>Result</dt><dd>{x.resultSummary ? fmtDate(x.resultOn) : 'Not yet available'}</dd></dl>
      {x.resultSummary && <>
        <h3 className="mt">Report <span className="sim">SYNTHETIC</span></h3>
        <div className="hl mt2">{x.resultSummary}</div>
        {x.values.length > 0 && <div className="mt2"><Table head={['Measure', 'Value', 'Reference', 'Flag']}>{x.values.map((v, i) => (
          <tr key={i}><td>{v.analyte}</td><td className="b">{v.value} {v.unit}</td><td>{v.refRange}</td>
            <td>{v.flag ? <span className="badge b-high">{v.flag === 'H' ? 'High' : 'Low'}</span> : <span className="badge b-low">In range</span>}</td></tr>))}</Table></div>}
        <p className="sm mut mt2">Range flags are arithmetic comparisons to the stated reference range, not a diagnosis.</p>
      </>}
      {x.reviewedOn && <div className="mt"><Banner icon="check"><b>Reviewed</b> on {fmtDate(x.reviewedOn)}{x.reviewNote ? `: ${x.reviewNote}` : ''}</Banner></div>}
      <div className="row mt" style={{ flexWrap: 'wrap', gap: 6 }}>
        {x.status === 'Ordered' && coord && <button className="btn s" onClick={() => setSub('schedule')}>Schedule test</button>}
        {x.status === 'Scheduled' && coord && <><button className="btn s" onClick={() => act(x.id, 'complete', 'Marked completed – ordering doctor notified')}>Patient completed test</button>
          <button className="btn sec s" onClick={() => setSub('remind')}><Icon name="send" small /> Send reminder</button></>}
        {x.status === 'Completed' && (coord || doctor) && <button className="btn s" onClick={() => setSub('result')}>Simulate result feed</button>}
        {x.status === 'Result Available' && doctor && <button className="btn s" onClick={() => setSub('review')}>Review &amp; sign off</button>}
        <button className="btn ghost s" onClick={onClose}>Close</button>
      </div>
    </Modal>
  )
}

function useTestTransition(onClose: () => void, toast: (m: string, e?: boolean) => void) {
  const a = useTestAction()
  return (id: string, action: 'complete', msg: string) => a.mutate({ id, action }, { onSuccess: () => { toast(msg); onClose() }, onError: (e) => toast(e.message, true) })
}

export function TaskDetailDialog({ task, onClose }: { task: Task; onClose: () => void }) {
  const me = useMe().data
  const toast = useToast()
  const upd = useUpdateTask()
  const [sub, setSub] = useState<'edit' | 'reassign' | null>(null)
  const k = task
  if (sub === 'edit') return <TaskDialog task={k} onClose={onClose} />
  if (sub === 'reassign') return <ReassignDialog task={k} onClose={onClose} />
  const set = (status: 'Completed' | 'In Progress', msg: string) => upd.mutate({ id: k.id, status }, { onSuccess: () => { toast(msg); onClose() }, onError: (e) => toast(e.message, true) })
  return (
    <Modal title={k.title} size="lg" onClose={onClose} footer={false}>
      <div className="row"><StatusBadge s={k.status} /><PriorityBadge p={k.priority} /><span className="mut">{k.id} · {k.source}</span></div>
      <dl className="kv mt2">
        <dt>Patient</dt><dd>{k.patientId ? <Link className="b" to={`/patients/${k.patientId}`} onClick={onClose}>{k.patientName}</Link> : '—'}</dd>
        <dt>Assigned to</dt><dd>{k.assigneeName}</dd><dt>Created</dt><dd>{fmtDate(k.created)}</dd>
        <dt>Due</dt><dd>{fmtDate(k.due)}{k.status !== 'Completed' && k.due && k.due < todayIso() && <> <span className="badge b-Overdue">Overdue</span></>}</dd>
        <dt>Description</dt><dd>{k.description || '—'}</dd>
      </dl>
      <h3 className="mt">Task history</h3>
      <div className="list">{[...k.events].reverse().map((h, i) => <div key={i}><span className="mut nowrap sm">{fmtDateTime(h.ts)}</span><span><b>{h.byName}</b> – {h.text}</span></div>)}</div>
      <div className="row mt" style={{ flexWrap: 'wrap', gap: 6 }}>
        {me && <>
          <button className="btn s" onClick={() => setSub('edit')}><Icon name="edit" small /> Edit</button>
          <button className="btn sec s" onClick={() => setSub('reassign')}>Reassign</button>
          {k.status !== 'Completed' ? <button className="btn grn s" onClick={() => set('Completed', 'Task marked complete')}><Icon name="check" small /> Mark complete</button>
            : <button className="btn sec s" onClick={() => set('In Progress', 'Task reopened')}>Reopen</button>}
        </>}
        <button className="btn ghost s" onClick={onClose}>Close</button>
      </div>
    </Modal>
  )
}
