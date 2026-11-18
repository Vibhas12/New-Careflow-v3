/** Diagnostic tests – same KPIs, filters, table and one-step actions as V2 PAGES.tests. */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { TestItem, User } from '../api/types'
import { useTestAction, useTests } from '../api/workflows'
import { TestDetailDialog } from '../components/details'
import { RequestTestDialog, ReviewResultDialog, ScheduleTestDialog, SimulateResultDialog } from '../components/dialogs'
import { Icon } from '../components/Icon'
import { useToast } from '../components/Toast'
import { Empty, ErrorBanner, Kpi, Loading, PageHead, StatusBadge, Table } from '../components/ui'
import { fmtDate } from '../lib/format'

const PEND = ['Ordered', 'Scheduled', 'Completed']
const DEPTS = ['Cardiology', 'Neurology', 'Oncology', 'Orthopedics', 'General Medicine', 'Mental Health']

export function TestsPage({ user }: { user: User }) {
  const toast = useToast()
  const res = useTests('all')
  const act = useTestAction()
  const [f, setF] = useState({ q: '', status: '', dept: '' })
  const [dlg, setDlg] = useState<{ k: 'request' | 'schedule' | 'result' | 'review' | 'view'; t?: TestItem } | null>(null)
  const all = res.data ?? []
  const rows = all.filter((t) => (!f.status || (f.status === 'pending' ? PEND.includes(t.status) : f.status === 'review' ? t.status === 'Result Available' : t.status === f.status))
    && (!f.dept || t.department === f.dept) && (!f.q || `${t.patientName}${t.patientId}${t.name}`.toLowerCase().includes(f.q.toLowerCase())))
  const coord = user.role === 'coordinator', doctor = user.role === 'doctor'
  const complete = (t: TestItem) => act.mutate({ id: t.id, action: 'complete' }, { onSuccess: () => toast('Marked completed – ordering doctor notified'), onError: (e) => toast(e.message, true) })
  const action = (t: TestItem) =>
    t.status === 'Ordered' && coord ? <button className="btn s" onClick={() => setDlg({ k: 'schedule', t })}>Schedule</button>
    : t.status === 'Scheduled' && coord ? <button className="btn s" onClick={() => complete(t)}>Patient completed</button>
    : t.status === 'Completed' ? <button className="btn s" onClick={() => setDlg({ k: 'result', t })}>Simulate result</button>
    : t.status === 'Result Available' && doctor ? <button className="btn s" onClick={() => setDlg({ k: 'review', t })}>Review</button>
    : <button className="btn ghost s" onClick={() => setDlg({ k: 'view', t })}>View</button>

  return (
    <>
      <PageHead title="Diagnostic Tests" sub="Track investigations from order to doctor review."
        actions={doctor && <button className="btn" onClick={() => setDlg({ k: 'request' })}><Icon name="plus" small /> Request test</button>} />
      <div className="grid g4 mt2">
        <Kpi label="Pending (ordered, scheduled or awaiting result)" value={all.filter((t) => PEND.includes(t.status)).length} tone="amb" onClick={() => setF({ ...f, status: 'pending' })} />
        <Kpi label="Results awaiting doctor review" value={all.filter((t) => t.status === 'Result Available').length} tone="red" onClick={() => setF({ ...f, status: 'review' })} />
        <Kpi label="Reviewed" value={all.filter((t) => t.status === 'Reviewed').length} tone="grn" onClick={() => setF({ ...f, status: 'Reviewed' })} />
        <Kpi label="All tests" value={all.length} onClick={() => setF({ ...f, status: '' })} />
      </div>
      <div className="filters">
        <label>Search<input type="text" placeholder="Patient or test" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} /></label>
        <label>Status<select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
          <option value="">All</option><option value="pending">Pending (all)</option><option value="review">Awaiting review</option>
          {['Ordered', 'Scheduled', 'Completed', 'Result Available', 'Reviewed'].map((s) => <option key={s}>{s}</option>)}</select></label>
        <label>Department<select value={f.dept} onChange={(e) => setF({ ...f, dept: e.target.value })}><option value="">All</option>{DEPTS.map((d) => <option key={d}>{d}</option>)}</select></label>
        <span className="sm mut" style={{ marginBottom: 8 }}>{rows.length} test(s)</span>
      </div>
      <ErrorBanner error={res.error} />
      {res.isLoading ? <Loading /> : <>
        <Table head={['Test', 'Patient', 'Department', 'Ordering doctor', 'Ordered', 'Test date', 'Status', 'Result', 'Actions']}>{rows.map((t) => (
          <tr key={t.id}>
            <td><a href="#" className="b" onClick={(e) => { e.preventDefault(); setDlg({ k: 'view', t }) }}>{t.name}</a><br /><span className="sm mut">{t.id}{t.priority === 'Urgent' && <> · <b style={{ color: 'var(--red)' }}>Urgent</b></>}</span></td>
            <td><Link className="b" to={`/patients/${t.patientId}`}>{t.patientName}</Link></td><td>{t.department ?? '—'}</td><td>{t.orderedByName ?? '—'}</td>
            <td>{fmtDate(t.orderedOn)}</td><td>{fmtDate(t.completedOn || t.scheduledDate)}</td>
            <td><StatusBadge s={t.status} />{t.abnormal && t.status === 'Result Available' && <> <span className="badge b-high">Flagged</span></>}</td>
            <td>{t.resultSummary ? 'Available' : '—'}</td><td className="nowrap">{action(t)}</td>
          </tr>
        ))}</Table>
        {!rows.length && <Empty title="No tests match" />}
      </>}
      {dlg?.k === 'request' && <RequestTestDialog onClose={() => setDlg(null)} />}
      {dlg?.k === 'schedule' && dlg.t && <ScheduleTestDialog test={dlg.t} onClose={() => setDlg(null)} />}
      {dlg?.k === 'result' && dlg.t && <SimulateResultDialog test={dlg.t} onClose={() => setDlg(null)} />}
      {dlg?.k === 'review' && dlg.t && <ReviewResultDialog test={dlg.t} onClose={() => setDlg(null)} />}
      {dlg?.k === 'view' && dlg.t && <TestDetailDialog test={dlg.t} onClose={() => setDlg(null)} />}
    </>
  )
}
