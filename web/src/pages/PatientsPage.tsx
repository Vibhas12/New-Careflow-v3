/** Patient directory – same filters, columns and row behaviour as V2 PAGES.patients; filtering is done by the API. */
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { usePatients, useUsers, type PatientQuery } from '../api/hooks'
import type { Priority, User } from '../api/types'
import { Icon } from '../components/Icon'
import { Avatar, Empty, ErrorBanner, Loading, PageHead, PriorityBadge, StatusBadge, Table } from '../components/ui'
import { age, fmtDate } from '../lib/format'

const DEPTS = ['Cardiology', 'Neurology', 'Oncology', 'Orthopedics', 'General Medicine', 'Mental Health']
const SORT: Record<string, PatientQuery['sort']> = { priority: 'priority', appt: 'nextAppt', name: 'name' }

export function PatientsPage({ user }: { user: User }) {
  const nav = useNavigate()
  const [sp, setSp] = useSearchParams()
  const doctors = (useUsers().data ?? []).filter((u) => u.role === 'doctor')
  const [name, setName] = useState(sp.get('search') ?? '')
  const f = (k: string) => sp.get(k) ?? ''
  const set = (k: string, v: string) => { const n = new URLSearchParams(sp); v ? n.set(k, v) : n.delete(k); setSp(n, { replace: true }) }
  useEffect(() => { const t = setTimeout(() => name.trim() !== f('search') && set('search', name.trim()), 250); return () => clearTimeout(t) }, [name]) // eslint-disable-line react-hooks/exhaustive-deps
  const res = usePatients({
    search: f('search') || undefined, department: f('dept') || undefined, doctorId: f('doctor') || undefined, priority: (f('priority') as Priority) || undefined,
    status: f('status') || undefined, mine: f('mine') === '1' || undefined, sort: SORT[f('sort') || 'priority'], pageSize: 100,
  } as PatientQuery)
  const rows = res.data?.items ?? []

  return (
    <>
      <PageHead title="Patients" sub={`Searchable directory of ${user.role === 'doctor' ? 'your assigned patients' : 'patients in the care-coordination service'}.`}
        actions={user.role === 'coordinator' && <button className="btn" onClick={() => nav('/import')}><Icon name="upload" small /> Import patient data</button>} />
      <div className="filters">
        <label>Name / Patient ID<input type="text" placeholder="Search…" value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label>Department<select value={f('dept')} onChange={(e) => set('dept', e.target.value)}><option value="">All</option>{DEPTS.map((d) => <option key={d}>{d}</option>)}</select></label>
        {user.role === 'coordinator' && <label>Assigned doctor<select value={f('doctor')} onChange={(e) => set('doctor', e.target.value)}><option value="">All</option>{doctors.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>}
        <label>Priority<select value={f('priority')} onChange={(e) => set('priority', e.target.value)}><option value="">All</option><option value="high">High</option><option value="med">Medium</option><option value="low">Low</option></select></label>
        <label>Status<select value={f('status')} onChange={(e) => set('status', e.target.value)}><option value="">All</option>{['Active', 'Under follow-up', 'Awaiting results', 'Discharged'].map((s) => <option key={s}>{s}</option>)}</select></label>
        <label>Sort by<select value={f('sort') || 'priority'} onChange={(e) => set('sort', e.target.value)}><option value="priority">Priority</option><option value="appt">Next appointment date</option><option value="name">Patient name</option></select></label>
        {user.role === 'coordinator' && <label className="row" style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 6 }}>
          <input type="checkbox" checked={f('mine') === '1'} onChange={(e) => set('mine', e.target.checked ? '1' : '')} style={{ width: 'auto' }} /> Only my assigned patients</label>}
        <span className="mut sm" style={{ marginBottom: 8 }}>{res.data?.total ?? 0} patient(s)</span>
      </div>
      <ErrorBanner error={res.error} />
      {res.isLoading ? <Loading /> : (
        <>
          <Table head={['Patient', 'ID', 'Age', 'Department', 'Primary condition', 'Assigned doctor', 'Last appt', 'Next appt', 'Priority', 'Status']}>
            {rows.map((p) => (
              <tr key={p.id} className="click" onClick={() => nav(`/patients/${p.id}`)}>
                <td><div className="row"><Avatar name={`${p.firstName} ${p.lastName}`} /><b>{p.firstName} {p.lastName}</b></div></td>
                <td>{p.id}</td><td>{age(p.dob)}</td><td>{p.department}</td><td>{p.primaryCondition}</td><td>{p.doctorName ?? '—'}</td>
                <td>{fmtDate(p.lastVisit)}</td><td>{p.nextAppt ? `${fmtDate(p.nextAppt.date)} ${p.nextAppt.time}` : '—'}</td>
                <td><PriorityBadge p={p.priority} /></td><td><StatusBadge s={p.status} /></td>
              </tr>
            ))}
          </Table>
          {!rows.length && <Empty title="No patients match these filters" hint={'Clear a filter' + (user.role === 'coordinator' ? ' or add patients through Data Import.' : '.')} />}
        </>
      )}
    </>
  )
}
