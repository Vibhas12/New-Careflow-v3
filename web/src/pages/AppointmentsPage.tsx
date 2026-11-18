/** Appointments calendar – same day / week / month views, chips and legend as V2 PAGES.appointments. */
import { useState } from 'react'
import { useUsers } from '../api/hooks'
import type { AppointmentItem, User } from '../api/types'
import { useAppointments, useCatalog } from '../api/workflows'
import { AppointmentDetailDialog } from '../components/details'
import { BookAppointmentDialog } from '../components/dialogs'
import { Icon } from '../components/Icon'
import { ErrorBanner, PageHead } from '../components/ui'
import { addDays, iso, parse, startOfWeek, todayIso } from '../lib/dates'
import { DOW, fmtDate, fmtDS } from '../lib/format'

type View = 'day' | 'week' | 'month'
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const MONTH = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

export function AppointmentsPage({ user }: { user: User }) {
  const T = todayIso()
  const [view, setView] = useState<View>('week')
  const [cur, setCur] = useState(T)
  const [doctor, setDoctor] = useState('')
  const [status, setStatus] = useState('')
  const [openId, setOpenId] = useState<string | null>(null)
  const [book, setBook] = useState<{ date?: string; time?: string } | null>(null)
  const slots = useCatalog().data?.slots ?? []
  const doctors = (useUsers().data ?? []).filter((u) => u.role === 'doctor')
  const admin = user.role === 'admin'

  let start: string, end: string, title: string
  if (view === 'day') { start = end = cur; title = `${fmtDS(cur)} ${cur.slice(0, 4)}` }
  else if (view === 'week') { start = startOfWeek(cur); end = addDays(start, 6); title = `${fmtDate(start)} – ${fmtDate(end)}` }
  else { const d = parse(cur); d.setDate(1); start = startOfWeek(iso(d)); end = addDays(start, 41); title = `${MONTH[parse(cur).getMonth()]} ${parse(cur).getFullYear()}` }
  const docF = user.role === 'doctor' ? user.id : doctor
  const res = useAppointments({ from: start, to: end, doctorId: docF || undefined, status: status || undefined })
  const all = res.data?.items ?? []

  const move = (n: number) => {
    if (view === 'day') setCur(addDays(cur, n))
    else if (view === 'week') setCur(addDays(cur, 7 * n))
    else { const x = parse(cur); x.setDate(1); x.setMonth(x.getMonth() + n); setCur(iso(x)) }
  }
  const chip = (a: AppointmentItem) => (
    <button key={a.id} className={`ap ${a.status}`} title={`${a.patientName} (${a.patientId}) · ${a.type} · ${a.status}`} onClick={(e) => { e.stopPropagation(); setOpenId(a.id) }}>
      {a.apptTime} {admin ? a.patientId : a.patientName}
    </button>
  )

  let body
  if (view === 'day') {
    body = (
      <div className="dayg">{slots.map((t) => {
        const items = all.filter((a) => a.apptTime === t && a.apptDate === cur)
        return (
          <div className="slot" key={t}><div className="tm">{t}</div><div className="c">
            {items.map((a) => <div key={a.id}>{chip(a)}<div className="sm mut" style={{ margin: '-1px 0 3px 4px' }}>{a.type} · {a.doctorName}</div></div>)}
            {!items.length && !admin && cur >= T && <button className="btn ghost s" onClick={() => setBook({ date: cur, time: t })}>+ Book</button>}
          </div></div>
        )
      })}</div>
    )
  } else {
    const n = view === 'week' ? 7 : 42, lim = view === 'month' ? 3 : 99
    body = (
      <div className="cal">
        {[...DOW.slice(1), DOW[0]].map((x) => <div className="dh" key={x}>{x}</div>)}
        {Array.from({ length: n }, (_, i) => {
          const d = addDays(start, i), items = all.filter((a) => a.apptDate === d).sort((a, b) => (a.apptTime ?? '').localeCompare(b.apptTime ?? ''))
          const out = view === 'month' && parse(d).getMonth() !== parse(cur).getMonth()
          return (
            <div key={d} className={`dc ${d === T ? 'today ' : ''}${out ? 'out' : ''}`} style={view === 'week' ? { minHeight: 300 } : undefined} onClick={() => { setView('day'); setCur(d) }}>
              <div className="dn">{parse(d).getDate()}{view === 'week' ? ` ${MON[parse(d).getMonth()]}` : ''}</div>
              {items.slice(0, lim).map(chip)}
              {items.length > lim && <div className="sm mut" style={{ padding: '0 4px' }}>+{items.length - lim} more</div>}
            </div>
          )
        })}
      </div>
    )
  }

  return (
    <>
      <PageHead title="Appointments" sub="Book, confirm, reschedule and track appointments. The calendar updates immediately."
        actions={!admin && <button className="btn" onClick={() => setBook({})}><Icon name="plus" small /> Book appointment</button>} />
      <div className="row sp" style={{ margin: '10px 0' }}>
        <div className="row">
          <button className="btn sec s" aria-label="Previous" onClick={() => move(-1)}><Icon name="chevl" small /></button>
          <button className="btn sec s" onClick={() => setCur(T)}>Today</button>
          <button className="btn sec s" aria-label="Next" onClick={() => move(1)}><Icon name="chev" small /></button>
          <h2 style={{ marginLeft: 8 }}>{title}</h2>
        </div>
        <div className="row">
          <div className="tabs" style={{ margin: 0, border: 0 }}>{(['day', 'week', 'month'] as View[]).map((v) => <button key={v} className={'tab' + (view === v ? ' on' : '')} onClick={() => setView(v)}>{v[0].toUpperCase() + v.slice(1)}</button>)}</div>
          {user.role !== 'doctor' && <select style={{ width: 'auto' }} aria-label="Doctor" value={doctor} onChange={(e) => setDoctor(e.target.value)}><option value="">All doctors</option>{doctors.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select>}
          <select style={{ width: 'auto' }} aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option>{['Scheduled', 'Confirmed', 'Completed', 'Cancelled', 'Missed'].map((s) => <option key={s}>{s}</option>)}</select>
        </div>
      </div>
      <ErrorBanner error={res.error} />
      {body}
      <div className="legend mt2" style={{ gap: 10 }}>
        {['Scheduled', 'Confirmed', 'Completed', 'Missed', 'Cancelled'].map((s) => <span key={s} className={`ap ${s}`} style={{ width: 'auto', display: 'inline-block', margin: 0, cursor: 'default' }}>{s}</span>)}
        <span>{all.length} appointment(s) in view. Click an appointment to confirm, reschedule, cancel or send a reminder.</span>
      </div>
      {openId && <AppointmentDetailDialog id={openId} onClose={() => setOpenId(null)} />}
      {book && <BookAppointmentDialog date={book.date} time={book.time} defaultDoctor={user.role === 'doctor' ? user.id : docF || undefined} onClose={() => setBook(null)} />}
    </>
  )
}
