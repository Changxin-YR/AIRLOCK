<script setup lang="ts">
import { stateLabels } from '../types'
defineProps<{ state: string }>()
</script>
<template><span :class="['status-badge', state.toLowerCase()]"><i></i>{{ stateLabels[state] ?? state }}</span></template>
