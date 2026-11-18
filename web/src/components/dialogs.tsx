/** Workflow dialogs – same fields, wording and banners as the V2 modals (frontend/src/05-modals.js). The API re-validates everything. */
import { useState, type ReactNode } from 'react'
import { usePatients, useUsers } from '../api/hooks'
import type { AppointmentItem, Priority, Task, TaskStatus, TestItem } from '../api/types'
import {
  useApptAction, useAppointments, useBookAppointment, useCatalog, useCreateReferral, useCreateTask, useLogCall, useRecordConsultation, useRequestTest,
  useSendReminder, useSlots, useTestAction, useUpdateTask,
} from '../api/workflows'
import { addDays, todayIso } from '../lib/dates'
import { ROLE_LABEL, fmtDate } from '../lib/format'
import { useToast } from './Toast'
import { Banner, Modal } from './ui'

export function Field({ label, req, hint, children, full, error }: { label: string; req?: boolean; hint?: string; children: ReactNode; full?: boolean; error?: string }) {
  return (
    <div className={'field' + (full ? ' full' : '') + (error ? ' bad' : '')}>
      <label>{label}{req && <span className="req"> *</span>}</label>
      {children}
      {error ? <span className="err">{error}</span> : hint && <span className="hint">{hint}</span>}
    </div>
  )
}

