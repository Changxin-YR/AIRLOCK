<script setup lang="ts">
import { stateNames, type State } from '../types'
defineProps<{state:State}>()
</script>
<template><span class="status" :class="'status-'+state"><span class="status-dot"></span>{{stateNames[state]}}</span></template>
