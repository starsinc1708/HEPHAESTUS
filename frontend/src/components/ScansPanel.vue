<script setup lang="ts">
import { onMounted, ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ScanListItem, ScanFinding } from '@/types/api'
import { api } from '@/api/client'
import { useToastStore } from '@/stores/toast'

// #7 — pick a completed scan, select its findings with checkboxes, and import the
// selected ones onto the board as `pending` tasks (idempotent: re-import is safe).
const { t } = useI18n()
const toast = useToastStore()

const scans = ref<ScanListItem[]>([])
const selectedDir = ref('')
const findings = ref<ScanFinding[]>([])
const selected = ref<Set<string>>(new Set())
const loadingFindings = ref(false)
const importing = ref(false)

// Only scans that have produced importable proposals.
const importable = computed(() =>
  scans.value.filter(s => (s.n_proposals ?? 0) > 0 || s.phase === 'done'),
)

async function fetchScans() {
  try {
    scans.value = await api.scanList() // newest first
    if (!selectedDir.value && importable.value.length > 0) {
      selectedDir.value = importable.value[0].dir
    }
  } catch {
    // silent — the scanner section above surfaces scan errors
  }
}

async function fetchFindings() {
  selected.value = new Set()
  if (!selectedDir.value) {
    findings.value = []
    return
  }
  loadingFindings.value = true
  try {
    const res = await api.scanResults(selectedDir.value)
    findings.value = res.ok ? (res.proposals ?? []) : []
  } catch {
    findings.value = []
  } finally {
    loadingFindings.value = false
  }
}

watch(selectedDir, () => { void fetchFindings() })

function toggleSelect(id: string) {
  const s = new Set(selected.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  selected.value = s
}

async function importSelected() {
  if (selected.value.size === 0) {
    toast.add('warn', t('tools.scansPanel.selectWarning'))
    return
  }
  importing.value = true
  try {
    const res = await api.scansImport([...selected.value], selectedDir.value)
    if (res.ok) {
      toast.add('success', t('tools.scansPanel.imported', { added: res.added.length, skipped: res.skipped.length }))
      selected.value = new Set()
    } else {
      toast.add('error', res.error ?? t('tools.scansPanel.importError'))
    }
  } catch (e: unknown) {
    toast.add('error', t('tools.error', { error: e instanceof Error ? e.message : String(e) }))
  } finally {
    importing.value = false
  }
}

onMounted(() => { void fetchScans() })
</script>

<template>
  <div class="scans-panel">
    <div v-if="importable.length === 0" class="scans-empty">
      {{ t('tools.scansPanel.empty') }}
    </div>

    <template v-else>
      <div class="scans-controls">
        <label class="form-label">{{ t('tools.scansPanel.scanLabel') }}</label>
        <select v-model="selectedDir" class="form-select" data-test="scans-select">
          <option v-for="s in importable" :key="s.dir" :value="s.dir">
            {{ s.dir }}<span v-if="s.n_proposals != null"> {{ t('tools.scansPanel.findingsCount', { count: s.n_proposals }) }}</span>
          </option>
        </select>
        <button
          class="btn btn-secondary"
          data-test="scans-import"
          :disabled="importing || selected.size === 0"
          @click="importSelected"
        >
          <span v-if="importing" class="btn-spinner" />
          {{ importing ? t('tools.scansPanel.importing') : t('tools.scansPanel.importBtn', { count: selected.size }) }}
        </button>
      </div>

      <div v-if="loadingFindings" class="scans-empty">{{ t('tools.scansPanel.loadingFindings') }}</div>
      <div v-else-if="findings.length === 0" class="scans-empty">
        {{ t('tools.scansPanel.noFindings') }}
      </div>
      <div v-else class="findings-list">
        <div
          v-for="f in findings"
          :key="f.id"
          class="finding-card"
          :class="{ selected: selected.has(f.id) }"
          data-test="finding-card"
          @click="toggleSelect(f.id)"
        >
          <div class="finding-header">
            <input
              type="checkbox"
              :data-test="'import-select-' + f.id"
              :checked="selected.has(f.id)"
              @click.stop="toggleSelect(f.id)"
            />
            <span class="finding-title">{{ f.title }}</span>
            <span v-if="f.category" class="badge">{{ f.category }}</span>
            <span v-if="f.severity" class="badge" :class="'sev-' + f.severity">{{ f.severity }}</span>
          </div>
          <p class="finding-proposal">{{ f.proposal }}</p>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.scans-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.scans-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.form-label {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
}

.form-select {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-family: var(--mono);
  font-size: 12px;
  padding: 6px 10px;
  outline: none;
  flex: 1;
  min-width: 180px;
}
.form-select:focus { border-color: var(--primary); }

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

.scans-empty {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--muted);
  padding: 8px 0;
}

.findings-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 360px;
  overflow: auto;
}

.finding-card {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px 12px;
  cursor: pointer;
  transition: border-color 0.12s, background 0.12s;
}
.finding-card:hover { border-color: var(--primary); }
.finding-card.selected {
  border-color: var(--primary);
  background: color-mix(in srgb, var(--primary) 8%, var(--panel-2));
}

.finding-header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.finding-title {
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
.sev-high, .sev-bug, .sev-security { color: var(--rose, #e5484d); border-color: color-mix(in srgb, var(--rose, #e5484d) 40%, transparent); background: color-mix(in srgb, var(--rose, #e5484d) 10%, transparent); }
.sev-medium, .sev-perf, .sev-quality { color: var(--amber, #ffb300); border-color: color-mix(in srgb, var(--amber, #ffb300) 40%, transparent); background: color-mix(in srgb, var(--amber, #ffb300) 10%, transparent); }

.finding-proposal {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
  margin: 0;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
