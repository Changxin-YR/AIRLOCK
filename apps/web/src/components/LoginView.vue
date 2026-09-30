<script setup lang="ts">
import { ref } from 'vue'
import { LockKeyhole, ShieldCheck, ArrowRight } from 'lucide-vue-next'
import { useWorkbench } from '../stores/workbench'
const store = useWorkbench(), username = ref('reviewer'), password = ref('')
async function submit() { await store.login(username.value, password.value); password.value = '' }
</script>
<template>
  <main class="login-layout">
    <section class="login-story"><a class="brand" href="#"><span class="brand-mark"><ShieldCheck :size="25"/></span>AIRLOCK</a>
      <div class="story-copy"><h1>让每一次变更，<br/>都经过你的确认。</h1><p>先看清影响，再决定执行。为智能体的数据操作提供独立、可核对的审批边界。</p>
        <div class="story-flow"><span>影子预检</span><i></i><span>独立审批</span><i></i><span>一致性执行</span></div>
      </div><p class="story-foot">Agent Change Review · 个人开源工程项目</p>
    </section>
    <section class="login-form"><div class="login-icon"><LockKeyhole :size="26"/></div><h2>进入审批工作台</h2><p class="muted">审批身份与 Agent 服务身份相互独立。</p>
      <el-alert v-if="store.error" :title="store.error" type="error" :closable="false"/>
      <form @submit.prevent="submit"><label for="username">审批账号</label><el-input id="username" v-model="username" autocomplete="username" size="large"/>
        <label for="password">密码</label><el-input id="password" v-model="password" type="password" show-password autocomplete="current-password" size="large"/>
        <el-button type="primary" size="large" native-type="submit" :loading="store.busy" :disabled="!password || !username">安全登录 <ArrowRight :size="16"/></el-button>
      </form><div class="credential-hint">首次启动后的随机账号信息保存在<br/><code>.airlock/reviewer.txt</code><br/><span>请勿将审批密码提供给 Agent。</span></div>
    </section>
  </main>
</template>
