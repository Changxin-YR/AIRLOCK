<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount } from 'vue'
import { ShieldCheck, LayoutDashboard, History, FlaskConical, Info, LogOut, RefreshCw, ArrowUpRight, LockKeyhole, Activity, ShieldBan, CheckCheck, Timer } from 'lucide-vue-next'
import { useWorkbench } from './stores/workbench'
import LoginView from './components/LoginView.vue'
import OperationList from './components/OperationList.vue'
import ReviewDetail from './components/ReviewDetail.vue'
import DemoLab from './components/DemoLab.vue'
const store=useWorkbench()
const tabs=[{id:'reviews',label:'审批工作台',icon:LayoutDashboard},{id:'history',label:'审计记录',icon:History},{id:'demo',label:'演示实验',icon:FlaskConical},{id:'about',label:'项目边界',icon:Info}]
const title=computed(()=>tabs.find(t=>t.id===store.tab)?.label)
const count=(state:string)=>store.metrics?.states[state]??0
onMounted(()=>store.check());onBeforeUnmount(()=>store.stop())
function navigate(id:string){store.tab=id;if(id==='history')void store.changeFilter(''); if(store.selected)void store.select(store.selected.operation.id);}
</script>
<template><div v-if="!store.checked" class="boot-state"><ShieldCheck :size="40"/><p>正在连接审批服务…</p></div><LoginView v-else-if="!store.session"/>
<div v-else class="app-shell"><aside class="sidebar"><a class="brand" href="#" @click.prevent="navigate('reviews')"><span class="brand-mark"><ShieldCheck :size="25"/></span>AIRLOCK</a><span class="brand-subtitle">Agent Change Review</span><nav aria-label="主导航"><button v-for="item in tabs" :key="item.id" :class="{active:store.tab===item.id}" @click="navigate(item.id)"><component :is="item.icon" :size="19"/>{{item.label}}<span v-if="item.id==='reviews'&&count('PENDING_APPROVAL')" class="nav-count">{{count('PENDING_APPROVAL')}}</span></button></nav><div class="sidebar-bottom"><div class="boundary-note"><LockKeyhole :size="18"/><strong>执行权在服务端</strong><p>Agent 可以提议，<br/>不能代替你批准。</p></div><button class="user-button" aria-label="退出登录" @click="store.logout"><span class="avatar">R</span><span>{{store.session.username}}<small>独立审批身份</small></span><LogOut :size="16"/></button></div></aside>
<main class="main-surface"><header class="topbar"><div class="breadcrumb">个人工作空间 <span>/</span> {{title}}</div><div class="topbar-right"><span :class="['connection',{offline:!store.connected}]"><i></i>{{store.connected?'事件已连接':'重连中 · 查询可用'}}</span><span class="environment">演示环境</span></div></header><div class="workspace"><div class="workspace-heading"><div><h1>{{title}}</h1><p>{{store.tab==='reviews'?'看清影响范围，批准确定的变更。':store.tab==='history'?'回看当时提供的证据与已经发生的执行。':store.tab==='demo'?'每个场景都运行在真实、隔离的演示数据上。':'只承诺已经实现和验证的能力。'}}</p></div><div class="header-actions"><el-button @click="store.refresh" aria-label="刷新请求"><RefreshCw :size="16"/>刷新</el-button><el-button v-if="store.tab!=='demo' && store.session.demo_enabled" type="primary" @click="store.tab='demo'">新建演示请求<ArrowUpRight :size="16"/></el-button></div></div>
<el-alert v-if="store.error" :title="store.error" type="error" show-icon @close="store.error=''"/>
<template v-if="store.tab==='reviews'||store.tab==='history'"><section class="metrics-strip" aria-label="实时请求统计"><div><span><Timer :size="17"/>等待审批</span><strong>{{count('PENDING_APPROVAL')}}<small>项需要你处理</small></strong></div><div><span><ShieldBan :size="17"/>已阻止 / 已拒绝</span><strong>{{count('BLOCKED')+count('REJECTED')}}<small>项未执行</small></strong></div><div><span><CheckCheck :size="17"/>执行成功</span><strong>{{count('SUCCEEDED')}}<small>份目标回执</small></strong></div><div><span><Activity :size="17"/>审计事件</span><strong>{{store.metrics?.audit_events??0}}<small>条持久化记录</small></strong></div></section><div class="review-layout"><OperationList/><ReviewDetail :read-only="store.tab==='history'" :key="store.selected?.operation.id??'empty'"/></div></template>
<DemoLab v-else-if="store.tab==='demo'"/>
<section v-else class="about-page"><h2>一个范围明确、证据可核对的个人项目。</h2><p>AIRLOCK 保护结构化 SQLite 工具调用，聚焦预检、审批与执行一致性。不是通用 SQL 防火墙，也不宣称首创人工审批。</p><div class="about-columns"><article><h3>已经实现的边界</h3><p>授权字段查询、更新与删除；一致性影子快照；直接与级联 diff；独立审批账号；计划摘要、期限、权限和目标状态复核；事务回执与故障对账。</p></article><article><h3>明确不提供的能力</h3><p>任意 SQL / Shell、任意数据库连接、多租户组织权限、自动学习放行、通用工具回滚、对宿主机管理员或失陷浏览器的保护。</p></article></div><div class="evidence-note"><h3>验证信息</h3><p>界面统计来自本次运行，不是安全评测成绩。真实模型调用需要配置模型服务凭据；未配置时不产生模型性能结论。未开展真实用户实验。</p><p>审计回放只读；摘要链可检查记录一致性，但不是防管理员篡改的合规认证。</p></div><p class="fineprint">品牌用于本个人仓库展示，不与其他同名项目构成关联。</p></section>
<footer class="workspace-footer"><span>AIRLOCK · 个人项目 / v0.1.0</span><span>知情审批，不止一个确认按钮。</span></footer></div></main></div></template>
