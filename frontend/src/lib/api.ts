const TOKEN_KEY = 'myata.token'

export class ApiError extends Error {
  status: number
  payload: unknown

  constructor(status: number, message: string, payload: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

type Query = Record<string, string | number | boolean | undefined | null>

function buildUrl(path: string, query?: Query): string {
  const url = `/api${path}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    params.set(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${url}?${qs}` : url
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function parseError(response: Response): Promise<ApiError> {
  let payload: unknown = null
  let message = `${response.status} ${response.statusText}`
  try {
    payload = await response.json()
    const detail = (payload as { detail?: unknown }).detail
    if (typeof detail === 'string') message = detail
    else if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: string; loc?: unknown[] }
      const field = Array.isArray(first.loc) ? first.loc.slice(1).join('.') : ''
      message = field ? `${field}: ${first.msg ?? 'ошибка'}` : (first.msg ?? message)
    }
  } catch {
    /* keep the status text */
  }
  return new ApiError(response.status, message, payload)
}

async function request<T>(
  method: string,
  path: string,
  options: { body?: unknown; query?: Query; raw?: boolean } = {},
): Promise<T> {
  const response = await fetch(buildUrl(path, options.query), {
    method,
    headers: {
      ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...authHeaders(),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  if (!response.ok) {
    const error = await parseError(response)
    if (error.status === 401 && getToken()) {
      setToken(null)
      window.dispatchEvent(new CustomEvent('myata:signed-out'))
    }
    throw error
  }
  if (options.raw) return (await response.text()) as unknown as T
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>('GET', path, { query }),
  post: <T>(path: string, body?: unknown, query?: Query) => request<T>('POST', path, { body, query }),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, { body }),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, { body }),
  del: <T>(path: string) => request<T>('DELETE', path),
  text: (path: string) => request<string>('GET', path, { raw: true }),
}

export async function uploadImage(file: File): Promise<{ url: string; filename: string }> {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch('/api/admin/upload/image', {
    method: 'POST',
    headers: authHeaders(),
    body: form,
  })
  if (!response.ok) throw await parseError(response)
  return (await response.json()) as { url: string; filename: string }
}

export async function downloadQrPng(tableId: string): Promise<void> {
  const response = await fetch(`/api/admin/hall/tables/${tableId}/qr.png`, { headers: authHeaders() })
  if (!response.ok) throw await parseError(response)
  const blob = await response.blob()
  triggerDownload(blob, `qr-${tableId}.png`)
}

export async function downloadQrSheet(): Promise<void> {
  const response = await fetch('/api/admin/hall/qr/sheet', { headers: authHeaders() })
  if (!response.ok) throw await parseError(response)
  const blob = await response.blob()
  triggerDownload(blob, 'myata-qr-sheet.svg')
}

export function triggerDownload(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
