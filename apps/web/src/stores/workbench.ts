import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, ApiError, setCsrf } from '../api'
import type { Audit, Metrics, Operation, Review, Session } from '../types'

export const useWorkbench = defineStore('workbench', () => {
  const session = ref<Session | null>(null), checked = ref(false), error = ref(''), busy = ref(false)
  const items = ref<Operation[]>([]), total = ref(0), metrics = ref<Metrics | null>(null), selected = ref<Review | null>(null), audit = ref<Audit | null>(null)
  const filter = ref(''), query = ref(''), tab = ref('reviews'), connected = ref(false), page = ref(0)
  let stream: EventSource | null = null, interval: ReturnType<typeof setInterval> | undefined, loading = false
  let refreshGeneration = 0, selectionGeneration = 0
  const displayed = computed(() => items.value.filter(o => `${o.intent} ${o.id} ${o.requester}`.toLowerCase().includes(query.value.toLowerCase())))
  function fail(e: unknown) {
    error.value = e instanceof Error ? e.message : '请求失败'
    if (e instanceof ApiError && e.status === 401) { session.value = null; stop(); setCsrf('') }
  }
  async function check() {
    try { session.value = await api<Session>('/api/session'); setCsrf(session.value.csrf_token); await start() }
    catch (e) { if (!(e instanceof ApiError && e.status === 401)) fail(e) }
    finally { checked.value = true }
  }
  async function login(username: string, password: string) {
    busy.value = true; error.value = ''
    try { session.value = await api<Session>('/api/session/login', { method: 'POST', body: JSON.stringify({ username, password }) }); setCsrf(session.value.csrf_token); await start() }
    catch (e) { fail(e) } finally { busy.value = false }
  }
  async function logout() {
    try { await api('/api/session/logout', { method: 'POST', body: '{}' }); stop(); session.value = null; selected.value = null; items.value = []; setCsrf('') }
    catch (e) { fail(e) }
  }
  function stop() { stream?.close(); stream = null; connected.value = false; if (interval) clearInterval(interval); interval = undefined }
  async function start() {
    stop(); await refresh()
    stream = new EventSource('/api/events')
    stream.onopen = () => { connected.value = true }
    stream.onerror = () => { connected.value = false }
    stream.addEventListener('change', (event) => {
      const payload = JSON.parse((event as MessageEvent).data)
      // Serving a view is an audit event, not a new operation version. Avoid a self-refresh loop.
      if (payload.kind !== 'REVIEW_VIEW_SERVED') { void refresh(); const current = selected.value?.operation; if (current && current.id===payload.operation_id && current.version!==payload.version) void select(payload.operation_id) }
    })
    stream.addEventListener('session_expired', () => { session.value = null; stop(); error.value = '登录已过期，请重新登录。' })
    interval = setInterval(() => { void refresh() }, 5000)
  }
  async function refresh() {
    if (!session.value || loading) return
    loading = true
    const generation = ++refreshGeneration
    try {
      const params = new URLSearchParams({ limit: '30', offset: String(page.value * 30) })
      if (filter.value) params.set('state', filter.value)
      const [result, summary] = await Promise.all([api<{ items: Operation[]; total: number }>(`/api/reviews?${params}`), api<Metrics>('/api/metrics')])
      if (generation !== refreshGeneration) return
      items.value = result.items; total.value = result.total; metrics.value = summary
      const current = selected.value?.operation
      if (current) {
        const updated = result.items.find(o => o.id === current.id)
        if (updated && updated.version !== current.version) await select(current.id)
      }
    } catch (e) { fail(e) } finally { loading = false }
  }
  async function select(id: string) {
    const generation = ++selectionGeneration
    try {
      const [detail, history] = await Promise.all([api<Review>(`/api/reviews/${id}?read_only=${tab.value==='history'}`), api<Audit>(`/api/reviews/${id}/audit`)])
      if (generation === selectionGeneration) { selected.value = detail; audit.value = history }
    } catch (e) { fail(e) }
  }
  async function changeFilter(value: string) { filter.value = value; page.value = 0; await refresh() }
  async function decide(decision: 'approve' | 'reject', reason: string) {
    const review = selected.value
    if (!review?.view_id || !review.operation.plan_digest) return
    busy.value = true; error.value = ''
    try {
      await api(`/api/reviews/${review.operation.id}/decision`, { method: 'POST', body: JSON.stringify({ decision, reason,
        plan_digest: review.operation.plan_digest, expected_version: review.operation.version,
        view_id: review.view_id, idempotency_key: crypto.randomUUID() }) })
      await select(review.operation.id); await refresh()
    } catch (e) { fail(e); await select(review.operation.id) } finally { busy.value = false }
  }
  async function cancel() {
    if (!selected.value) return
    busy.value = true
    const id = selected.value.operation.id
    try { await api(`/api/reviews/${id}/cancel`, { method: 'POST', body: '{}' }); await select(id); await refresh() }
    catch (e) { fail(e) } finally { busy.value = false }
  }
  async function reconcile() {
    const id=selected.value?.operation.id; if(!id) return
    busy.value=true
    try { await api(`/api/reviews/${id}/reconcile`,{method:'POST',body:'{}'}); await select(id); await refresh() }
    catch(e){fail(e)} finally{busy.value=false}
  }
  async function demo(scenario: string) {
    busy.value = true; error.value = ''
    try {
      const op = await api<Operation>('/api/demo', { method: 'POST', body: JSON.stringify({ scenario }), headers: { 'Idempotency-Key': crypto.randomUUID() } })
      tab.value = 'reviews'; filter.value = ''; page.value = 0
      await refresh(); await select(op.id)
    } catch (e) { fail(e) } finally { busy.value = false }
  }
  return { session, checked, error, busy, items, total, metrics, selected, audit, filter, query, tab, connected, page,
    displayed, check, login, logout, refresh, select, decide, cancel, reconcile, demo, changeFilter, stop }
})
