import { useLocation, useNavigate } from 'react-router-dom'
import { Icon } from '../components/Icon'
import { NAV } from '../components/Layout'

/** Screens not yet moved to the new API – shown in the V2 "restricted" card style. */
export function ComingSoonPage() {
  const { pathname } = useLocation()
  const nav = useNavigate()
  const item = NAV.find((n) => n.to === pathname)
  return (
    <div className="card" style={{ maxWidth: 560, margin: '40px auto', textAlign: 'center' }}>
      <div style={{ color: 'var(--blue)' }}><Icon name={item?.icon ?? 'info'} /></div>
      <h2 style={{ justifyContent: 'center' }}>{item ? item.label : 'Page not found'}</h2>
      <p className="mut">{item ? 'This area is being moved to the new CareFlow API and will be available in the next release.' : 'This page does not exist.'}</p>
      <button className="btn" onClick={() => nav('/')}>Back to dashboard</button>
    </div>
  )
}
