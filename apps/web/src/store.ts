import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, setCsrf, newKey } from './api'
import type { Operation, Session, State } from './types'

export const useWorkbench = defineStore('workbench', () => {
  const session=ref<Session|null>(null), items=ref<Operation[]>([]), selected=ref<Operation|null>(null)
  const states=ref<Partial<Record<State,number>>>({}), total=ref(0), offset=ref(0)
  const filter=ref(''), busy=ref(false), error=ref(''), connected=ref(false), demoEnabled=ref(false)
  let events:EventSource|null=null, timer:ReturnType<typeof setInterval>|null=null
  let refreshTimer:ReturnType<typeof setTimeout>|null=null, selectionRevision=0, listRevision=0
  let refreshing=false, refreshQueued=false, authEpoch=0

  async function restore() {
    try { session.value=await api<Session>('/session'); setCsrf(session.value.csrf); start(); return true }
    catch { return false }
  }
  async function login(username:string,password:string) {
    session.value=await api<Session>('/session',{method:'POST',body:JSON.stringify({username,password})})
    setCsrf(session.value.csrf); await refresh(); start()
  }
  function stop() {
    events?.close(); events=null; connected.value=false
    if(timer) clearInterval(timer); timer=null
    if(refreshTimer) clearTimeout(refreshTimer); refreshTimer=null
  }
  function expire() { stop(); authEpoch++; listRevision++; selectionRevision++; refreshQueued=false; busy.value=false; session.value=null; selected.value=null; items.value=[]; states.value={}; total.value=0; setCsrf('') }
  async function logout() { await api('/session/logout',{method:'POST'}); expire() }
  async function refresh() {
    if(!session.value) return
    if(refreshing) { refreshQueued=true; listRevision++; return }
    refreshing=true; const revision=++listRevision, epoch=authEpoch
    try {
      const [list,overview]=await Promise.all([
        api<{items:Operation[];total:number}>(`/operations?limit=20&offset=${offset.value}${filter.value?'&state='+filter.value:''}`),
        api<{states:Partial<Record<State,number>>;demo_enabled:boolean}>('/overview')])
      if(revision!==listRevision || epoch!==authEpoch || !session.value) return
      items.value=list.items; total.value=list.total; states.value=overview.states; demoEnabled.value=overview.demo_enabled
      const ident=selected.value?.id
      if(ident) {
        const detail=await api<Operation>('/operations/'+ident)
        if(epoch===authEpoch && selected.value?.id===ident && detail.version>=selected.value.version) selected.value=detail
      }
      error.value=''
    } catch(e) { if(epoch===authEpoch && session.value) error.value=(e as Error).message }
    finally { refreshing=false; if(refreshQueued && session.value) {refreshQueued=false; void refresh()} }
  }
  async function select(id:string) {
    const revision=++selectionRevision, epoch=authEpoch; busy.value=true; error.value=''
    try { const detail=await api<Operation>('/operations/'+id); if(revision===selectionRevision && epoch===authEpoch && session.value) selected.value=detail }
    catch(e) { error.value=(e as Error).message }
    finally { if(revision===selectionRevision) busy.value=false }
  }
  async function changeFilter(value:string) { filter.value=value; offset.value=0; await refresh() }
  async function page(delta:number) { offset.value=Math.max(0,offset.value+delta*20); await refresh() }
  function start() {
    stop(); events=new EventSource('/api/events')
    events.addEventListener('ready',()=>{connected.value=true})
    events.addEventListener('change',()=>{
      if(!refreshTimer) refreshTimer=setTimeout(()=>{refreshTimer=null; void refresh()},120)
    })
    events.addEventListener('auth_expired',expire)
    events.onerror=()=>{connected.value=false}
    timer=setInterval(()=>{void refresh()},5000) // Polling fallback; no approval tied to SSE.
    void refresh()
  }
  async function propose(scenario:string) {
    const op=await api<Operation>('/demo/scenarios/'+scenario,{method:'POST',headers:{'Idempotency-Key':newKey()}})
    await select(op.id); await refresh(); return op
  }
  window.addEventListener('airlock:expired',expire)
  return {session,items,selected,states,total,offset,filter,busy,error,connected,demoEnabled,
    restore,login,logout,refresh,select,changeFilter,page,propose,stop}
})
