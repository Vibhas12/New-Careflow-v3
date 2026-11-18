/** Thin fetch wrapper. The session lives in an HttpOnly cookie, so no token is ever handled by JavaScript. */
export class ApiError extends Error {
  status: number
  data: unknown
  constructor(status: number, message: string, data?: unknown) {
    super(message)
    this.status = status
    this.data = data
  }
}

function detailMessage(body: unknown, status: number): string {
  const d = (body as { detail?: unknown })?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map((e) => (e as { msg?: string }).msg ?? 'Invalid value').join('; ')
  if (d && typeof d === 'object' && typeof (d as { message?: unknown }).message === 'string') return (d as { message: string }).message
  return `Request failed (${status})`
}

/** multipart upload (the browser sets the boundary); same session cookie + CSRF header as api() */
export async function upload<T>(path: string, file: File): Promise<T> {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch(path, { method: 'POST', credentials: 'same-origin', headers: { 'X-Requested-With': 'careflow' }, body: fd })
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, detailMessage(body, res.status), (body as { detail?: unknown })?.detail)
  return body as T
}

export async function api<T>(path: string, init: { method?: string; body?: unknown; query?: Record<string, unknown> } = {}): Promise<T> {
  const qs = init.query
    ? '?' + new URLSearchParams(Object.entries(init.query).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => [k, String(v)]))
    : ''
  const res = await fetch(path + qs, {
    method: init.method ?? 'GET',
    credentials: 'same-origin',
    headers: { 'X-Requested-With': 'careflow', ...(init.body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
  })
  if (res.status === 204) return undefined as T
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, detailMessage(body, res.status), (body as { detail?: unknown })?.detail)
  return body as T
}
