<script setup lang="ts">
import { Search, Inbox, ChevronLeft, ChevronRight, ArrowUpRight } from 'lucide-vue-next'
import { useWorkbench } from '../stores/workbench'
import { formatTime, toolLabels } from '../types'
import StatusBadge from './StatusBadge.vue'
const store = useWorkbench()
async function changePage(delta: number) { store.page += delta; await store.refresh() }
</script>
<template><section class="request-list" aria-label="变更请求列表">
  <div class="list-toolbar"><h2>变更请求 <span>{{ store.total }}</span></h2><el-select placeholder="全部状态" :model-value="store.filter" @update:model-value="store.changeFilter" aria-label="按状态筛选" style="width:130px"><el-option label="全部状态" value=""/><el-option label="等待审批" value="PENDING_APPROVAL"/><el-option label="已阻止" value="BLOCKED"/><el-option label="执行成功" value="SUCCEEDED"/><el-option label="计划已失效" value="STALE"/></el-select></div>
  <div class="list-search"><Search :size="17"/><input v-model="store.query" placeholder="搜索当前页请求或编号" aria-label="搜索请求"/></div>
  <div v-if="!store.displayed.length" class="empty-list"><Inbox :size="36"/><h3>当前没有请求</h3><p>提交一个演示任务，或连接你的 Agent。</p><el-button v-if="store.session?.demo_enabled" @click="store.tab='demo'">进入演示实验</el-button></div>
  <button v-for="op in store.displayed" :key="op.id" :class="['request-row',{active:store.selected?.operation.id===op.id}]" @click="store.select(op.id)">
    <div class="row-head"><span>{{ toolLabels[op.tool] }}</span><StatusBadge :state="op.state"/></div><h3>{{ op.intent }}</h3><p class="row-meta">{{ op.requester }} <span>·</span> {{ op.resource_id }}</p>
    <div class="row-bottom"><time>{{ formatTime(op.created_at) }}</time><span v-if="op.impact!==null">{{ op.impact }} 条变更 <ArrowUpRight :size="13"/></span><span v-else>等待预检</span></div>
  </button>
  <div class="pagination"><el-button :disabled="store.page===0" @click="changePage(-1)" aria-label="上一页"><ChevronLeft :size="16"/></el-button><span>{{ store.page+1 }} / {{ Math.max(1,Math.ceil(store.total/30)) }}</span><el-button :disabled="(store.page+1)*30>=store.total" @click="changePage(1)" aria-label="下一页"><ChevronRight :size="16"/></el-button></div>
</section></template>
