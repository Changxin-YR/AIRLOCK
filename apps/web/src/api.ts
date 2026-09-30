export class ApiError extends Error {
  constructor(public code:string, message:string, public status:number) { super(message) }
}
let csrf = ''
export function setCsrf(value:string) { csrf = value }
export async function api<T>(path:string, options:RequestInit = {}):Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body) headers.set('Content-Type','application/json')
  if (options.method && options.method !== 'GET') headers.set('X-CSRF-Token',csrf)
  let response:Response
  try { response = await fetch('/api'+path,{...options,headers,credentials:'same-origin',signal:options.signal ?? AbortSignal.timeout(15000)}) }
  catch { throw new ApiError('NETWORK_UNAVAILABLE','连接中断或请求超时。请刷新状态，不要假定操作未执行。',0) }
  const data = await response.json().catch(()=>({}))
  if (!response.ok) {
    if (response.status===401 && path!=='/session') window.dispatchEvent(new Event('airlock:expired'))
    throw new ApiError(data.error?.code ?? 'REQUEST_FAILED',data.error?.safe_message ?? '请求未完成，请刷新后查看。',response.status)
  }
  return data as T
}
export const newKey = () => crypto.randomUUID()
