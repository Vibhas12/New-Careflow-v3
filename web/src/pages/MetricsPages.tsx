/** Doctor Performance Center and Executive Overview – same structure as V2 PAGES.performance / PAGES.executive (frontend/src/08-pages-c.js),
 *  without patient satisfaction and recovery outcomes (removed in phase 4). Aggregates only; "Explain with AI" is on request. */
import { useState } from 'react'
import { useExecutive, usePerformance, type Metric } from '../api/metrics'
import type { User } from '../api/types'
import { InsightsPanel } from '../components/ai'
import { BarChart, LineChart } from '../components/charts'
import { Banner, ErrorBanner, Kpi, Loading, PageHead, Table } from '../components/ui'

const RANGES: [string, string][] = [['30', 'Last 30 days'], ['90', 'Last 90 days'], ['7', 'Last 7 days'], ['180', 'Last 180 days'], ['all', 'All recorded']]
const pct = (v: number) => `${v}%`
const hint = (m: Metric) => `${m.definition} · n=${m.n ?? 0}`
const tone = (m: Metric): 'amb' | 'red' | undefined =>
  (m.key === 'pending_reviews' || m.key === 'open_care_gaps') && (m.value ?? 0) > 0 ? 'amb' : m.key === 'missed_appointments' && (m.value ?? 0) > 0 ? 'red' : undefined

function Kpis({ items }: { items: Metric[] }) {
  return <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))' }}>
    {items.map((m) => <Kpi key={m.key} label={m.label} value={m.display} hint={hint(m)} tone={tone(m)} />)}</div>
}

