/** Sign-in – same layout as the V2 loginPage(): role cards, then email + password, "Sign in as …". Real email/password authentication. */
import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { keys, useDemoAccounts, useLogin, useMe } from '../api/hooks'
import type { Role } from '../api/types'
import { Icon } from '../components/Icon'
import { Avatar } from '../components/ui'

interface DemoInfo { enabled: boolean; hasData: boolean | null; scenarios: { id: string; title: string; summary: string }[] }

const ROLES: [Role, string, string][] = [
  ['coordinator', 'Care Coordinator', 'Import patient data, schedule, chase care gaps and follow-ups.'],
  ['doctor', 'Doctor', 'Review summaries and results, record consultations, approve AI recommendations.'],
  ['admin', 'Administrator / Operations Manager', 'Operational dashboards, team activity, users and permissions.'],
]
// the V2 demo persona for each role (first match wins)
const PERSONA: Record<Role, string> = { coordinator: 'priya.nair@careflow.demo', doctor: 'sarah.wilson@careflow.demo', admin: 'marcus.reid@careflow.demo' }

export function LoginPage() {
  const me = useMe()
  const login = useLogin()
  const demo = useDemoAccounts()                       // empty in production
  const nav = useNavigate()
  const from = (useLocation().state as { from?: string } | null)?.from ?? '/'
  const [role, setRole] = useState<Role>('coordinator')
  const [email, setEmail] = useState(PERSONA.coordinator)
  const [password, setPassword] = useState('careflow-demo')
  const demoInfo = useQuery({ queryKey: ['demo-scenarios'], queryFn: () => api<DemoInfo>('/api/demo/scenarios'), retry: false })
  const [scenario, setScenario] = useState<string | null>(null)
  const [loading, setLoading] = useState<string | null>(null)
  const [demoErr, setDemoErr] = useState<string | null>(null)
  const qc = useQueryClient()
  if (me.data && !loading) return <Navigate to={from} replace />

  const accounts = demo.data ?? []
  const persona = (r: Role) => accounts.find((a) => a.email === PERSONA[r]) ?? accounts.find((a) => a.role === r)
  const selected = accounts.find((a) => a.email.toLowerCase() === email.trim().toLowerCase())
  const pick = (r: Role) => { setRole(r); const p = persona(r); if (p) { setEmail(p.email); setPassword('careflow-demo') } }
  const demoOn = !!demoInfo.data?.enabled
  const hasData = !!demoInfo.data?.hasData
  const choice = scenario ?? (hasData ? 'keep' : 'empty')
  const picked = demoInfo.data?.scenarios.find((s) => s.id === choice)
  const submit = (e?: FormEvent) => {
    e?.preventDefault()
    setDemoErr(null)
    login.mutate({ email, password }, {
      onSuccess: async () => {
        // the chosen demo scenario replaces all patient data before the app opens; "keep" leaves the database as it is
        if (demoOn && choice !== 'keep' && (choice !== 'empty' || hasData)) {
          setLoading(picked?.title ?? choice)
          try {
            await api('/api/demo/load', { method: 'POST', body: { scenario: choice } })
            const user = qc.getQueryData(keys.me)
            qc.clear()
            qc.setQueryData(keys.me, user)
          } catch (x) {
            setDemoErr(`Signed in, but the demo data could not be loaded: ${(x as Error).message}`)
            setLoading(null)
            return
          }
        }
        nav(from, { replace: true })
      },
    })
  }

  return (
    <div className="login">
      <div className="l">
        <div className="row" style={{ gap: 10 }}>
          <span className="logo" style={{ color: '#fff', width: 'auto' }}><span className="mark" style={{ background: '#fff', color: 'var(--blue)' }}><Icon name="heart" /></span></span>
          <b style={{ fontSize: 18 }}>Bupa CareFlow Assistant</b>
        </div>
        <h1>Helping care teams stay connected with patients, appointments, and follow-ups.</h1>
        <p>From fragmented patient information to connected, evidence-based and actionable care coordination.</p>
        <div><span className="pill">Care-gap detection</span><span className="pill">Evidence-grounded AI</span><span className="pill">Human-approved actions</span><span className="pill">Full audit trail</span></div>
        <p className="sm" style={{ marginTop: 30, opacity: 0.8 }}>Prototype with fictional patients. Not connected to any healthcare system. AI is advisory only and never diagnoses or prescribes.</p>
      </div>
      <form className="r" onSubmit={submit}>
        <h2 style={{ fontSize: 20, marginBottom: 4 }}>Sign in{accounts.length ? ' (demo)' : ''}</h2>
        <p className="sub">{accounts.length ? 'Choose a role to experience the product from that perspective.' : 'Use your work email and password.'}</p>
        {accounts.length > 0 && ROLES.map(([r, title, desc]) => (
          <button type="button" key={r} className={'rolecard' + (role === r ? ' on' : '')} onClick={() => pick(r)}>
            <Avatar name={persona(r)?.name ?? title} /><span><b>{title}</b><br /><span className="sm mut">{desc}</span></span>
          </button>
        ))}
        <div className="fg mt2">
          <div className="field"><label htmlFor="email">Email</label><input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} /></div>
          <div className="field"><label htmlFor="pw">Password</label><input id="pw" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></div>
        </div>
        {demoOn && (
          <div className="fg mt2" style={{ gridTemplateColumns: '1fr' }}>
            <div className="field">
              <label htmlFor="scenario">Demo data to show after sign-in</label>
              <select id="scenario" value={choice} onChange={(e) => setScenario(e.target.value)}>
                {hasData && <option value="keep">Keep current data</option>}
                {demoInfo.data!.scenarios.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
              </select>
              <span className="hint">{choice === 'keep' ? 'Continue with the data already in the system.' : picked?.summary}
                {choice !== 'keep' && hasData && <b style={{ color: 'var(--amb)' }}> Replaces all current patient data.</b>}</span>
            </div>
          </div>
        )}
        {(login.error || demoErr) && <div className="err mt2" style={{ color: 'var(--red)' }} role="alert">{login.error?.message ?? demoErr}</div>}
        <div className="row mt"><button className="btn" type="submit" disabled={login.isPending || !!loading}>
          {loading ? `Loading “${loading}”…` : login.isPending ? 'Signing in…' : `Sign in${selected ? ` as ${selected.name}` : ''}`}</button></div>
        {accounts.length > 0 && <p className="sm mut mt2">Demo password for all users: <code>careflow-demo</code>. Data is stored in the CareFlow database on the server. Other demo accounts: {accounts.filter((a) => !Object.values(PERSONA).includes(a.email)).slice(0, 3).map((a) => a.name).join(', ')} – type their email above.</p>}
      </form>
    </div>
  )
}
