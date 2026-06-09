<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { AgentRef } from '@/types/api'
import AgentRefEditor from './AgentRefEditor.vue'

const props = defineProps<{ modelValue: AgentRef[]; useModels: boolean; lensNames?: string[]; modelOnly?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [AgentRef[]] }>()
const { t } = useI18n()

function updateAt(i: number, ref: AgentRef) {
  const next = props.modelValue.slice()
  next[i] = ref
  emit('update:modelValue', next)
}
function add() {
  const base: AgentRef = props.modelValue[0]
    ? { ...props.modelValue[0] }
    : { provider: 'anthropic', model: 'claude-opus-4-8', agent: null }
  emit('update:modelValue', [...props.modelValue, base])
}
function remove(i: number) {
  emit('update:modelValue', props.modelValue.filter((_, idx) => idx !== i))
}
function fillAll() {
  const first = props.modelValue[0]
  if (!first) return
  emit('update:modelValue', props.modelValue.map(() => ({ ...first })))
}
</script>

<template>
  <div class="agent-list" data-test="agent-list">
    <div v-for="(ref, i) in modelValue" :key="i" class="al-row">
      <span class="al-idx">{{ lensNames?.[i] ?? `#${i + 1}` }}</span>
      <AgentRefEditor
        :model-value="ref" :use-models="useModels" :model-only="modelOnly"
        @update:model-value="updateAt(i, $event)"
      />
      <button class="al-btn al-remove" data-test="al-remove" :title="t('agents.listEditor.remove')" @click="remove(i)">✕</button>
    </div>
    <div class="al-actions">
      <button class="al-btn" data-test="al-add" @click="add">{{ t('agents.listEditor.addRow') }}</button>
      <button v-if="modelValue.length > 1" class="al-btn" data-test="al-fill" @click="fillAll">
        {{ t('agents.listEditor.fillAll') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.agent-list { display: flex; flex-direction: column; gap: 6px; }
.al-row { display: flex; align-items: center; gap: 8px; }
.al-idx { font-family: var(--mono); font-size: 11px; color: var(--muted); min-width: 92px; }
.al-actions { display: flex; gap: 8px; margin-top: 2px; }
.al-btn {
  background: var(--panel-2); border: 1px solid var(--border); border-radius: 4px;
  color: var(--text); font-size: 11px; padding: 4px 8px; cursor: pointer;
}
.al-btn:hover { border-color: var(--primary); }
.al-remove { color: var(--rose); border-color: transparent; padding: 4px 6px; }
</style>
