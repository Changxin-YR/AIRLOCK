export class ApiError extends Error { constructor(public code: string, message: string, public status: number) { super(message) } }
let csrf = ''
export function setCsrf(value: string) { csrf = value }
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const headers: Record<string, string> = { ...options.headers as Record<string, string> }
  if (method !== 'GET') { headers['Content-Type'] = 'application/json'; headers['X-CSRF-Token'] = csrf }
  const response = await fetch(path, { ...options, headers, credentials: 'same-origin' })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new ApiError(data.error?.code ?? 'NETWORK_ERROR', data.error?.safe_message ?? '请求失败，请检查服务状态。', response.status)
  return data as T
}
