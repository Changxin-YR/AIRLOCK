<script setup lang="ts">
import { ref } from 'vue'
import { api } from '../api'
import { CheckCircle2 } from 'lucide-vue-next'
import { formatTime } from '../types'
import type { Audit } from '../types'
const props = defineProps<{ audit: Audit | null; operationId: string }>()
const snapshots = ref<Record<string, unknown>>({})
const errors = ref<Record<string, string>>({})
async function loadView(id: unknown) {
  if(typeof id !== 'string') return
  try { snapshots.value[id] = await api(`/api/reviews/${props.operationId}/views/${id}`) }
  catch(e) { errors.value[id] = e instanceof Error ? e.message : '读取失败' }
}
const labels: Record<string,string> = { REQUEST_RECEIVED:'收到请求', PREVIEW_STARTED:'开始影子预检', PREVIEW_COMPLETED:'预检完成', REVIEW_VIEW_SERVED:'提供审批证据视图', HUMAN_APPROVED:'审批通过', HUMAN_REJECTED:'人工拒绝', EXECUTION_AUTHORIZED:'授权领取执行任务', EXECUTION_SUCCEEDED:'事务执行成功', RECEIPT_RECOVERED:'通过目标回执恢复结果', BLOCKED:'策略阻止', EXPIRED:'计划过期', STALE:'计划失效', OUTCOME_UNKNOWN:'结果待核实', RECOVERY_REQUIRED:'需要恢复', CANCELLED:'取消请求', AUTHORIZATION_CHANGED:'权限或策略发生变化' }
</script>
<template><section v-if="audit" class="audit-timeline"><div class="section-heading"><h3>只读审计时间线</h3><span :class="['integrity',{'invalid':!audit.chain_valid}]"><CheckCircle2 :size="14"/>{{audit.chain_valid?'摘要链一致':'摘要链异常'}}</span></div><ol><li v-for="event in audit.events" :key="event.id"><span class="timeline-dot"></span><div><strong>{{ labels[event.kind] ?? event.kind }}</strong><time>{{formatTime(event.created_at)}}</time><details><summary>查看证据 #{{event.seq}}</summary><pre>{{JSON.stringify(event.payload,null,2)}}</pre><code class="digest">{{event.event_hash}}</code><div v-if="typeof event.payload.view_id==='string'"><el-button text @click="loadView(event.payload.view_id)">只读查看当时审批视图</el-button><pre v-if="snapshots[event.payload.view_id]">{{JSON.stringify(snapshots[event.payload.view_id],null,2)}}</pre><p v-if="errors[event.payload.view_id]">{{errors[event.payload.view_id]}}</p></div></details></div></li></ol><p class="fineprint">{{audit.limitation}}</p></section></template>
