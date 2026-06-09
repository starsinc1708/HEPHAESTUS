<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import { useToastStore } from '@/stores/toast'
import { useAgentJob } from '@/composables/useAgentJob'

// #7 — «Новая цель» on the Board. Opens a modal (title + description + optional max),
// fires the ASYNC decompose agent-job, shows progress, and refreshes the board on done.
// One-shot: the job lands the decomposed tree as `pending` tasks (no Ralph auto-start).
const emit = defineEmits<{ planned: [] }>()

const { t } = useI18n()
const toast = useToastStore()
const open = ref(false)
const title = ref('')
const description = ref('')
const maxTasks = ref<number | null>(null)

// FEAT-003: built-in goal templates — selecting one seeds title + description.
interface GoalTemplate { id: string; title: string; description: string }
const templates = ref<GoalTemplate[]>([])
const selectedTemplate = ref('')

const job = useAgentJob()
const planning = computed(() => job.status.value === 'running')
const canPlan = computed(() => title.value.trim().length > 0 && !planning.value)

async function openModal() {
  open.value = true
  if (!templates.value.length) {
    try {
      const r = await api.goalTemplates()
      if (r.ok) templates.value = r.templates
    } catch { /* templates are optional — silently skip */ }
  }
}

function applyTemplate() {
  const t = templates.value.find((x) => x.id === selectedTemplate.value)
  if (t) {
    title.value = t.title
    description.value = t.description
  }
}

function closeModal() {
  if (planning.value) return // don't dismiss while the job runs
  open.value = false
}

async function onPlan() {
  if (!canPlan.value) return
  const titleText = title.value.trim()
  const d = description.value.trim()
  const max = maxTasks.value && maxTasks.value > 0 ? maxTasks.value : undefined

  await job.run(() => api.decomposeGoal(titleText, d, max))

  if (job.status.value === 'done') {
    const n = (job.result.value?.taskIds ?? []).length
    toast.add('success', n ? t('goal.planned', n) : t('goal.decomposed'))
    emit('planned')
    title.value = ''
    description.value = ''
    maxTasks.value = null
    selectedTemplate.value = ''
    open.value = false
  } else if (job.status.value === 'failed') {
    toast.add('error', t('goal.error', { error: job.error.value ?? '' }))
  }
}

// UI-006: let the parent (BoardView) open the modal via the `n` shortcut.
defineExpose({ openModal })
</script>

<template>
  <div class="goal-modal-root">
    <button class="btn btn-primary" data-test="new-goal" @click="openModal">
      {{ t('goal.newGoal') }}
    </button>

    <div v-if="open" class="modal-overlay" @click.self="closeModal">
      <div class="modal" role="dialog" aria-modal="true" data-test="goal-modal">
        <div class="modal-header">
          <h3>{{ t('goal.modalTitle') }}</h3>
          <button class="modal-close" :aria-label="t('goal.close')" :disabled="planning" @click="closeModal">✕</button>
        </div>

        <p class="modal-help">{{ t('goal.help') }}</p>

        <div class="modal-form">
          <template v-if="templates.length">
            <label class="form-label">{{ t('goal.templateLabel') }}</label>
            <select
              v-model="selectedTemplate"
              class="form-input"
              data-test="goal-template"
              :disabled="planning"
              @change="applyTemplate"
            >
              <option value="">{{ t('goal.noTemplate') }}</option>
              <option v-for="tpl in templates" :key="tpl.id" :value="tpl.id">{{ tpl.title }}</option>
            </select>
          </template>
          <label class="form-label">{{ t('goal.goalLabel') }}</label>
          <input
            v-model="title"
            type="text"
            class="form-input"
            :placeholder="t('goal.goalPlaceholder')"
            :disabled="planning"
          />
          <label class="form-label">{{ t('goal.descLabel') }}</label>
          <textarea
            v-model="description"
            class="form-textarea"
            rows="3"
            :placeholder="t('goal.descPlaceholder')"
            :disabled="planning"
          />
          <label class="form-label">{{ t('goal.maxLabel') }}</label>
          <input
            v-model.number="maxTasks"
            type="number"
            min="1"
            max="50"
            class="form-input form-input-narrow"
            :placeholder="t('goal.maxPlaceholder')"
            data-test="goal-max"
            :disabled="planning"
          />
        </div>

        <div v-if="planning" class="modal-progress" data-test="goal-progress">
          <span class="btn-spinner" />
          <span>{{ t('goal.progress') }}</span>
        </div>

        <div class="modal-footer">
          <button class="btn" :disabled="planning" @click="closeModal">{{ t('goal.cancel') }}</button>
          <button class="btn btn-primary" data-test="plan-goal" :disabled="!canPlan" @click="onPlan">
            <span v-if="planning" class="btn-spinner" />
            {{ planning ? t('goal.planning') : t('goal.plan') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.goal-modal-root {
  margin-bottom: 12px;
}

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
}
.btn:hover:not(:disabled) { background: var(--panel-3, var(--panel)); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { border-color: var(--primary); color: var(--primary); }

.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 12vh;
  z-index: 50;
}

.modal {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 18px;
  width: min(520px, 92vw);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.4);
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.modal-header h3 {
  margin: 0;
  font-size: 14px;
  color: var(--text);
}
.modal-close {
  background: none;
  border: none;
  color: var(--muted);
  font-size: 14px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
}
.modal-close:hover:not(:disabled) { color: var(--text); background: var(--panel-2); }
.modal-close:disabled { opacity: 0.4; cursor: not-allowed; }

.modal-help {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
  margin: 0 0 14px;
}

.modal-form {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.form-label {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
  margin-top: 4px;
}
.form-input,
.form-textarea {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-family: var(--mono);
  font-size: 12px;
  padding: 6px 10px;
  outline: none;
  transition: border-color 0.15s;
}
.form-input:focus,
.form-textarea:focus { border-color: var(--primary); }
.form-textarea { resize: vertical; }
.form-input-narrow { width: 160px; }

.modal-progress {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 18px;
}

.btn-spinner {
  display: inline-block;
  width: 11px;
  height: 11px;
  border: 1.5px solid var(--border);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
