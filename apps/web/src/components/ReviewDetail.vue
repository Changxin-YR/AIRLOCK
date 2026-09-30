<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch, nextTick } from 'vue'
import { ShieldCheck, Clock3, Database, ArrowRight, FileDiff, AlertTriangle, CheckCircle2, X, LockKeyhole } from 'lucide-vue-next'
import { useWorkbench } from '../stores/workbench'
import { api } from '../api'
import { formatTime, toolLabels } from '../types'
import StatusBadge from './StatusBadge.vue'
import AuditTimeline from './AuditTimeline.vue'
const props = defineProps<{ readOnly?: boolean }>()
const store = useWorkbench(), reason = ref(''), now = ref(Date.now()), root = ref<HTMLElement | null>(null), diffPage = ref(0)
const timer = setInterval(()=>{now.value=Date.now()},1000)
const detail = computed(()=>store.selected), op = computed(()=>detail.value?.operation), preview = computed(()=>detail.value?.view?.preview)
const canDecide = computed(()=>!props.readOnly && op.value?.state==='PENDING_APPROVAL' && !!detail.value?.view_id && op.value.expires_at>now.value)
const remaining = computed(()=>op.value ? Math.max(0,Math.ceil((op.value.expires_at-now.value)/1000)) : 0)
const changes = computed(()=>preview.value?.changes.slice(diffPage.value*3,(diffPage.value+1)*3) ?? [])
const fields = (change: import('../types').Change)=>[...new Set([...Object.keys(change.before??{}),...Object.keys(change.after??{})])].filter(k=>k!=='id' && (k==='name'||!change.before||!change.after||change.before[k]!==change.after[k]))
const displayValue = (v:unknown)=> v===true||v===1 ? '1' : v===false||v===0 ? '0' : String(v??'—')
let observer:IntersectionObserver|undefined, visible=false, started=0, elapsed=0, sentFirst=false
function duration(){return Math.floor(elapsed+(started?performance.now()-started:0))}
function send(event:'first_visible'|'visibility'|'diff_expanded'|'decision_click'){
  const current=detail.value
  if(!current?.view_id) return
  void api(`/api/reviews/${current.operation.id}/telemetry`,{method:'POST',body:JSON.stringify({event,view_id:current.view_id,visible_ms:duration(),hidden:document.hidden})}).catch(()=>{})
}
function track(){
  const active=visible&&!document.hidden
  if(active&&!started){started=performance.now();if(!sentFirst){sentFirst=true;send('first_visible')}}
  if(!active&&started){elapsed+=performance.now()-started;started=0}
}
function visibility(){track();send('visibility')}
watch(()=>detail.value?.view_id,async()=>{
  reason.value='';diffPage.value=0;observer?.disconnect();visible=false;elapsed=0;started=0;sentFirst=false
  await nextTick()
  if(root.value){observer=new IntersectionObserver(([entry])=>{visible=entry.isIntersecting;track()},{threshold:0.15});observer.observe(root.value)}
},{immediate:true})
document.addEventListener('visibilitychange',visibility)
onBeforeUnmount(()=>{clearInterval(timer);observer?.disconnect();document.removeEventListener('visibilitychange',visibility)})
async function decide(value:'approve'|'reject'){send('decision_click');await store.decide(value,reason.value.trim())}
</script>
<template><section ref="root" class="review-detail" aria-label="变更审批详情">
  <div v-if="!op" class="detail-empty"><span class="empty-symbol"><ShieldCheck :size="44"/></span><h2>先看清变更，再做决定。</h2><p>从左侧选择一个请求。这里将展示实际影响、<br/>字段差异与可核对的审批证据。</p><div class="empty-steps"><span><Database :size="18"/>影子预检</span><ArrowRight :size="15"/><span><FileDiff :size="18"/>核对差异</span><ArrowRight :size="15"/><span><LockKeyhole :size="18"/>独立审批</span></div></div>
  <template v-else><header class="detail-header"><div class="detail-kicker"><span>{{op.resource_id}} / customers</span><StatusBadge :state="op.state"/></div><h2>{{op.intent}}</h2><p>{{toolLabels[op.tool]}} <span>·</span> {{op.requester}} <span>·</span> <code>{{op.id.slice(0,12)}}</code></p></header>
    <div v-if="op.error" class="outcome-banner warning"><AlertTriangle :size="19"/><div><strong>{{op.error.code}}</strong><p>{{op.error.safe_message}}</p></div></div>
    <div v-if="op.state==='SUCCEEDED'" class="outcome-banner success"><CheckCircle2 :size="20"/><div><strong>执行完成，回执已保存</strong><p>实际变更 {{op.result?.changed_records}} 条。业务写入与回执在同一目标事务中提交。</p></div></div>
    <template v-if="preview"><section class="impact-summary"><div class="impact-main"><span>本次实际预检影响</span><strong>{{preview.total_changes}}<small>条记录</small></strong></div><div><span>直接变更</span><strong>{{preview.direct_changes}}</strong><small>customers</small></div><div><span>级联变更</span><strong>{{preview.cascaded_changes}}</strong><small>customer_notes</small></div></section>
      <div class="evidence-strip"><span><ShieldCheck :size="15"/>当前快照内精确</span><span><Clock3 :size="15"/>{{formatTime(preview.snapshot_at)}}</span><span>恢复能力：未配置</span><span v-if="preview.non_test_matches">涉及 {{preview.non_test_matches}} 条正式客户</span></div>
      <section class="diff-section"><div class="section-heading"><h3><FileDiff :size="18"/>变更前后对比</h3><span>{{preview.changes.length}} 条完整差异 · 邮箱已隐藏</span></div>
        <div v-if="!preview.changes.length" class="no-diff">此请求不会改变受管业务数据。<span v-if="op.tool==='db.query_rows'">读取结果见下方执行回执。</span></div>
        <div v-for="change in changes" :key="`${change.table}-${change.id}`" class="diff-record"><div class="diff-record-title"><code>{{change.table}} #{{change.id}}</code><span :class="change.kind">{{change.scope==='cascade'?'级联 · ':''}}{{change.kind==='delete'?'删除':change.kind==='update'?'更新':'新增'}}</span></div><div class="diff-grid"><div class="diff-before"><span class="diff-label">变更前</span><dl><template v-for="key in fields(change)" :key="key"><dt>{{key}}</dt><dd :class="{changed:change.before?.[key]!==change.after?.[key]}">{{displayValue(change.before?.[key])}}</dd></template></dl><p v-if="!change.before">不存在</p></div><div class="diff-after"><span class="diff-label">变更后</span><dl v-if="change.after"><template v-for="key in fields(change)" :key="key"><dt>{{key}}</dt><dd :class="{changed:change.before?.[key]!==change.after?.[key]}">{{displayValue(change.after?.[key])}}</dd></template></dl><p v-else class="removed"><X :size="17"/>该记录将被删除</p></div></div></div>
        <div v-if="preview.changes.length>3" class="pagination"><el-button :disabled="diffPage===0" @click="diffPage--;send('diff_expanded')">上一组</el-button><span>{{diffPage*3+1}}–{{Math.min((diffPage+1)*3,preview.changes.length)}} / {{preview.changes.length}}</span><el-button :disabled="(diffPage+1)*3>=preview.changes.length" @click="diffPage++;send('diff_expanded')">下一组</el-button></div>
      </section>
      <details class="technical-details" @toggle="send('diff_expanded')"><summary>查看请求参数、计划摘要与覆盖边界</summary><pre>{{JSON.stringify(detail?.view?.request,null,2)}}</pre><p><strong>计划摘要</strong></p><code class="digest">{{op.plan_digest}}</code><p v-for="limit in preview.limitations" :key="limit" class="fineprint">{{limit}}</p><p class="fineprint">以上事实来自确定性预检，不是模型推测。全受管数据发生变化时，旧计划会失效。</p></details>
    </template>
    <section v-if="canDecide" class="decision-box"><div class="section-heading"><h3>你的决定</h3><span class="deadline"><Clock3 :size="14"/>剩余 {{remaining}} 秒</span></div><label for="reason">审批理由 <span>必填；拒绝理由也会返回 Agent</span></label><el-input id="reason" v-model="reason" type="textarea" :rows="2" maxlength="500" placeholder="说明你核对了哪些内容，或为什么拒绝。"/><p class="fineprint">仅批准这份固定计划。执行前仍会复核数据与权限。请勿在理由中填写敏感信息。</p><div class="decision-actions"><el-button type="primary" :disabled="!reason.trim()" :loading="store.busy" @click="decide('approve')"><CheckCircle2 :size="16"/>批准这次变更</el-button><el-button :disabled="!reason.trim()||store.busy" @click="decide('reject')">拒绝请求</el-button></div></section>
    <p v-else-if="!readOnly && op.state==='PENDING_APPROVAL'" class="outcome-banner warning">审批窗口已过期，不能继续批准。系统正在同步终态。</p>
    <div v-if="op.result" class="receipt"><h3>执行回执</h3><p>{{formatTime(op.result.committed_at)}} · {{op.ready_source==='human'?'人工批准':'策略放行'}}</p><pre>{{JSON.stringify(op.result.rows?.length ? op.result.rows : {operation_id:op.result.operation_id,changed_records:op.result.changed_records,business_state_digest:op.result.business_state_digest},null,2)}}</pre></div>
    <div v-if="!readOnly && ['RECEIVED','PENDING_APPROVAL','READY'].includes(op.state)" class="cancel-line"><el-button text :disabled="store.busy" @click="store.cancel">取消尚未领取的请求</el-button></div>
    <div v-if="!readOnly && op.state==='UNKNOWN'" class="cancel-line"><el-button :loading="store.busy" @click="store.reconcile">重新查询目标回执（不重放操作）</el-button></div><AuditTimeline :audit="store.audit" :operation-id="op.id"/>
  </template>
</section></template>
