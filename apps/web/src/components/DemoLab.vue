<script setup lang="ts">
import { Play, Database, ShieldBan, FileCheck2, ListFilter, ArrowRight } from 'lucide-vue-next'
import { useWorkbench } from '../stores/workbench'
const store=useWorkbench()
const scenarios=[{id:'review',icon:FileCheck2,title:'合法变更，等待你审批',desc:'给 6 条过期测试客户更新标签。预检展示真实差异，只有独立审批后才会写入。',path:'预检 → 人工审批 → 执行回执',label:'创建待审批请求'},
{id:'blocked',icon:ShieldBan,title:'阻止范围过大的删除',desc:'模拟 Agent 请求清空全部客户。记录真实影响，但禁止规则不能被审批覆盖。',path:'预检 → 策略阻止 → 数据不变',label:'运行阻断场景'},
{id:'delete',icon:Database,title:'看清关联记录的变化',desc:'删除 6 条过期测试客户，关联备注也会级联删除。预览不仅仅显示直接影响行数。',path:'直接变更 + 级联变更 → 逐项确认',label:'检查级联删除'},
{id:'read',icon:ListFilter,title:'让低风险读取正常通过',desc:'读取授权字段，不返回邮箱，不增加不必要的人工确认。结果来自真实演示数据库。',path:'身份与字段校验 → 直接返回',label:'运行只读请求'}]
</script>
<template><section class="demo-lab"><div class="page-intro"><h2>用真实操作，验证安全边界。</h2><p>这些是明确标注的合成场景。所有演示均经过同一后端规则，没有关闭审批或绕过执行器的开关。</p></div><div class="demo-notice"><Database :size="18"/><span>当前资源：demo · SQLite · 初始 1,206 条客户 + 24 条备注。实际数量会随已批准操作变化。</span></div><article v-for="(scenario,index) in scenarios" :key="scenario.id" class="scenario-row"><span class="scenario-number">0{{index+1}}</span><component :is="scenario.icon" :size="26"/><div><h3>{{scenario.title}}</h3><p>{{scenario.desc}}</p><small>{{scenario.path}}</small></div><el-button :disabled="!store.session?.demo_enabled" :loading="store.busy" @click="store.demo(scenario.id)">{{scenario.label}}<ArrowRight :size="15"/></el-button></article><div class="demo-bottom"><h3>数据漂移与崩溃恢复</h3><p>这两类场景由自动化测试在一次性环境中注入故障，不在公开界面加入篡改数据或杀进程的后门。</p><code>python -m pytest tests/test_process_recovery.py -v</code></div></section></template>
