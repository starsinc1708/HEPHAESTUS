<script setup lang="ts">
import { ref, computed, watch, onMounted, provide } from 'vue'
import { useI18n } from 'vue-i18n'
import type { DirEntry } from '@/types/api'
import { api } from '@/api/client'
import ScopeNode from './ScopeNode.vue'

const { t } = useI18n()
const props = defineProps<{ wsId: string; modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [string] }>()

const roots = ref<DirEntry[]>([])
const loading = ref(false)
const error = ref('')

function parse(s: string): string[] {
  return Array.from(new Set(s.split(/\s+/).map(x => x.trim()).filter(Boolean)))
}
// Selection is derived from the bound scope string — single source of truth, no internal
// copy to keep in sync (raw-text edits in the parent flow straight back into the tree).
const selected = computed(() => parse(props.modelValue))

function emitSel(arr: string[]) {
  emit('update:modelValue', Array.from(new Set(arr)).sort().join(' '))
}
function toggle(path: string) {
  const cur = selected.value
  if (cur.includes(path)) {
    emitSel(cur.filter(p => p !== path))
  } else {
    // checking a dir subsumes any already-selected descendants — drop them
    emitSel([...cur.filter(p => !p.startsWith(path + '/')), path])
  }
}

provide('scopeCtx', {
  isSelected: (p: string) => selected.value.includes(p),
  isCovered: (p: string) => selected.value.some(s => s !== p && p.startsWith(s + '/')),
  toggle,
  loadChildren: (path: string) => api.listWorkspaceDirs(props.wsId, path),
})

async function loadRoots() {
  if (!props.wsId) { roots.value = []; return }
  loading.value = true
  error.value = ''
  try {
    roots.value = (await api.listWorkspaceDirs(props.wsId)).dirs
  } catch {
    error.value = t('tools.scopePicker.loadError')
  } finally {
    loading.value = false
  }
}
onMounted(loadRoots)
watch(() => props.wsId, loadRoots)
</script>

<template>
  <div class="scope-picker">
    <div v-if="loading" class="muted small">{{ t('tools.scopePicker.loading') }}</div>
    <div v-else-if="error" class="err small">{{ error }}</div>
    <ul v-else class="tree">
      <ScopeNode v-for="d in roots" :key="d.path" :node="d" />
      <li v-if="!roots.length" class="muted small">{{ t('tools.scopePicker.empty') }}</li>
    </ul>
  </div>
</template>

<style scoped>
.scope-picker {
  background: var(--panel-2); border: 1px solid var(--border);
  border-radius: 6px; padding: 6px 8px; max-height: 260px; overflow: auto;
}
.tree { margin: 0; padding: 0; list-style: none; }
.muted { color: var(--muted); }
.err { color: var(--rose); }
.small { font-size: 11px; }
</style>
