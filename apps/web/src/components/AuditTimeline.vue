<script setup lang="ts">
import { ref,watch } from 'vue'
import { api } from '../api'
import { timestamp,type Audit } from '../types'
const props=defineProps<{operationId:string;version:number}>()
const audit=ref<Audit|null>(null),error=ref('')
let generation=0
const names:Record<string,string>={REQUEST_RECEIVED:'接收工具请求',PREVIEW_READY:'影子预检完成',STATE_CHANGED:'状态转换',VIEW_PROVIDED:'向审批会话提供预览',HUMAN_DECISION:'记录人工决定',EXECUTION_AUTHORIZED:'持久化执行许可',EXECUTION_RECEIPT:'收到目标事务回执',RECEIPT_RECOVERED:'通过回执恢复结果',RECOVERY_CLAIMED:'领取核实任务',MANUAL_RECONCILE_REQUESTED:'人工请求核实'}
watch(()=>[props.operationId,props.version],async()=>{
  const request=++generation;error.value=''
  try{const result=await api<Audit>(`/reviews/${props.operationId}/audit`);if(request===generation)audit.value=result}
  catch(e){if(request===generation)error.value=(e as Error).message}
},{immediate:true})
</script>
<template>
  <section><div class="section-heading"><h3>审计时间线</h3><span class="micro">只读回放 · 不会重新执行</span></div>
    <p v-if="error" class="error-banner" role="alert">{{error}}</p>
    <template v-if="audit"><p class="integrity" :class="{invalid:!audit.chain_valid}">{{audit.chain_valid?'本地事件链校验通过':'事件链不一致，请停止依赖此记录'}}<span>不等于防管理员篡改证明</span></p>
      <ol class="timeline"><li v-for="event in audit.items" :key="event.seq"><div class="timeline-title"><strong>{{names[event.type]??event.type}}</strong><time>{{timestamp(event.at)}}</time></div><details><summary>查看事件证据 #{{event.ordinal}}</summary><pre class="code-block">{{JSON.stringify(event.data,null,2)}}</pre><code class="digest">{{event.hash}}</code></details></li></ol>
      <details v-if="audit.provided_approval_view" class="evidence-details"><summary>审批时提供的完整视图快照</summary><p class="micro">记录服务端提供了什么，不证明审批者已经阅读或理解。</p><pre class="code-block">{{JSON.stringify(audit.provided_approval_view,null,2)}}</pre></details>
    </template>
  </section>
</template>
