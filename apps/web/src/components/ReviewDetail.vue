<script setup lang="ts">
import { computed,ref,onBeforeUnmount } from 'vue'
import { ElDialog } from 'element-plus/es/components/dialog/index'
import { ElMessage } from 'element-plus/es/components/message/index'
import { api,newKey } from '../api'
import { timestamp,toolNames,type Operation } from '../types'
import { useVisibility } from '../useVisibility'
import StatusBadge from './StatusBadge.vue'
import DiffTable from './DiffTable.vue'
import AuditTimeline from './AuditTimeline.vue'
const props=defineProps<{operation:Operation}>()
const emit=defineEmits<{changed:[]}>()
const root=ref<HTMLElement|null>(null),operationId=computed(()=>props.operation.id)
const {diffOpened,send}=useVisibility(root,operationId)
const tab=ref('changes'),reason=ref(''),rejectOpen=ref(false),working=ref(false),error=ref('')
const time=ref(Date.now()),clock=setInterval(()=>{time.value=Date.now()},1000)
onBeforeUnmount(()=>clearInterval(clock))
const seconds=computed(()=>Math.max(0,Math.ceil(props.operation.expires_at-time.value/1000)))
const pending=computed(()=>props.operation.state==='PENDING_APPROVAL')
const cancelable=computed(()=>['RECEIVED','PREVIEWING','PENDING_APPROVAL','READY'].includes(props.operation.state))
const messages:Record<string,string>={
  STALE:'数据或策略已变化。这份计划不会执行，请创建新的请求重新预检。',
  UNKNOWN:'尚不能确认目标是否已经提交。系统会优先核对原回执，请勿把它当成失败后重新提交。',
  READY:'审批或规则授权已记录，正在等待执行器领取。此时还没有执行成功。',
  EXECUTING:'执行器正在事务内复核并执行，以目标事务回执确认最终结果。',
  BLOCKED:'请求被策略或权限边界阻止，人工审批不能覆盖这一结果。',
  REJECTED:'审批者已拒绝。Agent 需要提出新的、更合适的请求。',
  EXPIRED:'请求有效期已结束，没有新的执行许可。重新操作需要新预检。',
  CANCELLED:'操作在执行领取之前已取消。',
  FAILED:'执行被明确拒绝或失败。请查看错误及审计证据。',
}
async function decide(decision:'approve'|'reject') {
  const plan=props.operation.plan
  if(!plan||working.value) return
  working.value=true;error.value=''
  try {
    const result=await api<Operation>(`/reviews/${props.operation.id}/decision`,{method:'POST',body:JSON.stringify({
      decision,plan_digest:plan.plan_digest,view_digest:plan.view_digest,expected_version:props.operation.version,
      decision_key:newKey(),reason:decision==='reject'?reason.value:''})})
    rejectOpen.value=false
    ElMessage({message:result.state==='READY'?'批准已记录，等待真实执行回执。':result.state==='REJECTED'?'已拒绝此请求。':'操作状态已改变，请查看最新结果。',type:'info'})
    void send();emit('changed')
  } catch(e) { error.value=(e as Error).message; emit('changed') }
  finally { working.value=false }
}
async function command(action:'cancel'|'reconcile') {
  working.value=true;error.value=''
  try { await api(`/operations/${props.operation.id}/${action}`,{method:'POST'});emit('changed') }
  catch(e){error.value=(e as Error).message}
  finally{working.value=false}
}
</script>
<template>
  <article ref="root" class="review-detail" aria-label="操作详情">
    <div class="detail-top"><span class="micro mono">{{operation.id.slice(0,8).toUpperCase()}} · {{operation.resource_id}}</span><StatusBadge :state="operation.state"/></div>
    <h2 class="detail-title">{{operation.task||toolNames[operation.tool]||'数据操作'}}</h2>
    <p class="detail-subtitle">{{toolNames[operation.tool]}} · customers <span>发起于 {{timestamp(operation.created_at)}}</span></p>
    <div v-if="operation.summary" class="impact-summary">
      <div class="impact-primary"><strong>{{operation.summary.total_changed.toLocaleString()}}</strong><span>条业务记录将发生变化</span></div>
      <div class="impact-breakdown"><span><b>{{operation.summary.direct_changed}}</b> 直接变更</span><span><b>{{operation.summary.cascade_changed}}</b> 外键级联</span></div>
    </div>
    <div v-if="operation.plan" class="evidence-strip"><span class="evidence-check">✓</span><div><strong>当前快照内精确预检</strong><p>只覆盖受管 SQLite 业务表 · 恢复方案未配置</p></div><span class="mono micro">{{operation.plan.facts.preview_ms.toFixed(1)}} ms</span></div>
    <div v-if="pending" class="deadline-strip"><span>请核对字段差异后决定。批准只对这份计划有效。</span><span :class="{urgent:seconds<30}">{{seconds>0?`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')} 后过期`:'已到期，等待服务端刷新'}}</span></div>
    <div v-if="messages[operation.state]" class="state-notice" :class="'notice-'+operation.state"><strong>{{messages[operation.state]}}</strong><p v-if="operation.error">{{operation.error.safe_message}} <code>{{operation.error.code}}</code></p></div>
    <div v-if="operation.state==='SUCCEEDED' && operation.result" class="receipt-notice"><span>✓</span><div><strong>执行成功，目标事务回执已确认</strong><p>{{timestamp(operation.result.committed_at)}} · 实际变更 {{operation.result.total_changed}} 条 · 同一操作重试返回原回执</p></div></div>
    <p v-if="error" class="error-banner" role="alert">{{error}}</p>
    <div class="detail-tabs" role="tablist"><button role="tab" :aria-selected="tab==='changes'" :class="{active:tab==='changes'}" @click="tab='changes'">变更与证据</button><button role="tab" :aria-selected="tab==='audit'" :class="{active:tab==='audit'}" @click="tab='audit'">审计时间线</button></div>
    <div class="detail-body">
      <template v-if="tab==='changes'">
        <DiffTable v-if="operation.plan" :changes="operation.plan.facts.changes" @opened="diffOpened=true"/>
        <div v-else class="empty-detail"><div class="loading-ring" v-if="['RECEIVED','PREVIEWING'].includes(operation.state)"></div><p>{{['RECEIVED','PREVIEWING'].includes(operation.state)?'正在生成影子快照和变更证据…':'没有可用的完整预检证据。'}}</p></div>
        <section v-if="operation.result?.query_result" class="query-section"><h3>实际读取结果</h3><div class="table-scroll"><table class="data-table"><thead><tr><th v-for="field in Object.keys(operation.result.query_result.rows[0]??{})" :key="field">{{field}}</th></tr></thead><tbody><tr v-for="(row,index) in operation.result.query_result.rows" :key="index"><td v-for="(value,key) in row" :key="key">{{value}}</td></tr></tbody></table></div><p class="micro">{{operation.result.query_result.truncated?'结果按请求限制截断，未展示全部匹配记录。':'已返回请求范围内的记录。'}}</p></section>
        <details class="evidence-details"><summary>请求参数与计划绑定</summary><p class="micro">参数不能在审批时改写；任何变更必须创建新请求。</p><pre class="code-block">{{JSON.stringify(operation.request,null,2)}}</pre><dl v-if="operation.plan" class="hash-list"><dt>计划摘要</dt><dd>{{operation.plan.plan_digest}}</dd><dt>展示视图</dt><dd>{{operation.plan.view_digest}}</dd><dt>业务快照</dt><dd>{{operation.plan.state_digest}}</dd><dt>策略版本</dt><dd>{{operation.plan.policy_version}}</dd></dl></details>
        <p class="micro scope-note">事实来自后端预检，不由模型生成。执行前再次检查业务快照；历史回放不会产生副作用。</p>
      </template>
      <AuditTimeline v-else :operation-id="operation.id" :version="operation.version"/>
    </div>
    <footer class="decision-bar"><span class="micro">{{pending?'独立人工审批 · 仅批准当前计划':'以服务端状态与目标回执为准'}}</span><div><button v-if="cancelable" class="text-button" :disabled="working" @click="command('cancel')">取消请求</button><button v-if="pending" class="secondary danger-text" :disabled="working||seconds===0" @click="reason='';rejectOpen=true">拒绝</button><button v-if="pending" class="primary" :disabled="working||seconds===0" @click="decide('approve')">{{working?'正在提交…':'批准这份变更'}}</button><button v-if="operation.state==='UNKNOWN'" class="primary" :disabled="working" @click="command('reconcile')">核对原执行回执</button></div></footer>
    <ElDialog v-model="rejectOpen" title="拒绝这份变更" width="min(460px, calc(100vw - 32px))" :close-on-click-modal="false" :close-on-press-escape="!working" :show-close="!working">
      <p class="dialog-note">提供清楚的修改方向。拒绝不会修改原计划，也不会授权替代操作。</p><label for="rejection-reason">拒绝理由</label><textarea id="rejection-reason" v-model="reason" maxlength="500" rows="4" placeholder="例如：范围过大，请只处理确认过期的测试记录。"></textarea>
      <template #footer><button class="secondary" :disabled="working" @click="rejectOpen=false">返回检查</button><button class="danger" :disabled="working||!reason.trim()" @click="decide('reject')">{{working?'正在提交…':'确认拒绝'}}</button></template>
    </ElDialog>
  </article>
</template>
