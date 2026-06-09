<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Idea } from '@/types/api'
import { api } from '@/api/client'
import { useToastStore } from '@/stores/toast'
import { useAgentJob } from '@/composables/useAgentJob'
import LiveConsole from '@/components/LiveConsole.vue'

const { t } = useI18n()
const toast = useToastStore()

const ideas = ref<Idea[]>([])
const importing = ref(false)
const selected = ref<Set<string>>(new Set())
const categoriesInput = ref('')

const job = useAgentJob()
const loading = computed(() => job.status.value === 'running')

async function fetchIdeas() {
  try {
    const res = await api.listIdeas()
    if (res.ok) ideas.value = res.ideas
  } catch (e: unknown) {
    toast.add('error', t('tools.ideasPanel.loadError', { error: e instanceof Error ? e.message : String(e) }))
  }
}

async function generateIdeas() {
  const cats = categoriesInput.value.trim()
    ? categoriesInput.value.split(',').map(s => s.trim()).filter(Boolean)
    : undefined

  await job.run(() => api.generateIdeas(cats))

  if (job.status.value === 'done' && job.result.value) {
    const fetchedIdeas: Idea[] = job.result.value.ideas ?? []
    ideas.value = fetchedIdeas
    selected.value = new Set()
    toast.add('success', t('tools.ideasPanel.generated', { count: fetchedIdeas.length }))
  } else if (job.status.value === 'failed') {
    toast.add('error', t('tools.ideasPanel.genError', { error: job.error.value ?? '' }))
  }
}

function toggleSelect(id: string) {
  const s = new Set(selected.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  selected.value = s
}

async function importSelected() {
  if (selected.value.size === 0) {
    toast.add('warn', t('tools.ideasPanel.selectWarning'))
    return
  }
  importing.value = true
  try {
    const res = await api.importIdeas([...selected.value])
    if (res.ok) {
      toast.add('success', t('tools.ideasPanel.imported', { count: res.added }))
      selected.value = new Set()
    } else {
      toast.add('error', t('tools.ideasPanel.importError'))
    }
  } catch (e: unknown) {
    toast.add('error', t('tools.error', { error: e instanceof Error ? e.message : String(e) }))
  } finally {
    importing.value = false
  }
}

onMounted(() => { void fetchIdeas() })
</script>

<template>
  <div class="ideas-panel">
    <!-- Controls -->
    <div class="ideas-controls">
      <input
        v-model="categoriesInput"
        type="text"
        class="form-input"
        :placeholder="t('tools.ideasPanel.categoriesPlaceholder')"
      />
      <button
        class="btn btn-primary"
        data-test="gen-ideas"
        :disabled="loading"
        @click="generateIdeas"
      >
        <span v-if="loading" class="btn-spinner" />
        {{ loading ? t('tools.ideasPanel.generating') : t('tools.ideasPanel.generateBtn') }}
      </button>
      <button
        class="btn btn-secondary"
        data-test="ideas-import"
        :disabled="importing || selected.size === 0"
        @click="importSelected"
      >
        <span v-if="importing" class="btn-spinner" />
        {{ importing ? t('tools.ideasPanel.importing') : t('tools.ideasPanel.importBtn', { count: selected.size }) }}
      </button>
    </div>

    <!-- Live progress stream while job is running -->
    <div v-if="loading && job.streamUrl.value" class="ideas-stream">
      <LiveConsole
        :iter-dir="null"
        :active="true"
        :stream-url="job.streamUrl.value"
      />
    </div>

    <!-- Idea cards -->
    <div v-if="ideas.length === 0 && !loading" class="ideas-empty">
      {{ t('tools.ideasPanel.empty') }}
    </div>
    <div class="ideas-list">
      <div
        v-for="idea in ideas"
        :key="idea.id"
        class="idea-card"
        :class="{ selected: selected.has(idea.id) }"
        data-test="idea-card"
        @click="toggleSelect(idea.id)"
      >
        <div class="idea-header">
          <input
            type="checkbox"
            :data-test="'import-select-' + idea.id"
            :checked="selected.has(idea.id)"
            @click.stop="toggleSelect(idea.id)"
          />
          <span class="idea-title">{{ idea.title }}</span>
          <span class="badge badge-category">{{ idea.category }}</span>
          <span class="badge badge-severity" :class="'sev-' + idea.severity">{{ idea.severity }}</span>
          <span v-if="idea.imported" class="badge badge-imported">imported</span>
        </div>
        <p class="idea-proposal">{{ idea.proposal }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ideas-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ideas-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.form-input {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-family: var(--mono);
  font-size: 12px;
  padding: 6px 10px;
  outline: none;
  transition: border-color 0.15s;
  flex: 1;
  min-width: 180px;
}
.form-input:focus { border-color: var(--primary); }

.btn {
  font-family: var(--mono);
  font-size: 12px;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 6px 14px;
  cursor: pointer;
  background: var(--panel-2);
  color: var(--text);
  transition: background 0.12s, opacity 0.12s;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.btn:hover:not(:disabled) { background: var(--panel-3, var(--panel)); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { border-color: var(--primary); color: var(--primary); }
.btn-secondary { border-color: var(--blue, #4aa3ff); color: var(--blue, #4aa3ff); }

.btn-spinner {
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 1.5px solid var(--border);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.ideas-stream {
  margin-bottom: 4px;
}

.ideas-empty {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--muted);
  padding: 8px 0;
}

.ideas-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.idea-card {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px 12px;
  cursor: pointer;
  transition: border-color 0.12s, background 0.12s;
}
.idea-card:hover { border-color: var(--primary); }
.idea-card.selected {
  border-color: var(--primary);
  background: color-mix(in srgb, var(--primary) 8%, var(--panel-2));
}

.idea-header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.idea-title {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text);
  font-weight: 600;
  flex: 1;
  min-width: 0;
}

.badge {
  font-family: var(--mono);
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 3px;
  border: 1px solid var(--border);
  background: var(--panel-3, var(--panel));
  color: var(--muted);
  flex-shrink: 0;
}

.badge-imported {
  color: var(--green, #4caf50);
  border-color: color-mix(in srgb, var(--green, #4caf50) 40%, transparent);
  background: color-mix(in srgb, var(--green, #4caf50) 12%, transparent);
}

.sev-bug, .sev-security { color: var(--rose, #e5484d); border-color: color-mix(in srgb, var(--rose, #e5484d) 40%, transparent); background: color-mix(in srgb, var(--rose, #e5484d) 10%, transparent); }
.sev-perf, .sev-quality { color: var(--amber, #ffb300); border-color: color-mix(in srgb, var(--amber, #ffb300) 40%, transparent); background: color-mix(in srgb, var(--amber, #ffb300) 10%, transparent); }

.idea-proposal {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
  margin: 0;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
