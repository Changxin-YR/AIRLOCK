<script setup lang="ts">
import { computed,ref,watch } from 'vue'
import type { Change } from '../types'
const props=defineProps<{changes:Change[]}>()
const page=ref(0), expanded=ref(false)
const emit=defineEmits<{opened:[]}>()
const rows=computed(()=>props.changes.slice(page.value*12,(page.value+1)*12))
watch(()=>props.changes.length,()=>{page.value=0})
const fields=(change:Change)=>Array.from(new Set([...Object.keys(change.before??{}),...Object.keys(change.after??{})])).filter(key=>key!=='project' && key!=='id' && (!change.before||!change.after||change.before[key]!==change.after[key]))
const val=(value:unknown)=>value===null||value===undefined?'∅':String(value)
function toggle() { expanded.value=!expanded.value; if(expanded.value) emit('opened') }
</script>
<template>
  <section class="diff-section">
    <div class="section-heading"><h3>变更明细 <span class="muted">{{changes.length}} 条</span></h3><button class="text-button" @click="toggle">{{expanded?'收起原始记录':'查看原始记录'}}</button></div>
    <div v-if="!changes.length" class="quiet-note">此请求不改变业务数据。读取结果将在执行回执中返回。</div>
    <div v-else class="table-scroll">
      <table class="diff-table"><thead><tr><th>记录 / 来源</th><th>字段</th><th>变更前</th><th>变更后</th></tr></thead>
        <tbody v-for="change in rows" :key="change.table+change.id">
          <tr v-for="(field,index) in fields(change)" :key="field">
            <td v-if="index===0" :rowspan="fields(change).length"><strong>{{change.table==='customers'?'客户':'客户备注'}} #{{change.id}}</strong><span class="cell-caption">{{change.origin==='direct'?'直接变更':'外键级联'}} · {{change.kind==='delete'?'删除':change.kind==='insert'?'新增':'更新'}}</span></td>
            <td class="mono">{{field}}</td><td class="before-value">{{val(change.before?.[field])}}</td><td :class="{'after-value':change.after,'deleted-value':!change.after}">{{change.after?val(change.after[field]):'删除'}}</td>
          </tr>
          <tr v-if="expanded"><td colspan="4"><pre class="code-block">{{JSON.stringify(change,null,2)}}</pre></td></tr>
        </tbody>
      </table>
    </div>
    <div v-if="changes.length>12" class="pagination"><button :disabled="page===0" @click="page--">上一页</button><span>{{page+1}} / {{Math.ceil(changes.length/12)}} · 完整影响未截断</span><button :disabled="(page+1)*12>=changes.length" @click="page++">下一页</button></div>
  </section>
</template>
