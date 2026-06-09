<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import { useWorkspaceStore } from '@/stores/workspace'
import { useToastStore } from '@/stores/toast'
import HelpHint from '@/components/HelpHint.vue'
import type { PromptSummary, WsPromptDetail } from '@/types/api'

const ws = useWorkspaceStore()
const toast = useToastStore()
const { t } = useI18n()

const list = ref<PromptSummary[]>([])
const selected = ref<string | null>(null)
const detail = ref<WsPromptDetail | null>(null)
const buf = ref('')
const busy = ref(false)

const dirty = computed(() => detail.value !== null && buf.value !== detail.value.content)
// Build the "{{var}}" display in script — a literal {{ in a template expression
// would be misparsed by the Vue compiler as an interpolation delimiter.
const varsDisplay = computed(() => (detail.value?.variables ?? []).map(v => '{{' + v + '}}').join(' '))

async function loadList() {
  if (!ws.activeId) return
  const res = await api.listWsPrompts(ws.activeId)
  list.value = res.prompts
}
async function select(name: string) {
  if (!ws.activeId) return
  selected.value = name
  const d = await api.getWsPrompt(ws.activeId, name)
  detail.value = d
  buf.value = d.content
}
async function save() {
  if (!ws.activeId || !selected.value) return
  busy.value = true
  try {
    const d = await api.putWsPrompt(ws.activeId, selected.value, buf.value)
    detail.value = d
    buf.value = d.content
    toast.add('success', t('agents.prompts.saved', { name: selected.value }))
    await loadList()
  } catch (e: unknown) {
    toast.add('error', e instanceof Error ? e.message : String(e))
  } finally { busy.value = false }
}
async function reset() {
  if (!ws.activeId || !selected.value) return
  busy.value = true
  try {
    const d = await api.resetWsPrompt(ws.activeId, selected.value)
    detail.value = d
    buf.value = d.content
    toast.add('success', t('agents.prompts.resetToGlobal', { name: selected.value }))
    await loadList()
  } catch (e: unknown) {
    toast.add('error', e instanceof Error ? e.message : String(e))
  } finally { busy.value = false }
}

onMounted(async () => { await ws.fetchWorkspaces(); await loadList() })
</script>

<template>
  <div class="prompts" v-if="ws.activeId">
    <aside class="list">
      <h3>{{ t('agents.prompts.title') }} <HelpHint :text="t('agents.prompts.helpHint')" /></h3>
      <ul>
        <li v-for="p in list" :key="p.name" :class="{ active: p.name === selected }" data-test="prompt-item" @click="select(p.name)">
          <span class="mono">{{ p.name }}</span>
          <span v-if="p.overridden" class="badge" data-test="overridden-badge">override</span>
        </li>
        <li v-if="!list.length" class="muted">{{ t('agents.prompts.noTemplates') }}</li>
      </ul>
    </aside>

    <main v-if="detail" class="editor">
      <div class="ed-head">
        <b class="mono">{{ selected }}</b>
        <span v-if="detail.overridden" class="badge">{{ t('agents.prompts.overriddenForRepo') }}</span>
        <span v-else class="muted small">{{ t('agents.prompts.globalTemplate') }}</span>
        <span v-if="detail.variables.length" class="vars">{{ t('agents.prompts.variables') }} <code>{{ varsDisplay }}</code></span>
      </div>
      <textarea class="ta mono" v-model="buf" spellcheck="false" data-test="prompt-textarea"></textarea>
      <div class="ed-actions">
        <button class="btn btn-primary" :disabled="busy || !dirty" data-test="save-prompt" @click="save">{{ t('agents.prompts.saveForRepo') }}</button>
        <button class="btn" :disabled="busy || !detail.overridden" data-test="reset-prompt" @click="reset">{{ t('agents.prompts.resetBtn') }}</button>
        <span v-if="dirty" class="muted small">{{ t('agents.prompts.unsavedChanges') }}</span>
      </div>
    </main>
    <main v-else class="editor empty muted">{{ t('agents.prompts.selectToEdit') }}</main>
  </div>
  <div v-else class="empty-state muted">
    {{ t('agents.prompts.noActiveRepoPrefix') }} <router-link to="/settings">{{ t('agents.prompts.settingsLink') }}</router-link>.
  </div>
</template>

<style scoped>
.prompts { display: grid; grid-template-columns: 240px 1fr; gap: 16px; height: 100%; }
.list h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin: 0 0 10px; }
.list ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 2px; }
.list li { display: flex; align-items: center; justify-content: space-between; gap: 6px; padding: 6px 8px; border-radius: 4px; cursor: pointer; font-size: 12px; }
.list li:hover { background: var(--panel-2); }
.list li.active { background: var(--panel-3); border: 1px solid var(--primary); }
.badge { font-size: 9px; text-transform: uppercase; color: var(--on-primary); background: var(--amber); border-radius: 3px; padding: 1px 5px; }
.editor { display: flex; flex-direction: column; gap: 10px; min-height: 0; }
.editor.empty { align-items: center; justify-content: center; }
.ed-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.vars { font-size: 11px; color: var(--muted); }
.ta { flex: 1; min-height: 320px; background: var(--panel-2); border: 1px solid var(--border); border-radius: 6px; color: var(--text); font-size: 12.5px; line-height: 1.5; padding: 12px; outline: none; resize: vertical; }
.ta:focus { border-color: var(--primary); }
.ed-actions { display: flex; align-items: center; gap: 10px; }
.btn { background: var(--panel-2); border: 1px solid var(--border); border-radius: 4px; color: var(--text); font-size: 12px; padding: 6px 12px; cursor: pointer; }
.btn:hover { border-color: var(--primary); }
.btn-primary { background: var(--primary); color: var(--on-primary); border-color: var(--primary); font-weight: 600; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.small { font-size: 11px; }
.empty-state { padding: 24px; }
</style>
