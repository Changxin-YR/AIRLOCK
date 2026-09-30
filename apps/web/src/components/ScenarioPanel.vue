<script setup lang="ts">
import { onMounted,ref } from 'vue'
import { api } from '../api'
import type { Scenario } from '../types'
const props=defineProps<{busy:string}>()
const emit=defineEmits<{submit:[id:string]}>()
const scenarios=ref<Scenario[]>([]),error=ref('')
onMounted(async()=>{try{scenarios.value=(await api<{items:Scenario[]}>('/demo/scenarios')).items}catch(e){error.value=(e as Error).message}})
const expectation=(value:string)=>({pass:'直接放行',block:'策略阻断',need_approval:'人工审批'}[value]??value)
</script>
<template>
  <section class="scenario-panel"><div class="section-heading"><h2>请求实验室</h2><span class="source-label">合成数据 · 脚本 Agent</span></div>
    <p class="section-description">选择一个真实执行场景。请求仍经过相同权限、预检与审批流程；这里没有关闭安全校验的开关。</p>
    <p class="error-banner" v-if="error">{{error}}</p>
    <div class="scenario-list"><div class="scenario-row" v-for="(item,index) in scenarios" :key="item.id"><span class="scenario-number">0{{index+1}}</span><div><h3>{{item.title}}</h3><p>{{item.description}}</p><span class="micro">初始演示数据下预期：{{expectation(item.expected)}}</span></div><button class="secondary" :disabled="!!props.busy" @click="emit('submit',item.id)">{{props.busy===item.id?'正在提交…':'提交请求'}}</button></div></div>
    <div class="note-strip"><strong>测试计划失效</strong><p>先提交一个待审批请求，再运行“单条标记更新”。前一请求的快照会失效，批准后也不会执行旧变更。</p></div>
    <p class="micro">此页不冒充真实模型对话。真实 Agent 与 MCP 客户端从独立进程接入，不能读取审批凭据。</p>
  </section>
</template>
