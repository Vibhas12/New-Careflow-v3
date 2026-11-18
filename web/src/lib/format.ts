import type { Priority, Role } from '../api/types'

export const PRIORITY_LABEL: Record<Priority, string> = { high: 'High', med: 'Medium', low: 'Low' }
export const ROLE_LABEL: Record<Role | 'system', string> = { coordinator: 'Care Coordinator', doctor: 'Doctor', admin: 'Operations Manager', system: 'System' }

// same output as V2 fmtD / fmtDT: "6 Nov 2026", "18 Nov 2026, 23:31" (fixed month names – no locale "Sept")
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const pad2 = (n: number) => String(n).padStart(2, '0')

/** "Sat 21 Nov" – V2 fmtDS() */
export const fmtDS = (s: string | null | undefined) => {
  if (!s) return '—'
  const d = new Date(s.slice(0, 10) + 'T00:00:00')
  return `${DOW[d.getDay()]} ${d.getDate()} ${MON[d.getMonth()]}`
}
export const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

export const fmtDate = (s: string | null | undefined) => {
  if (!s) return '—'
  const d = new Date(s.length === 10 ? s + 'T00:00:00' : s)
  return `${d.getDate()} ${MON[d.getMonth()]} ${d.getFullYear()}`
}
export const fmtDateTime = (s: string | null | undefined) => {
  if (!s) return '—'
  const d = new Date(s)
  return `${d.getDate()} ${MON[d.getMonth()]} ${d.getFullYear()}, ${pad2(d.getHours())}:${pad2(d.getMinutes())}`
}

export function age(dob: string | null): string {
  if (!dob) return '—'
  const b = new Date(dob + 'T00:00:00'), n = new Date()
  let a = n.getFullYear() - b.getFullYear()
  if (n.getMonth() < b.getMonth() || (n.getMonth() === b.getMonth() && n.getDate() < b.getDate())) a--
  return String(a)
}

export const initials = (name: string) => name.replace(/^Dr\.?\s+/, '').split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase()
