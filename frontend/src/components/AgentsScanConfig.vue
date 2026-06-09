<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useConfigStore } from '@/stores/config'

const configStore = useConfigStore()
const { t } = useI18n()
const editBuffer = ref<Record<string, string>>({})
const selectedPreset = ref('standard')
const saving = ref(false)

// EffectiveConfig is Record<string, string | undefined>, which is NOT assignable to
// editBuffer (Record<string, string>). Normalise undefined -> '' so behaviour is
// identical but the assignment is type-clean.
const toStrMap = (src: Record<string, string | undefined>): Record<string, string> =>
  Object.fromEntries(Object.entries(src).map(([k, v]) => [k, v ?? '']))

const PRESETS = computed(() => [
  { name: 'strict',     label: t('agents.scanConfig.strict') },
  { name: 'standard',   label: t('agents.scanConfig.standard') },
  { name: 'permissive', label: t('agents.scanConfig.permissive') },
  { name: 'disabled',   label: t('agents.scanConfig.disabled') },
])

const NUMERIC_KEYS = new Set(['HEPHAESTUS_MAX_ITER', 'HEPHAESTUS_ITER_TIMEOUT_SEC', 'HEPHAESTUS_MAX_CONSEC_FAIL'])

// Keys with a fully-known set of values -> render as a dropdown instead of free text.
const ENUM_KEYS: Record<string, string[]> = {
  HEPHAESTUS_TIER_REVIEW: ['on', 'off'],
  HEPHAESTUS_AUTOPUSH: ['on', 'off'],
}

const EDITABLE_KEYS = [
  'HEPHAESTUS_MAX_ITER', 'HEPHAESTUS_ITER_TIMEOUT_SEC', 'HEPHAESTUS_MAX_CONSEC_FAIL',
  'HEPHAESTUS_TIER_REVIEW', 'HEPHAESTUS_PRIMARY_AGENT', 'HEPHAESTUS_FALLBACK_AGENT',
  'HEPHAESTUS_AUTOPUSH', 'HEPHAESTUS_TIER1_APPROVE_THRESHOLD', 'HEPHAESTUS_TIER2_APPROVE_THRESHOLD',
]

const isDirty = computed(() => {
  for (const key of EDITABLE_KEYS) {
    if (editBuffer.value[key] !== configStore.effective[key]) return true
  }
  return false
})

function isNumericInvalid(key: string): boolean {
  if (!NUMERIC_KEYS.has(key)) return false
  const val = editBuffer.value[key]
  if (val === undefined || val === '') return false
  const num = Number(val)
  return isNaN(num) || num <= 0
}

function numericHelper(key: string): string {
  if (!isNumericInvalid(key)) return ''
  return t('agents.scanConfig.positiveNumber')
}

onMounted(async () => {
  await configStore.fetchConfig()
  editBuffer.value = toStrMap(configStore.effective)
  configStore.snapshotOriginals()
})

async function save() {
  const overrides: Record<string, string> = {}
  for (const key of EDITABLE_KEYS) {
    const val = editBuffer.value[key]
    if (val !== undefined && val !== configStore.effective[key]) {
      overrides[key] = val
    }
  }
  saving.value = true
  try {
    await configStore.saveConfig(overrides)
    editBuffer.value = toStrMap(configStore.effective)
  } finally {
    saving.value = false
  }
}

async function applyPreset() {
  await configStore.applyPreset(selectedPreset.value)
  editBuffer.value = toStrMap(configStore.effective)
}

function discard() {
  editBuffer.value = toStrMap(configStore.effective)
  configStore.discardChanges()
}
</script>

<template>
  <div class="config-page">
    <section class="config-section">
      <h3>{{ t('agents.scanConfig.presetTitle') }}</h3>
      <div class="preset-row">
        <select v-model="selectedPreset" class="select-input">
          <option v-for="p in PRESETS" :key="p.name" :value="p.name">{{ p.label }}</option>
        </select>
        <button class="btn" @click="applyPreset">{{ t('agents.scanConfig.applyPreset') }}</button>
      </div>
    </section>

    <section class="config-section">
      <div class="section-header">
        <h3>{{ t('agents.scanConfig.parameters') }}</h3>
        <div v-if="isDirty" class="dirty-badge">
          {{ t('agents.scanConfig.unsavedChanges') }}
        </div>
      </div>
      <div class="config-grid">
        <div v-for="key in EDITABLE_KEYS" :key="key" class="config-field">
          <label class="config-label">{{ key }}</label>
          <select
            v-if="ENUM_KEYS[key]"
            v-model="editBuffer[key]"
            class="config-input"
          >
            <option v-for="opt in ENUM_KEYS[key]" :key="opt" :value="opt">{{ opt }}</option>
          </select>
          <input
            v-else
            v-model="editBuffer[key]"
            type="text"
            class="config-input"
            :class="{ 'config-input-invalid': isNumericInvalid(key) }"
          />
          <span v-if="isNumericInvalid(key)" class="config-helper">{{ numericHelper(key) }}</span>
        </div>
      </div>
      <div class="save-row">
        <button
          class="btn btn-primary"
          :disabled="saving"
          @click="save"
        >
          <span v-if="saving" class="btn-spinner" />
          {{ saving ? t('agents.scanConfig.saving') : t('agents.scanConfig.save') }}
        </button>
        <button
          v-if="isDirty"
          class="btn btn-discard"
          @click="discard"
        >
          {{ t('agents.scanConfig.discard') }}
        </button>
      </div>
    </section>

    <section class="config-section">
      <h3>{{ t('agents.scanConfig.currentConfig') }}</h3>
      <pre class="config-dump">{{ JSON.stringify(configStore.effective, null, 2) }}</pre>
    </section>
  </div>
</template>

<style scoped>
.config-page { max-width: 800px; }

.config-section {
  margin-bottom: 24px;
}
.config-section h3 {
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  margin: 0 0 10px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}
.section-header h3 { margin: 0; }

.dirty-badge {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--amber);
  background: rgba(251,191,36,0.1);
  border: 1px solid rgba(251,191,36,0.3);
  border-radius: 3px;
  padding: 2px 8px;
}

.preset-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.select-input {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-family: var(--mono);
  font-size: 12px;
  padding: 6px 10px;
  outline: none;
}
.select-input:focus { border-color: var(--primary); }

.config-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.config-field { display: flex; flex-direction: column; gap: 4px; }
.config-label {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
}
.config-input {
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
.config-input:focus { border-color: var(--primary); }
.config-input-invalid { border-color: var(--rose); }
.config-input-invalid:focus { border-color: var(--rose); }

.config-helper {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--rose);
}

.save-row {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.config-dump {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text);
  background: var(--panel-2);
  padding: 12px;
  border-radius: 4px;
  overflow-x: auto;
  white-space: pre;
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
  transition: background 0.12s;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.btn:hover:not(:disabled) { background: var(--panel-3); }
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-primary { border-color: var(--primary); color: var(--primary); }
.btn-discard { border-color: var(--muted); color: var(--muted); }

.btn-spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid var(--border);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
