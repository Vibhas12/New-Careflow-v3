/** Local-date helpers working on YYYY-MM-DD strings (no time-zone drift). */
const pad = (n: number) => String(n).padStart(2, '0')
export const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
export const todayIso = () => iso(new Date())
export const parse = (s: string) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d) }
export const addDays = (s: string, n: number) => { const d = parse(s); d.setDate(d.getDate() + n); return iso(d) }
export const startOfWeek = (s: string) => { const d = parse(s); const dow = (d.getDay() + 6) % 7; d.setDate(d.getDate() - dow); return iso(d) }   // Monday
export const weekdayLabel = (s: string) => parse(s).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