const nowHHMM = () => { const d = new Date(); return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}` }

/** V2 patientOpts(): every patient the user may see, by name */
function usePatientOptions() {
  const r = usePatients({ pageSize: 100, sort: 'name' })
  return (r.data?.items ?? []).filter((p) => !p.discharged).map((p) => ({ id: p.id, label: `${p.firstName} ${p.lastName} (${p.id})`, doctorId: p.doctorId, coordId: p.coordId, name: `${p.firstName} ${p.lastName}` }))
}

// ---------------------------------------------------------------- appointments
export function BookAppointmentDialog({ patientId, defaultDoctor, date, time, onClose }: { patientId?: string; defaultDoctor?: string | null; date?: string; time?: string; onClose: () => void }) {
  const toast = useToast()
  const cat = useCatalog()
  const doctors = (useUsers().data ?? []).filter((u) => u.role === 'doctor')
  const patients = usePatientOptions()
  const book = useBookAppointment()
  const [f, setF] = useState({ patientId: patientId ?? '', doctorId: defaultDoctor ?? '', date: date ?? addDays(todayIso(), 7), time: time ?? '', type: 'Follow-up review', notes: '' })
  const [err, setErr] = useState<Record<string, string>>({})
  const slots = useSlots(f.doctorId, f.date)
  const day = useAppointments({ from: f.date, to: f.date, doctorId: f.doctorId || undefined })
  const free = (slots.data?.slots ?? []).filter((t) => f.date !== todayIso() || t > nowHHMM())
  const booked = (day.data?.items ?? []).filter((a) => ['Scheduled', 'Confirmed'].includes(a.status)).length
  const set = (k: keyof typeof f, v: string) => setF((o) => {
    const n = { ...o, [k]: v }
    if (k === 'patientId' && !o.doctorId) n.doctorId = patients.find((p) => p.id === v)?.doctorId ?? ''
    if (k === 'doctorId' || k === 'date') n.time = ''
    return n
  })
  const submit = () => {
    const e: Record<string, string> = {}
    if (!f.patientId) e.patientId = 'Patient is required'
    if (!f.doctorId) e.doctorId = 'Doctor is required'
    if (!f.date) e.date = 'Date is required'; else if (f.date < todayIso()) e.date = 'Date cannot be in the past'
    if (!f.time) e.time = 'Choose a time slot'
    setErr(e)
    if (Object.keys(e).length) return
    book.mutate(f, { onSuccess: (a) => { toast(`Appointment booked for ${fmtDate(a.apptDate)} at ${a.apptTime} – reminders scheduled (simulated)`); onClose() }, onError: (x) => setErr({ time: x.message }) })
  }
  return (
    <Modal title="Book appointment" onClose={onClose} submit="Book appointment" onSubmit={submit} busy={book.isPending}>
      <div className="fg">
        <Field label="Patient" req error={err.patientId}>
          <select value={f.patientId} disabled={!!patientId} onChange={(e) => set('patientId', e.target.value)}>
            <option value="">Select patient…</option>{patients.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </Field>
        <Field label="Doctor" req error={err.doctorId}>
          <select value={f.doctorId} onChange={(e) => set('doctorId', e.target.value)}>
            <option value="">Select doctor…</option>{doctors.map((d) => <option key={d.id} value={d.id}>{d.name} – {d.departments.join(', ')}</option>)}
          </select>
        </Field>
        <Field label="Date" req error={err.date} hint={f.doctorId && f.date ? `${booked} appointment(s) already booked that day` : undefined}>
          <input type="date" min={todayIso()} value={f.date} onChange={(e) => set('date', e.target.value)} />
        </Field>
        <Field label="Time" req error={err.time}>
          <select value={f.time} onChange={(e) => set('time', e.target.value)}>
            <option value="">{free.length ? 'Select a free slot…' : 'No free slots – choose another date'}</option>{free.map((s) => <option key={s}>{s}</option>)}
          </select>
        </Field>
        <Field label="Appointment type" req><select value={f.type} onChange={(e) => set('type', e.target.value)}>{cat.data?.appointmentTypes.map((t) => <option key={t}>{t}</option>)}</select></Field>
        <Field label="Notes (optional)"><input type="text" value={f.notes} onChange={(e) => set('notes', e.target.value)} /></Field>
      </div>
      <div className="mt"><Banner>Booking creates reminders per Settings → Reminder Configuration (7d / 3d / 1d / 2h). Reminders are <b>simulated</b>.</Banner></div>
    </Modal>
  )
}

export function RescheduleDialog({ appt, onClose }: { appt: AppointmentItem; onClose: () => void }) {
  const toast = useToast()
  const cat = useCatalog()
  const act = useApptAction()
  const [date, setDate] = useState(appt.apptDate >= todayIso() ? appt.apptDate : addDays(todayIso(), 1))
  const [time, setTime] = useState('')
  const [reason, setReason] = useState('')
  const [err, setErr] = useState('')
  const slots = useSlots(appt.doctorId ?? '', date, appt.id)
  const free = (slots.data?.slots ?? []).filter((t) => date !== todayIso() || t > nowHHMM())
  const submit = () => {
    if (!time) return setErr('Choose a time slot')
    act.mutate({ id: appt.id, action: 'reschedule', body: { date, time, reason } }, { onSuccess: () => { toast(`Appointment rescheduled to ${fmtDate(date)} ${time}`); onClose() }, onError: (e) => setErr(e.message) })
  }
  return (
    <Modal title="Reschedule appointment" onClose={onClose} submit="Reschedule" onSubmit={submit} busy={act.isPending}>
      <div className="fg">
        <Field label="Patient" req><select disabled><option>{appt.patientName} ({appt.patientId})</option></select></Field>
        <Field label="Doctor" req><select disabled><option>{appt.doctorName}</option></select></Field>
        <Field label="Date" req><input type="date" min={todayIso()} value={date} onChange={(e) => { setDate(e.target.value); setTime('') }} /></Field>
        <Field label="Time" req error={err}><select value={time} onChange={(e) => setTime(e.target.value)}>
          <option value="">{free.length ? 'Select a free slot…' : 'No free slots – choose another date'}</option>{free.map((s) => <option key={s}>{s}</option>)}</select></Field>
        <Field label="Appointment type" req><select disabled value={appt.type ?? ''}>{cat.data?.appointmentTypes.map((t) => <option key={t}>{t}</option>)}</select></Field>
        <Field label="Reason for rescheduling"><input type="text" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </div>
      <div className="mt"><Banner>Booking creates reminders per Settings → Reminder Configuration (7d / 3d / 1d / 2h). Reminders are <b>simulated</b>.</Banner></div>
    </Modal>
  )
}

export function CancelAppointmentDialog({ appt, onClose }: { appt: AppointmentItem; onClose: () => void }) {
  const toast = useToast()
  const act = useApptAction()
  const [reason, setReason] = useState('')
  const [err, setErr] = useState('')
  return (
    <Modal title="Cancel appointment" onClose={onClose} submit="Cancel appointment" danger busy={act.isPending} onSubmit={() => {
      if (!reason.trim()) return setErr('Reason is required')
      act.mutate({ id: appt.id, action: 'cancel', body: { reason } }, { onSuccess: () => { toast('Appointment cancelled'); onClose() }, onError: (e) => setErr(e.message) })
    }}>
      <p>This frees the slot and removes scheduled reminders.</p>
      <div className="fg"><Field label="Reason" req full error={err}><input type="text" value={reason} onChange={(e) => setReason(e.target.value)} /></Field></div>
    </Modal>
  )
}

// ---------------------------------------------------------------- calls & reminders (simulated)
export function CallDialog({ patientId, name, mobile, onClose }: { patientId: string; name: string; mobile: string | null; onClose: () => void }) {
  const toast = useToast()
  const log = useLogCall(patientId)
  const [f, setF] = useState({ outcome: 'Reached patient', notes: '' })
  return (
    <Modal title={`Call patient – ${name}`} onClose={onClose} submit="Log call outcome" busy={log.isPending}
      onSubmit={() => log.mutate(f, { onSuccess: () => { toast(`Call outcome logged for ${name}`); onClose() }, onError: (e) => toast(e.message, true) })}>
      <Banner warn icon="phone"><b>Prototype – no call is placed.</b> Dial <b>{mobile ?? 'the patient'}</b> using your telephony tool, then log what happened here.</Banner>
      <div className="fg mt">
        <Field label="Call outcome"><select value={f.outcome} onChange={(e) => setF({ ...f, outcome: e.target.value })}>{['Reached patient', 'No answer', 'Left voicemail', 'Wrong number / unreachable'].map((o) => <option key={o}>{o}</option>)}</select></Field>
        <Field label="Notes" full><textarea rows={3} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
      </div>
    </Modal>
  )
}

const REMINDER_TYPES = ['Appointment reminder', 'Diagnostic test reminder', 'Follow-up request', 'Medication reminder']
export function ReminderDialog({ patientId, name, appt, test, type, onClose }: {
  patientId: string; name: string; appt?: { id: string; date: string; time: string | null; doctorName: string | null } | null
  test?: { id: string; name: string; scheduledDate: string | null } | null; type?: string; onClose: () => void
}) {
  const toast = useToast()
  const send = useSendReminder(patientId)
  const tpl = (ty: string) => ty === 'Diagnostic test reminder' && test ? `Reminder: your ${test.name} is arranged for ${fmtDate(test.scheduledDate)}. Please attend as planned.`
    : ty === 'Follow-up request' ? 'Your clinician would like you to arrange a follow-up review. Please contact us to book a time.'
    : ty === 'Medication reminder' ? 'Reminder: please check your prescription supply and contact us if you need a review before it runs out.'
    : appt ? `Reminder: you have an appointment on ${fmtDate(appt.date)} at ${appt.time} with ${appt.doctorName}. Please reply YES to confirm.`
    : 'Reminder from your care team: please contact us regarding your upcoming care.'
  const ty0 = type ?? (test ? 'Diagnostic test reminder' : 'Appointment reminder')
  const [f, setF] = useState({ type: ty0, channel: 'SMS', message: tpl(ty0) })
  const [err, setErr] = useState('')
  return (
    <Modal title={`Send reminder – ${name}`} onClose={onClose} submit="Send reminder (simulated)" busy={send.isPending} onSubmit={() => {
      if (!f.message.trim()) return setErr('Message is required')
      send.mutate({ ...f, appointmentId: appt?.id, testId: test?.id }, {
        onSuccess: (r) => { toast(`Reminder recorded for ${name} (simulated – ${r.status.toLowerCase()})`, r.status === 'Failed'); onClose() }, onError: (e) => setErr(e.message) })
    }}>
      <Banner warn><b>Simulated.</b> This prototype records the reminder and simulates delivery. No real SMS, email or app notification is sent.</Banner>
      <div className="fg mt">
        <Field label="Reminder type"><select value={f.type} onChange={(e) => setF({ ...f, type: e.target.value, message: tpl(e.target.value) })}>{REMINDER_TYPES.map((t) => <option key={t}>{t}</option>)}</select></Field>
        <Field label="Channel"><select value={f.channel} onChange={(e) => setF({ ...f, channel: e.target.value })}>{['SMS', 'Email', 'App'].map((c) => <option key={c}>{c}</option>)}</select></Field>
        <Field label="Message" req full error={err}><textarea rows={3} value={f.message} onChange={(e) => setF({ ...f, message: e.target.value })} /></Field>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------- diagnostic tests
export function RequestTestDialog({ patientId, onClose }: { patientId?: string; onClose: () => void }) {
  const toast = useToast()
  const cat = useCatalog()
  const req = useRequestTest()
  const patients = usePatientOptions()
  const [f, setF] = useState({ patientId: patientId ?? '', name: 'Blood Test', priority: 'Routine' as 'Routine' | 'Urgent', notes: '' })
  const [err, setErr] = useState('')
  const p = patients.find((x) => x.id === f.patientId)
  const coord = (useUsers().data ?? []).find((u) => u.id === p?.coordId)
  return (
    <Modal title={patientId && p ? `Request diagnostic test – ${p.name}` : 'Request diagnostic test'} onClose={onClose} submit="Request test" busy={req.isPending} onSubmit={() => {
      if (!f.patientId) return setErr('Select a patient')
      req.mutate(f, { onSuccess: (t) => { toast(`${t.name} requested – task created for the coordinator`); onClose() }, onError: (e) => setErr(e.message) })
    }}>
      <div className="fg">
        {!patientId && <Field label="Patient" req full error={err}><select value={f.patientId} onChange={(e) => setF({ ...f, patientId: e.target.value })}><option value="">Select patient…</option>{patients.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</select></Field>}
        <Field label="Test"><select value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })}>{cat.data?.testTypes.map((t) => <option key={t}>{t}</option>)}</select></Field>
        <Field label="Urgency"><select value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value as 'Routine' | 'Urgent' })}><option>Routine</option><option>Urgent</option></select></Field>
        <Field label="Clinical reason / notes" full error={patientId ? err : undefined}><textarea rows={3} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
      </div>
      <Banner>This creates the test request and a task for the care coordinator{coord ? ` (${coord.name})` : ''} to schedule it.</Banner>
    </Modal>
  )
}

export function ScheduleTestDialog({ test, onClose }: { test: TestItem; onClose: () => void }) {
  const toast = useToast()
  const act = useTestAction()
  const [date, setDate] = useState(test.scheduledDate ?? addDays(todayIso(), 3))
  const [err, setErr] = useState('')
  return (
    <Modal title={`Schedule ${test.name}`} onClose={onClose} submit="Schedule test" busy={act.isPending} onSubmit={() => {
      if (!date) return setErr('Date is required')
      act.mutate({ id: test.id, action: 'schedule', body: { date } }, { onSuccess: () => { toast(`${test.name} scheduled for ${fmtDate(date)} – reminders scheduled (simulated)`); onClose() }, onError: (e) => setErr(e.message) })
    }}>
      <div className="fg"><Field label="Test date" req full error={err}><input type="date" min={todayIso()} value={date} onChange={(e) => setDate(e.target.value)} /></Field></div>
      <Banner>Scheduling creates diagnostic-test reminders (simulated).</Banner>
    </Modal>
  )
}

export function SimulateResultDialog({ test, onClose }: { test: TestItem; onClose: () => void }) {
  const toast = useToast()
  const act = useTestAction()
  const [abn, setAbn] = useState('no')
  return (
    <Modal title={`Simulate result feed – ${test.name}`} onClose={onClose} submit="Deliver synthetic result" busy={act.isPending}
      onSubmit={() => act.mutate({ id: test.id, action: 'result', body: { abnormal: abn === 'yes' } }, { onSuccess: () => { toast('Result received – doctor notified'); onClose() }, onError: (e) => toast(e.message, true) })}>
      <Banner warn>No lab system is connected. This generates a <b>synthetic</b> result so you can demonstrate the review workflow.</Banner>
      <div className="fg mt"><Field label="Synthetic values" full><select value={abn} onChange={(e) => setAbn(e.target.value)}><option value="no">Within reference range</option><option value="yes">Outside reference range (flags for review)</option></select></Field></div>
    </Modal>
  )
}

export function ReviewResultDialog({ test, onClose }: { test: TestItem; onClose: () => void }) {
  const toast = useToast()
  const act = useTestAction()
  const create = useCreateTask()
  const patients = usePatientOptions()
  const [note, setNote] = useState('')
  const [followUp, setFollowUp] = useState(false)
  const submit = () => act.mutate({ id: test.id, action: 'review', body: { note } }, {
    onSuccess: () => {
      const coord = patients.find((p) => p.id === test.patientId)?.coordId
      if (followUp && coord) create.mutate({ title: `Follow up after ${test.name} review`, patientId: test.patientId, assignee: coord, due: addDays(todayIso(), 2),
        priority: test.abnormal ? 'high' : 'med', kind: 'followup', description: note })
      toast('Review recorded' + (followUp ? ' – follow-up task created' : '')); onClose()
    }, onError: (e) => toast(e.message, true) })
  return (
    <Modal title={`Review ${test.name} result`} onClose={onClose} submit="Sign off review" onSubmit={submit} busy={act.isPending}>
      <div className="hl">{test.resultSummary}</div>
      <div className="fg mt">
        <Field label="Review note" full><textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        <div className="field full"><label className="sw" style={{ border: 0, padding: '2px 0' }}><input type="checkbox" checked={followUp} onChange={(e) => setFollowUp(e.target.checked)} /> <span>Create a follow-up task for the care coordinator</span></label></div>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------- tasks, referrals, consultations
const STATUSES: TaskStatus[] = ['New', 'In Progress', 'Waiting for Patient', 'Completed']
export function TaskDialog({ patientId, task, onClose }: { patientId?: string; task?: Task; onClose: () => void }) {
  const toast = useToast()
  const staff = (useUsers().data ?? []).filter((u) => u.role !== 'admin')
  const patients = usePatientOptions()
  const create = useCreateTask()
  const update = useUpdateTask()
  const p0 = task?.patientId ?? patientId ?? ''
  const [f, setF] = useState({ title: task?.title ?? '', patientId: p0, assignee: task?.assignee ?? '', due: task?.due ?? addDays(todayIso(), 2),
    priority: (task?.priority ?? 'med') as Priority, status: (task?.status ?? 'New') as TaskStatus, description: task?.description ?? '' })
  const [err, setErr] = useState<Record<string, string>>({})
  const assignee = f.assignee || (patients.find((p) => p.id === f.patientId)?.coordId ?? staff[0]?.id ?? '')
  const submit = () => {
    const e: Record<string, string> = {}
    if (!f.title.trim()) e.title = 'Task title is required'
    if (!f.due) e.due = 'Due date is required'
    setErr(e)
    if (Object.keys(e).length) return
    if (task) {
      update.mutate({ id: task.id, assignee, due: f.due, priority: f.priority, status: f.status }, { onSuccess: () => { toast('Task updated'); onClose() }, onError: (x) => setErr({ title: x.message }) })
    } else {
      create.mutate({ title: f.title, patientId: f.patientId || undefined, assignee, due: f.due, priority: f.priority, kind: 'followup', description: f.description },
        { onSuccess: (t) => { toast(`Task ${t.id} created and assigned to ${t.assigneeName}`); onClose() }, onError: (x) => setErr({ title: x.message }) })
    }
  }
  return (
    <Modal title={task ? 'Edit task' : 'Create task'} onClose={onClose} submit={task ? 'Save task' : 'Create task'} onSubmit={submit} busy={create.isPending || update.isPending}>
      <div className="fg">
        <Field label="Task title" req full error={err.title}><input type="text" value={f.title} disabled={!!task} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
        <Field label="Patient"><select value={f.patientId} disabled={!!(task || patientId)} onChange={(e) => setF({ ...f, patientId: e.target.value })}>
          <option value="">No patient (general task)</option>{patients.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}</select></Field>
        <Field label="Assigned to"><select value={assignee} onChange={(e) => setF({ ...f, assignee: e.target.value })}>{staff.map((u) => <option key={u.id} value={u.id}>{u.name} ({ROLE_LABEL[u.role]})</option>)}</select></Field>
        <Field label="Priority"><select value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value as Priority })}><option value="high">High</option><option value="med">Medium</option><option value="low">Low</option></select></Field>
        <Field label="Due date" req error={err.due}><input type="date" value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })} /></Field>
        {task && <Field label="Status"><select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value as TaskStatus })}>{STATUSES.map((s) => <option key={s}>{s}</option>)}</select></Field>}
        <Field label="Description" full><textarea rows={3} value={f.description} disabled={!!task} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
      </div>
    </Modal>
  )
}

export function ReassignDialog({ task, onClose }: { task: Task; onClose: () => void }) {
  const toast = useToast()
  const staff = (useUsers().data ?? []).filter((u) => u.role !== 'admin')
  const update = useUpdateTask()
  const [who, setWho] = useState(task.assignee ?? '')
  return (
    <Modal title="Reassign task" onClose={onClose} submit="Reassign" busy={update.isPending}
      onSubmit={() => update.mutate({ id: task.id, assignee: who }, { onSuccess: (t) => { toast(`Task reassigned to ${t.assigneeName}`); onClose() }, onError: (e) => toast(e.message, true) })}>
      <div className="fg"><Field label="Assign to" full><select value={who} onChange={(e) => setWho(e.target.value)}>{staff.map((u) => <option key={u.id} value={u.id}>{u.name} ({ROLE_LABEL[u.role]})</option>)}</select></Field></div>
    </Modal>
  )
}

export function ReferralDialog({ patientId, onClose }: { patientId: string; onClose: () => void }) {
  const toast = useToast()
  const create = useCreateReferral(patientId)
  const [f, setF] = useState({ referredTo: '', reason: '' })
  const [err, setErr] = useState<Record<string, string>>({})
  return (
    <Modal title="Add referral" onClose={onClose} submit="Create referral" busy={create.isPending} onSubmit={() => {
      const e: Record<string, string> = {}
      if (!f.referredTo.trim()) e.referredTo = 'Referred to is required'
      if (!f.reason.trim()) e.reason = 'Reason is required'
      setErr(e)
      if (!Object.keys(e).length) create.mutate(f, { onSuccess: () => { toast('Referral created (status: Pending)'); onClose() }, onError: (x) => setErr({ reason: x.message }) })
    }}>
      <div className="fg">
        <Field label="Referred to" req full error={err.referredTo}><input type="text" placeholder="e.g. Cardiac rehabilitation programme" value={f.referredTo} onChange={(e) => setF({ ...f, referredTo: e.target.value })} /></Field>
        <Field label="Reason" req full error={err.reason}><input type="text" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} /></Field>
      </div>
    </Modal>
  )
}

/** V2 consultation form (rendered inside the patient's Consultation tab, not as a modal). */
export function ConsultationForm({ patientId, onSaved, extra }: { patientId: string; onSaved?: () => void; extra?: ReactNode }) {
  const toast = useToast()
  const save = useRecordConsultation(patientId)
  const T = todayIso()
  const blank = { date: T, notes: '', diagnosis: '', prescription: '', rxConfirm: false, plan: '', followUp: '', instructions: '', createFollowUpTask: true }
  const [f, setF] = useState(blank)
  const [err, setErr] = useState<Record<string, string>>({})
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  const submit = () => {
    const e: Record<string, string> = {}
    if (!f.date) e.date = 'Consultation date is required'
    if (!f.notes.trim()) e.notes = 'Clinical notes are required'
    if (f.prescription.trim() && !f.rxConfirm) e.rxConfirm = 'Confirm that you entered this prescription'
    setErr(e)
    if (Object.keys(e).length) return
    save.mutate({ date: f.date, notes: f.notes, diagnosis: f.diagnosis, prescription: f.prescription, plan: f.plan, followUp: f.followUp || undefined, instructions: f.instructions,
      createFollowUpTask: f.createFollowUpTask }, { onSuccess: () => { toast('Consultation saved'); setF(blank); onSaved?.() }, onError: (x) => setErr({ notes: x.message }) })
  }
  return (
    <>
      <div className="fg">
        <Field label="Consultation date" req error={err.date}><input type="date" max={T} value={f.date} onChange={set('date')} /></Field><div />
        <Field label="Clinical notes" req full error={err.notes}><textarea rows={4} value={f.notes} onChange={set('notes')} /></Field>
        <Field label="Diagnosis" full hint="Recorded by the doctor – never generated by AI"><input type="text" value={f.diagnosis} onChange={set('diagnosis')} /></Field>
        <Field label="Prescription (doctor-entered)" full hint="e.g. drug, dose, frequency. Recorded as entered by you; AI never issues prescriptions."><textarea rows={2} value={f.prescription} onChange={set('prescription')} /></Field>
        {f.prescription.trim() && <div className={'field full' + (err.rxConfirm ? ' bad' : '')}><label className="sw" style={{ border: 0, padding: '2px 0' }}><input type="checkbox" checked={f.rxConfirm} onChange={(e) => setF({ ...f, rxConfirm: e.target.checked })} /> <span>I confirm I am the prescribing clinician and entered this prescription myself</span></label>{err.rxConfirm && <span className="err">{err.rxConfirm}</span>}</div>}
        <Field label="Treatment plan" full><textarea rows={2} value={f.plan} onChange={set('plan')} /></Field>
        <Field label="Follow-up date"><input type="date" min={T} value={f.followUp} onChange={set('followUp')} /></Field><div />
        <Field label="Additional instructions" full><textarea rows={2} value={f.instructions} onChange={set('instructions')} /></Field>
        <div className="field full"><label className="sw" style={{ border: 0, padding: '2px 0' }}><input type="checkbox" checked={f.createFollowUpTask} onChange={(e) => setF({ ...f, createFollowUpTask: e.target.checked })} /> <span>Also create a follow-up task for the care coordinator (when a follow-up date is set)</span></label></div>
      </div>
      <div className="row mt" style={{ flexWrap: 'wrap', gap: 6 }}><button className="btn" onClick={submit} disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Save Consultation Notes'}</button>{extra}</div>
    </>
  )
}
