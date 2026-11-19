/** App shell – same structure and classes as the V2 shell(): top bar (logo, global search, bell, help, user menu), side nav, main page. */
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useLogout, usePatients } from '../api/hooks'
import { useAlertSummary } from '../api/phase3'
import type { Role, User } from '../api/types'
import { useNotifications, useReadNotifications } from '../api/workflows'
import { ROLE_LABEL, fmtDateTime } from '../lib/format'
import { Icon, type IconName } from './Icon'
import { Avatar, Empty, Modal } from './ui'

/** `disabled` items stay visible in the menu but are greyed out and not clickable. */
interface NavItem { to: string; label: string; icon: IconName; roles: Role[]; disabled?: boolean }

export const NAV: NavItem[] = [
  { to: '/', label: 'Dashboard', icon: 'dash', roles: ['coordinator', 'doctor', 'admin'] },
  { to: '/patients', label: 'Patients', icon: 'users', roles: ['coordinator', 'doctor'] },
  { to: '/care-gaps', label: 'Care Gaps & Alerts', icon: 'alert', roles: ['coordinator', 'doctor', 'admin'] },
  { to: '/appointments', label: 'Appointments', icon: 'cal', roles: ['coordinator', 'doctor', 'admin'] },
  { to: '/tests', label: 'Diagnostic Tests', icon: 'flask', roles: ['coordinator', 'doctor'] },
  { to: '/tasks', label: 'Tasks & Follow-ups', icon: 'task', roles: ['coordinator', 'doctor', 'admin'] },
  { to: '/assistant', label: 'AI Care Assistant', icon: 'spark', roles: ['coordinator', 'doctor'] },
  { to: '/performance', label: 'Doctor Performance', icon: 'bars', roles: ['doctor', 'admin'], disabled: true },
  { to: '/executive', label: 'Executive Overview', icon: 'trend', roles: ['admin'], disabled: true },
  { to: '/settings', label: 'Settings', icon: 'cog', roles: ['coordinator', 'doctor', 'admin'] },
]

function GlobalSearch() {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const nav = useNavigate()
  const res = usePatients({ search: q.trim() || undefined, pageSize: 7, sort: 'name' })
  const go = (id: string) => { setQ(''); setOpen(false); nav(`/patients/${id}`) }
  return (
    <div className="gsearch" onBlur={(e) => !e.currentTarget.contains(e.relatedTarget) && setOpen(false)}>
      <Icon name="search" />
      <input type="text" placeholder="Search patients by name, ID or condition" autoComplete="off" aria-label="Global patient search"
        value={q} onChange={(e) => { setQ(e.target.value); setOpen(true) }} onFocus={() => setOpen(true)} />
      {open && q.trim() && (
        <div className="gdrop">
          {res.data?.items.length ? res.data.items.map((p) => (
            <button key={p.id} onMouseDown={(e) => e.preventDefault()} onClick={() => go(p.id)}>
              <Avatar name={`${p.firstName} ${p.lastName}`} />
              <span><b>{p.firstName} {p.lastName}</b><br /><span className="sm mut">{p.id} · {p.primaryCondition}</span></span>
            </button>
          )) : <div className="empty">{res.isFetching ? 'Searching…' : 'No matching authorised patients'}</div>}
        </div>
      )}
    </div>
  )
}

export function HelpDialog({ onClose }: { onClose: () => void }) {
  return (
    <Modal title="Help & safe-use notes" onClose={onClose}>
      <p><b>Bupa CareFlow Assistant</b> helps care teams coordinate patient journeys. Everything shown is <b>fictional demo data</b>.</p>
      <ul>
        <li><b>Care gaps</b> come from explainable, configurable rules (Settings → Priority Configuration). AI only explains and summarises them.</li>
        <li><b>AI suggestions</b> are labelled and need approval by an authorised person before any task or reminder is created.</li>
        <li>Prescriptions are doctor-entered only. The AI never diagnoses or prescribes.</li>
        <li>Reminders, SMS, email and app notifications are <b>simulated</b>; nothing is actually sent.</li>
        <li>The AI Care Assistant is template-based: no language model is connected, and its proposals need approval.</li>
        <li>The language model (Gemini) is called <b>only when you click</b> an AI button such as <i>Generate with AI</i>. Scans, imports and page loads never call it.</li>
      </ul>
      <p className="mut sm">Roles: Care Coordinator, Doctor, Administrator. Use the profile menu (top right) to switch role.</p>
    </Modal>
  )
}