export function PerformancePage({ user }: { user: User }) {
  const [f, setF] = useState<{ doctorId: string; dept: string; range: string }>({ doctorId: '', dept: '', range: '90' })
  const filter = { doctorId: f.doctorId || undefined, dept: f.dept || undefined, range: f.range }
  const q = usePerformance(filter)
  const d = q.data
  const s = d?.weekly.series ?? {}
  return (
    <>
      <PageHead title="Doctor Performance Center" sub="Operational coordination measures – not clinical performance rankings." />
      <Banner>Measures describe workflow activity (attendance, follow-up timeliness, review turnaround). They do not rank clinical quality or outcomes.
        {user.role === 'doctor' && ' You see your own figures only.'}</Banner>
      <div className="filters">
        {user.role !== 'doctor' && <label>Doctor<select value={f.doctorId} onChange={(e) => setF({ ...f, doctorId: e.target.value })}>
          <option value="">All doctors</option>{(d?.doctors ?? []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>}
        <label>Department<select value={f.dept} onChange={(e) => setF({ ...f, dept: e.target.value })}>
          <option value="">All departments</option>{(d?.departments ?? []).map((x) => <option key={x}>{x}</option>)}</select></label>
        <label>Date range<select value={f.range} onChange={(e) => setF({ ...f, range: e.target.value })}>{RANGES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
      </div>
      <ErrorBanner error={q.error} />
      {!d ? <Loading /> : <>
        <Kpis items={d.kpis} />
        <div className="grid g2 mt">
          <div className="card"><h2>Appointment attendance (% attended, weekly)</h2>
            <LineChart title="Weekly attendance" labels={d.weekly.labels} series={[{ name: 'Attendance %', values: s['Attendance %'] ?? [] }]} max={100} fmt={pct} /></div>
          <div className="card"><h2>Consultation activity (appointments per week)</h2>
            <BarChart title="Weekly appointment outcomes" labels={d.weekly.labels} series={['Completed', 'Missed', 'Cancelled'].map((n) => ({ name: n, values: s[n] ?? [] }))} /></div>
          <div className="card"><h2>Follow-up completion (tasks per week)</h2>
            <LineChart title="Follow-up tasks created and completed" labels={d.weekly.labels}
              series={[{ name: 'Created', values: s['Follow-ups created'] ?? [] }, { name: 'Completed', values: s['Follow-ups completed'] ?? [] }]} /></div>
          <div className="card"><h2>Patient journey trends (tests ordered per week)</h2>
            <BarChart title="Tests ordered per week" labels={d.weekly.labels} series={[{ name: 'Tests ordered', values: s['Tests ordered'] ?? [] }]} /></div>
        </div>
        <InsightsPanel page="performance" filter={filter} kpis={d.kpis} />
      </>}
    </>
  )
}

export function ExecutivePage() {
  const [range, setRange] = useState('90')
  const q = useExecutive(range)
  const d = q.data
  const k = new Map((d?.kpis ?? []).map((m) => [m.key, m]))
  const pick = (...keys: string[]) => keys.map((x) => k.get(x)).filter(Boolean) as Metric[]
  const Sect = ({ t }: { t: string }) => <h2 className="mt" style={{ fontSize: 17 }}>{t}</h2>
  return (
    <>
      <PageHead title="Bupa CareFlow – Executive Overview" sub="Care coordination and operations at a glance (prototype data)." />
      <div className="filters"><label>Date range<select value={range} onChange={(e) => setRange(e.target.value)}>{RANGES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label></div>
      <ErrorBanner error={q.error} />
      {!d ? <Loading /> : <>
        <Sect t="Care-coordination indicators" /><Kpis items={pick('followup_completion', 'attendance', 'test_completion', 'reminder_effectiveness')} />
        <Sect t="Operational indicators" /><Kpis items={pick('tasks_completed', 'patients_supported', 'open_care_gaps', 'missed_appointments')} />
        <div className="grid g2 mt">
          <div className="card"><h2>Appointment attendance trend</h2>
            <LineChart title="Weekly attendance" labels={d.weekly.labels} series={[{ name: 'Attendance %', values: d.weekly.series['Attendance %'] ?? [] }]} max={100} fmt={pct} /></div>
          <div className="card"><h2>Tasks completed per week</h2>
            <BarChart title="Tasks completed per week" labels={d.weekly.labels} series={[{ name: 'Tasks completed', values: d.weekly.series['Tasks completed'] ?? [] }]} /></div>
        </div>
        <div className="card mt"><h2>Department comparison</h2>
          <Table head={['Department', 'Attendance', 'Test completion', 'Follow-up completion', 'Open care gaps']}>
            {d.departments.map((x) => <tr key={x.department}><td><b>{x.department}</b></td>
              <td>{x.attendance == null ? '—' : `${x.attendance}%`} <span className="sm mut">n={x.attendanceN}</span></td>
              <td>{x.testCompletion == null ? '—' : `${x.testCompletion}%`} <span className="sm mut">n={x.testN}</span></td>
              <td>{x.followupCompletion == null ? '—' : `${x.followupCompletion}%`} <span className="sm mut">n={x.followupN}</span></td><td>{x.openGaps}</td></tr>)}
          </Table>
          <div className="mt2" style={{ maxWidth: 720 }}><BarChart title="Attendance by department" labels={d.departments.map((x) => x.department.split(' ')[0])}
            series={[{ name: 'Attendance %', values: d.departments.map((x) => x.attendance ?? 0) }]} max={100} fmt={pct} h={180} /></div>
        </div>
        <InsightsPanel page="executive" filter={{ range }} kpis={d.kpis} />
        <Sect t="Business impact – hypotheses to validate" />
        <Banner warn><b>These are proposed pilot targets, not measured results.</b> Each needs a baseline measurement before any improvement can be claimed. Nothing below is derived from the prototype data.</Banner>
        <div className="grid g3">{[['−30%', 'Information-gathering time', 'Estimated time saved'], ['−25%', 'Time to identify care gaps (faster)', 'Coordination efficiency'],
          ['−20%', 'Coordination effort', 'Improved patient engagement']].map(([v, t, h]) => (
          <div key={t} className="card"><div className="sm mut b">{h}</div><div style={{ fontSize: 30, fontWeight: 700, color: 'var(--mut)' }}>{v}</div><div>{t}</div>
            <div className="mt2"><span className="sim">HYPOTHESIS – BASELINE NEEDED</span></div></div>))}</div>
        <div className="card mt"><h2>AI usage signals (measured in this system’s data)</h2>
          <div className="row">{d.aiUsage.map((x) => <div key={x.label} className="hl" style={{ minWidth: 200 }}><div style={{ fontSize: 22, fontWeight: 700 }}>{x.value}</div><div className="sm mut">{x.label}</div></div>)}</div></div>
      </>}
    </>
  )
}
