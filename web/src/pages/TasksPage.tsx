/** Tasks & follow-ups – same KPIs, filters and drag-and-drop kanban as V2 PAGES.tasks. */
import { useState, type DragEvent } from 'react'
import { useUsers } from '../api/hooks'
import type { Task, TaskStatus, User } from '../api/types'
import { useTasks, useUpdateTask } from '../api/workflows'
import { TaskDetailDialog } from '../components/details'
import { TaskDialog } from '../components/dialogs'
import { Icon } from '../components/Icon'
import { useToast } from '../components/Toast'
import { ErrorBanner, Kpi, Loading, PageHead, PriorityBadge } from '../components/ui'
import { addDays, todayIso } from '../lib/dates'
import { fmtDate } from '../lib/format'

const COLS: TaskStatus[] = ['New', 'In Progress', 'Waiting for Patient', 'Completed']

export function TasksPage({ user }: { user: User }) {
  const toast = useToast()
  const T = todayIso()
  const [f, setF] = useState({ q: '', who: '', pri: '' })
  const [over, setOver] = useState<TaskStatus | null>(null)
  const [creating, setCreating] = useState(false)
  const [openId, setOpenId] = useState<string | null>(null)
  const staff = (useUsers().data ?? []).filter((u) => u.role !== 'admin')
  const res = useTasks({ assignee: f.who === 'me' ? user.id : f.who || undefined })
  const upd = useUpdateTask()
  const list = (res.data ?? []).filter((k) => (!f.pri || k.priority === f.pri) && (!f.q || `${k.title}${k.patientName ?? ''}${k.patientId ?? ''}`.toLowerCase().includes(f.q.toLowerCase())))
  const open = list.filter((k) => k.status !== 'Completed')
  const move = (k: Task, status: TaskStatus, msg: string) => k.status !== status && upd.mutate({ id: k.id, status }, { onSuccess: () => toast(msg), onError: (e) => toast(e.message, true) })
  const drop = (e: DragEvent, c: TaskStatus) => { e.preventDefault(); setOver(null); const k = list.find((x) => x.id === e.dataTransfer.getData('text/plain')); if (k) move(k, c, `Moved to ${c}`) }
  const openTask = openId ? list.find((k) => k.id === openId) : undefined

  const card = (k: Task) => {
    const od = k.status !== 'Completed' && !!k.due && k.due < T, ix = COLS.indexOf(k.status)
    return (
      <div key={k.id} className="tk" draggable onDragStart={(e) => e.dataTransfer.setData('text/plain', k.id)}>
        <div className="t" style={{ cursor: 'pointer' }} onClick={() => setOpenId(k.id)}>{k.title}</div>
        <div className="m"><span>{k.patientId ? `${k.patientName}` : 'General'}</span><span><Icon name="user" small /> {k.assigneeName}</span></div>
        <div className="m mt2"><span>Created {fmtDate(k.created)}</span><span>{od ? <b style={{ color: 'var(--red)' }}>Due {fmtDate(k.due)} – overdue</b> : `Due ${fmtDate(k.due)}`}</span></div>
        <div className="row sp mt2"><PriorityBadge p={k.priority} /><span className="row" style={{ gap: 4 }}>
          {ix < 3 && <button className="btn sec s" title={`Move to ${COLS[ix + 1]}`} onClick={() => move(k, COLS[ix + 1], `Task moved to ${COLS[ix + 1]}`)}>→</button>}
          {k.status !== 'Completed' && <button className="btn grn s" title="Mark complete" onClick={() => move(k, 'Completed', 'Task completed')}><Icon name="check" small /></button>}
          <button className="btn ghost s" onClick={() => setOpenId(k.id)}>Details</button>
        </span></div>
      </div>
    )
  }

  return (
    <>
      <PageHead title="Tasks & Follow-ups" sub="Coordinate follow-ups, referrals and reviews. Drag cards between columns or use the buttons."
        actions={user.role !== 'admin' && <button className="btn" onClick={() => setCreating(true)}><Icon name="plus" small /> Create task</button>} />
      <div className="grid g4 mt2">
        <Kpi label="Open tasks" value={open.length} />
        <Kpi label="Overdue" value={open.filter((k) => k.due && k.due < T).length} tone="red" />
        <Kpi label="Due today" value={open.filter((k) => k.due === T).length} tone="amb" />
        <Kpi label="Completed (30 days)" value={list.filter((k) => k.status === 'Completed' && (k.completedOn ?? '') >= addDays(T, -30)).length} tone="grn" />
      </div>
      <div className="filters">
        <label>Search<input type="text" placeholder="Task or patient" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} /></label>
        <label>Assigned to<select value={f.who} onChange={(e) => setF({ ...f, who: e.target.value })}><option value="">Everyone</option><option value="me">Me</option>{staff.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select></label>
        <label>Priority<select value={f.pri} onChange={(e) => setF({ ...f, pri: e.target.value })}><option value="">All</option><option value="high">High</option><option value="med">Medium</option><option value="low">Low</option></select></label>
      </div>
      <ErrorBanner error={res.error} />
      {res.isLoading ? <Loading /> : (
        <div className="kan">{COLS.map((c) => {
          const inCol = list.filter((k) => k.status === c)
          const items = c === 'Completed' ? [...inCol].sort((a, b) => (b.completedOn ?? '').localeCompare(a.completedOn ?? '')).slice(0, 8) : [...inCol].sort((a, b) => (a.due ?? '').localeCompare(b.due ?? ''))
          return (
            <div key={c} className={'col' + (over === c ? ' over' : '')} onDragOver={(e) => { e.preventDefault(); setOver(c) }} onDragLeave={() => setOver(null)} onDrop={(e) => drop(e, c)}>
              <h3>{c}<span className="cnt">{inCol.length}</span></h3>
              {items.length ? items.map(card) : <div className="sm mut" style={{ padding: 10 }}>Drop tasks here</div>}
              {c === 'Completed' && inCol.length > 8 && <div className="sm mut">Showing latest 8</div>}
            </div>
          )
        })}</div>
      )}
      {creating && <TaskDialog onClose={() => setCreating(false)} />}
      {openTask && <TaskDetailDialog task={openTask} onClose={() => setOpenId(null)} />}
    </>
  )
}