export function Layout({ user }: { user: User }) {
  const nav = useNavigate()
  const loc = useLocation()
  const logout = useLogout()
  const notes = useNotifications()
  const read = useReadNotifications()
  const gaps = useAlertSummary()
  const [pop, setPop] = useState<'bell' | 'menu' | null>(null)
  const [help, setHelp] = useState(false)
  useEffect(() => setPop(null), [loc.pathname])
  const unread = notes.data?.unread ?? 0
  const highGaps = gaps.data?.categories.reduce((n, c) => n + c.high, 0) ?? 0

  return (
    <div className="app">
      <header className="top">
        <div className="logo"><span className="mark"><Icon name="heart" /></span><span>Bupa CareFlow<small>Assistant</small></span></div>
        {user.role !== 'admin' && <GlobalSearch />}
        <div className="topr">
          <button className="icon-btn" aria-label="Notifications" onClick={() => setPop(pop === 'bell' ? null : 'bell')}>
            <Icon name="bell" />{unread > 0 && <span className="dot">{unread}</span>}
          </button>
          <button className="icon-btn" aria-label="Help" onClick={() => setHelp(true)}><Icon name="help" /></button>
          <button className="user" aria-label="User menu" onClick={() => setPop(pop === 'menu' ? null : 'menu')}>
            <Avatar name={user.name} /><span><b>{user.name}</b><br /><span className="rolechip">{ROLE_LABEL[user.role]}</span></span>
          </button>
        </div>
        {pop === 'bell' && (
          <div className="pop" style={{ right: 70 }}>
            <div className="row sp" style={{ padding: '10px 14px', borderBottom: '1px solid var(--line)' }}><b>Notifications</b>
              <button className="btn ghost s" onClick={() => read.mutate(undefined)}>Mark all read</button></div>
            {notes.data?.items.length ? notes.data.items.slice(0, 14).map((n) => (
              <button key={n.id} className={'it' + (n.isRead ? '' : ' unread')} onClick={() => {
                if (!n.isRead) read.mutate(n.id)
                setPop(null)
                const r = n.route ?? ''
                nav(r.startsWith('patient') ? `/patients/${n.patientId}` : `/${r === 'caregaps' ? 'care-gaps' : r}`)
              }}>
                <div className="b">{n.title}</div><div className="sm mut">{n.text}</div><div className="sm mut">{fmtDateTime(n.ts)}</div>
              </button>
            )) : <Empty title="No notifications" />}
          </div>
        )}
        {pop === 'menu' && (
          <div className="pop" style={{ right: 12, width: 270, padding: 12 }}>
            <div className="row"><Avatar name={user.name} /><div><b>{user.name}</b><div className="sm mut">{user.title}</div><div className="sm mut">{user.email}</div></div></div>
            <div className="hl mt2 sm">Current role: <b>{ROLE_LABEL[user.role]}</b></div>
            <div className="row mt2">
              <button className="btn sec s" onClick={() => nav('/settings')}><Icon name="cog" small /> Settings</button>
              <button className="btn dng s" onClick={() => logout.mutate(undefined, { onSettled: () => nav('/login') })}><Icon name="out" small /> Switch role / sign out</button>
            </div>
          </div>
        )}
      </header>
      <nav className="side" aria-label="Main navigation">
        {NAV.filter((n) => n.roles.includes(user.role)).map((n) => n.disabled ? (
          <span key={n.to} className="nav disabled" aria-disabled="true" title={`${n.label} is not available in this version`}>
            <Icon name={n.icon} /><span>{n.label}</span></span>
        ) : (
          <NavLink key={n.to} to={n.to} end={n.to === '/'} className={({ isActive }) => 'nav' + (isActive || (n.to === '/patients' && loc.pathname.startsWith('/patients')) ? ' on' : '')}>
            <Icon name={n.icon} /><span>{n.label}</span>{n.to === '/care-gaps' && highGaps > 0 && <span className="n">{highGaps}</span>}
          </NavLink>
        ))}
        <div className="demo-note"><b>V3 prototype.</b> Fictional data only. Notifications are simulated. <span className="sync ok">Saved to database</span></div>
      </nav>
      <main className="main"><div className="page"><Outlet /></div></main>
      {help && <HelpDialog onClose={() => setHelp(false)} />}
    </div>
  )
}
