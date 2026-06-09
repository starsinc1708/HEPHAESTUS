<script setup lang="ts">
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWorkspaceStore } from '@/stores/workspace'

const { t } = useI18n()
const ws = useWorkspaceStore()
onMounted(() => ws.fetchWorkspaces())

async function onChange(e: Event) {
  const id = (e.target as HTMLSelectElement).value
  if (id) await ws.activate(id)
}
</script>

<template>
  <select :value="ws.activeId ?? ''" @change="onChange" class="ws-switch">
    <option value="" disabled>{{ t('shell.workspacePlaceholder') }}</option>
    <option v-for="w in ws.workspaces" :key="w.id" :value="w.id">{{ w.name }}</option>
  </select>
</template>
