import { onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { api, newKey } from './api'
/** Client-only UX measurement; never consulted for authorization. */
export function useVisibility(element:Ref<HTMLElement|null>, operation:Ref<string|undefined>) {
  const diffOpened=ref(false)
  let observer:IntersectionObserver|null=null, visible=false, since=0, elapsed=0, first:string|null=null
  function update() {
    const time=performance.now()
    if(since) elapsed+=time-since
    since=visible && document.visibilityState==='visible' ? time : 0
    if(since && !first) first=new Date().toISOString()
  }
  function snapshot() { update(); return {visible_ms:Math.min(86400000,Math.round(elapsed)),diff_opened:diffOpened.value,first_visible_at:first??'',event_id:newKey()} }
  async function send(id=operation.value) {
    if(!id || !first) return
    const body=snapshot()
    try { await api(`/reviews/${id}/telemetry`,{method:'POST',body:JSON.stringify(body)}) } catch { /* UX telemetry cannot block a decision. */ }
  }
  watch([element,operation],([node],[,previousId])=>{
    if(previousId && previousId!==operation.value) void send(previousId)
    observer?.disconnect(); visible=false; since=0; elapsed=0; first=null; diffOpened.value=false
    if(node) { observer=new IntersectionObserver(entries=>{visible=entries[0]?.isIntersecting??false; update()},{threshold:.1}); observer.observe(node) }
  },{flush:'post'})
  document.addEventListener('visibilitychange',update)
  onBeforeUnmount(()=>{void send();observer?.disconnect();document.removeEventListener('visibilitychange',update)})
  return {diffOpened,send}
}
