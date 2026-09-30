<script setup lang="ts">
import { computed,onBeforeUnmount,onMounted,ref } from 'vue'
import { ElMessage } from 'element-plus/es/components/message/index'
import { useWorkbench } from './store'
import { stateNames,timestamp,toolNames } from './types'
import StatusBadge from './components/StatusBadge.vue'
import ReviewDetail from './components/ReviewDetail.vue'
import ScenarioPanel from './components/ScenarioPanel.vue'
const store=useWorkbench()
const starting=ref(true),username=ref('reviewer'),password=ref(''),loginBusy=ref(false),loginError=ref('')
const page=ref('workbench'),scenarioBusy=ref('')
const pending=computed(()=>store.states.PENDING_APPROVAL??0)
const blocked=computed(()=>store.states.BLOCKED??0)
const total=computed(()=>Object.values(store.states).reduce((sum,value)=>sum+(value??0),0))
const filters=[['','全部请求'],['PENDING_APPROVAL','等待审批'],['SUCCEEDED','已执行'],['BLOCKED','已阻断']]
onMounted(async()=>{await store.restore();starting.value=false})
onBeforeUnmount(()=>store.stop())
async function login() {
  loginBusy.value=true;loginError.value=''
  try {await store.login(username.value,password.value);password.value=''}
  catch(e){loginError.value=(e as Error).message}
  finally{loginBusy.value=false}
}
async function logout() {try{await store.logout()}catch(e){ElMessage.error((e as Error).message)}}
async function propose(id:string) {
  scenarioBusy.value=id
  try {await store.propose(id);page.value='workbench';await store.changeFilter('');ElMessage.info('请求已提交，预检结果由后端生成。')}
  catch(e){ElMessage.error((e as Error).message)}finally{scenarioBusy.value=''}
}
</script>
<template>
  <div v-if="starting" class="boot-screen"><div class="brand-symbol">A</div><p>正在连接审批工作台…</p></div>
  <main v-else-if="!store.session" class="login-screen">
    <section class="login-story"><div class="wordmark"><span class="brand-symbol">A</span>AIRLOCK</div><div class="login-copy"><p class="micro">AGENT CHANGE REVIEW</p><h1>让每一次批准，<br>都有事实依据。</h1><p>先看清变更，再决定执行。<br>把模型的提议，交给独立的审批边界。</p><div class="trust-steps"><span>01 影子预检</span><span>02 人工审批</span><span>03 事务回执</span></div></div><p class="login-footnote">个人工程作品 · 受控 SQLite 场景 · 不承诺通用工具安全</p></section>
    <section class="login-form-wrap"><form class="login-form" @submit.prevent="login"><span class="source-label">独立的人类审批会话</span><h2>登录审批工作台</h2><p>使用初始化时生成的审批账号。Agent Token 不能在这里登录或批准请求。</p><label for="username">审批账号</label><input id="username" v-model="username" autocomplete="username" maxlength="80" required><label for="password">密码</label><input id="password" v-model="password" type="password" autocomplete="current-password" maxlength="200" required><p v-if="loginError" class="error-banner" role="alert">{{loginError}}</p><button class="primary login-submit" :disabled="loginBusy">{{loginBusy?'正在验证…':'进入工作台'}}</button><div class="credential-help">首次启动？在本机查看 <code>runtime/human/credentials.json</code>。请勿将该文件提交至仓库或提供给 Agent。</div></form></section>
  </main>
  <div v-else class="app-shell">
    <aside class="sidebar"><div class="wordmark"><span class="brand-symbol">A</span><div>AIRLOCK<small>Agent Change Review</small></div></div>
      <div class="workspace-label">个人工作空间<span>DEMO / CRM</span></div>
      <nav aria-label="主要导航"><button :class="{active:page==='workbench'}" @click="page='workbench'"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="M4 10h16M10 10v10"/></svg>审批工作台<span class="nav-count" v-if="pending">{{pending}}</span></button><button v-if="store.demoEnabled" :class="{active:page==='lab'}" @click="page='lab'"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M9 3h6M10 3v7l-5 8a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-8V3M8 15h8"/></svg>请求实验室</button></nav>
      <div class="sidebar-boundary"><span class="boundary-line"></span><strong>服务端掌握执行权</strong><p>模型提出请求。<br>批准绑定计划。<br>回执确认结果。</p></div>
      <div class="sidebar-user"><div class="avatar">{{store.session.username.slice(0,1).toUpperCase()}}</div><div><strong>{{store.session.username}}</strong><span>人工审批者 · {{store.session.scope}}</span></div><button class="logout" @click="logout" aria-label="退出登录" title="退出登录">↗</button></div>
    </aside>
    <main class="workspace"><header class="topbar"><div class="breadcrumb">工作空间 <span>/</span> {{page==='lab'?'请求实验室':'审批工作台'}}</div><div class="topbar-right"><span class="connection" :class="{online:store.connected}"><i></i>{{store.connected?'事件流已连接':'自动重连 · 轮询恢复'}}</span><button class="secondary compact" @click="store.refresh()">刷新状态</button><button class="secondary compact mobile-logout" @click="logout" aria-label="退出登录">退出</button></div></header>
      <div class="workspace-content"><div class="page-title"><div><h1>{{page==='lab'?'把边界，放进真实流程。':'变更审批'}}</h1><p>{{page==='lab'?'从可复现请求检查放行、审批和阻断三条路径。':'看清影响，批准当前计划，核对最终回执。'}}</p></div><button v-if="store.demoEnabled&&page==='workbench'" class="primary" @click="page='lab'">发起演示请求 <span aria-hidden="true">＋</span></button></div>
        <p v-if="store.error" class="error-banner" role="alert">{{store.error}}</p>
        <ScenarioPanel v-if="page==='lab'" :busy="scenarioBusy" @submit="propose"/>
        <template v-else><div class="metrics-strip"><div><span>等待人工审批</span><strong>{{pending}}<small>项</small></strong></div><div><span>已确认执行成功</span><strong>{{store.states.SUCCEEDED??0}}<small>项</small></strong></div><div><span>被策略阻断</span><strong>{{blocked}}<small>项</small></strong></div><div class="metrics-source"><span>当前工作空间</span><strong>{{total}}<small>个真实请求</small></strong></div></div>
          <div class="review-layout" :class="{'has-selection':!!store.selected}"><section class="request-panel" aria-label="请求队列"><div class="queue-heading"><h2>请求队列</h2><span class="micro">{{store.total}} 项</span></div><div class="queue-filters" role="tablist"><button v-for="[value,label] in filters" :key="value" role="tab" :aria-selected="store.filter===value" :class="{active:store.filter===value}" @click="store.changeFilter(value!)">{{label}}</button></div>
            <div v-if="!store.items.length" class="empty-queue"><span class="empty-glyph">∅</span><h3>{{store.filter?'此筛选下没有请求':'还没有工具请求'}}</h3><p>新的工具调用会出现在这里。可从请求实验室开始。</p><button v-if="store.demoEnabled" class="text-button" @click="page='lab'">打开请求实验室 →</button></div>
            <div class="request-list"><button v-for="op in store.items" :key="op.id" class="request-item" :class="{selected:store.selected?.id===op.id}" :aria-pressed="store.selected?.id===op.id" @click="store.select(op.id)"><div class="request-meta"><span class="mono">{{op.id.slice(0,8).toUpperCase()}}</span><time>{{timestamp(op.created_at)}}</time></div><strong class="request-title">{{op.task||toolNames[op.tool]}}</strong><div class="request-resource">{{op.resource_id}}<span>· {{toolNames[op.tool]}}</span></div><div class="request-bottom"><StatusBadge :state="op.state"/><span class="change-count" v-if="op.summary">{{op.summary.total_changed}} 条变更</span></div></button></div>
            <div class="pagination" v-if="store.total>20"><button :disabled="store.offset===0" @click="store.page(-1)">上一页</button><span>{{Math.floor(store.offset/20)+1}} / {{Math.ceil(store.total/20)}}</span><button :disabled="store.offset+20>=store.total" @click="store.page(1)">下一页</button></div>
          </section>
          <section class="detail-panel" :aria-busy="store.busy"><div v-if="store.busy" class="detail-loading" role="status">正在读取审批证据…</div><ReviewDetail v-if="store.selected" :key="store.selected.id" :operation="store.selected" @changed="store.refresh()"/><div v-else class="welcome-panel"><div class="preview-motif" aria-hidden="true"><span></span><span></span><span></span></div><h2>从一份具体变更开始</h2><p>选择左侧请求，查看字段前后差异、直接与级联影响，以及审批时绑定的证据。</p><div class="welcome-principles"><span>预检不写真实库</span><span>旧计划不能复用</span><span>重试核对原回执</span></div></div></section>
          </div>
        </template>
        <footer class="workspace-footer"><span>AIRLOCK · 个人开源工程作品</span><span>事实预检 ≠ 模型猜测 · 审批 ≠ 执行成功</span></footer>
      </div>
    </main>
  </div>
</template>
