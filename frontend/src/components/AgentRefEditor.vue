<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { AgentRef } from '@/types/api'

const props = defineProps<{ modelValue: AgentRef; useModels: boolean; label?: string; modelOnly?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [AgentRef] }>()
const { t } = useI18n()

// Known providers — shown as a dropdown (datalist) while still allowing a custom value,
// since opencode also supports custom/self-hosted providers.
const PROVIDERS = ['anthropic', 'openai', 'deepseek', 'google', 'openrouter', 'groq', 'xai', 'mistral', 'ollama', 'azure', 'bedrock']

function update(patch: Partial<AgentRef>) {
  emit('update:modelValue', { ...props.modelValue, ...patch })
}
function onInput(e: Event, patch: (v: string) => Partial<AgentRef>) {
  update(patch((e.target as HTMLInputElement).value))
}
</script>

<template>
  <div class="agent-ref" data-test="agent-ref">
    <span v-if="label" class="ar-label">{{ label }}</span>
    <template v-if="modelOnly">
      <input
        class="ar-input ar-model" :value="modelValue.model" :placeholder="t('agents.refEditor.placeholderModelOnly')"
        data-test="ar-model" @input="onInput($event, (v) => ({ model: v }))"
      />
    </template>
    <template v-else-if="useModels">
      <input
        class="ar-input" :value="modelValue.provider" :placeholder="t('agents.refEditor.placeholderProvider')"
        list="ar-providers" data-test="ar-provider" @input="onInput($event, (v) => ({ provider: v }))"
      />
      <datalist id="ar-providers">
        <option v-for="p in PROVIDERS" :key="p" :value="p" />
      </datalist>
      <span class="ar-sep">/</span>
      <input
        class="ar-input ar-model" :value="modelValue.model" :placeholder="t('agents.refEditor.placeholderModel')"
        data-test="ar-model" @input="onInput($event, (v) => ({ model: v }))"
      />
    </template>
    <template v-else>
      <input
        class="ar-input ar-agent" :value="modelValue.agent ?? ''" :placeholder="t('agents.refEditor.placeholderAgent')"
        data-test="ar-agent" @input="onInput($event, (v) => ({ agent: v }))"
      />
    </template>
  </div>
</template>

<style scoped>
.agent-ref { display: flex; align-items: center; gap: 6px; flex: 1; min-width: 0; }
.ar-label { font-family: var(--mono); font-size: 11px; color: var(--muted); min-width: 90px; }
.ar-input {
  background: var(--panel-2); border: 1px solid var(--border); border-radius: 4px;
  color: var(--text); font-family: var(--mono); font-size: 12px; padding: 5px 8px;
  outline: none; transition: border-color 0.15s; min-width: 0; flex: 1;
}
.ar-input:focus { border-color: var(--primary); }
.ar-sep { color: var(--muted); }
</style>
