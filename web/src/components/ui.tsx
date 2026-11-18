/** Small renderers that produce the same markup and CSS classes as the V2 UI (frontend/src/04-ui.js). */
import { useEffect, type ReactNode } from 'react'
import type { Priority } from '../api/types'
import { PRIORITY_LABEL, initials } from '../lib/format'
import { Icon } from './Icon'

export const PriorityBadge = ({ p }: { p: Priority | null | undefined }) =>
  p ? <span className={`badge b-${p}`}>{PRIORITY_LABEL[p]}</span> : <span className="badge b-grey">—</span>

// status → badge colour class, exactly as stBadge() in V2
const ST_MAP: Record<string, string> = { 'In Progress': 'Progress', 'Result Available': 'Result', 'Waiting for Patient': 'Waiting', 'No Response': 'Pending',
  'Under follow-up': 'Progress', 'Awaiting results': 'Pending', Active: 'Confirmed', Discharged: 'Cancelled', 'Follow-up overdue': 'Overdue',
  'Follow-up scheduled': 'Confirmed', 'No follow-up scheduled': 'Pending', 'Not recorded': 'Draft' }
export const StatusBadge = ({ s }: { s: string }) => <span className={`badge b-${ST_MAP[s] ?? s.split(' ')[0].replace(/[^A-Za-z]/g, '')}`}>{s}</span>

export const Avatar = ({ name, lg }: { name: string; lg?: boolean }) => <span className={'avatar' + (lg ? ' lg' : '')}>{initials(name)}</span>

export const Sim = () => <span className="sim" title="Prototype only – no real message is sent">SIMULATED</span>

export function PageHead({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="head">
      <div className="grow"><h1>{title}</h1>{sub && <p className="sub">{sub}</p>}</div>
      {actions && <div className="row">{actions}</div>}
    </div>
  )
}

export const Empty = ({ title, hint }: { title: string; hint?: string }) => (
  <div className="empty"><div className="b">{title}</div>{hint && <div className="sm">{hint}</div>}</div>
)

export function Kpi({ label, value, tone, hint, onClick }: { label: string; value: ReactNode; tone?: 'red' | 'amb' | 'grn'; hint?: string; onClick?: () => void }) {
  return (
    <button type="button" className={`kpi ${tone ?? ''}${onClick ? '' : ' static'}`} onClick={onClick} tabIndex={onClick ? 0 : -1}>
      <span className="v">{value}</span><span className="l">{label}</span>{hint && <span className="h">{hint}</span>}
    </button>
  )
}

export const Banner = ({ warn, icon = 'info', children }: { warn?: boolean; icon?: 'info' | 'shield' | 'phone' | 'check' | 'spark'; children: ReactNode }) => (
  <div className={'banner' + (warn ? ' warn' : '')}><Icon name={icon} /><div>{children}</div></div>
)

/** V2 modal: header with close button, body, optional footer (Cancel/Close + submit). */
export function Modal({ title, onClose, children, footer, size, submit, onSubmit, busy, danger }: {
  title: string; onClose: () => void; children: ReactNode; footer?: ReactNode | false; size?: 'lg'
  submit?: string; onSubmit?: () => void; busy?: boolean; danger?: boolean
}) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])
  const foot = footer === false ? null : footer !== undefined ? <div className="mf">{footer}</div> : (
    <div className="mf">
      <button className="btn sec" onClick={onClose}>{submit ? 'Cancel' : 'Close'}</button>
      {submit && <button className={'btn' + (danger ? ' dng' : '')} onClick={onSubmit} disabled={busy}>{busy ? 'Saving…' : submit}</button>}
    </div>
  )
  return (
    <div className="mb-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={'modal' + (size ? ' ' + size : '')} role="dialog" aria-modal="true" aria-label={title}>
        <div className="mh"><h2>{title}</h2><button className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" /></button></div>
        <div className="mbd">{children}</div>
        {foot}
      </div>
    </div>
  )
}

export const Loading = () => <div className="empty">Loading…</div>

export const ErrorBanner = ({ error }: { error: unknown }) =>
  error ? <div className="banner warn" role="alert"><Icon name="info" /><div>{error instanceof Error ? error.message : String(error)}</div></div> : null

/** <div class="tw"><table class="tbl"> wrapper used everywhere in V2 */
export const Table = ({ head, children }: { head: ReactNode[]; children: ReactNode }) => (
  <div className="tw"><table className="tbl"><thead><tr>{head.map((h, i) => <th key={i}>{h}</th>)}</tr></thead><tbody>{children}</tbody></table></div>
)
