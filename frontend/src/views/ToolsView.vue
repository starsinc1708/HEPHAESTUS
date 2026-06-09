<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ScanStatus, ScanListItem, RunSummary } from '@/types/api'
import { api } from '@/api/client'
import { useToastStore } from '@/stores/toast'
import { useLoopStore } from '@/stores/loop'
import { useWorkspaceStore } from '@/stores/workspace'
import AppShell from '@/components/AppShell.vue'
import ScopePicker from '@/components/ScopePicker.vue'
import IntegrationsPanel from '@/components/IntegrationsPanel.vue'
import IdeasPanel from '@/components/IdeasPanel.vue'
import ScansPanel from '@/components/ScansPanel.vue'
import InsightsChat from '@/components/InsightsChat.vue'

const { t } = useI18n()
const toast = useToastStore()
const loopStore = useLoopStore()
const ws = useWorkspaceStore()

// ── Page-level state ──
const pageLoading = ref(true)

// ── Scanner section ──
const scanStatus = ref<ScanStatus | null>(null)
const scanLoading = ref(false)
const scanHistory = ref<ScanListItem[]>([])
const historyLoading = ref(false)
const importLoading = ref<string | null>(null)
const scanLog = ref<string[]>([])
const showLog = ref(true)

const PHASE_LABELS = computed<Record<string, string>>(() => ({
  idle: t('tools.scan.phaseIdle'),
  queued: t('tools.scan.phaseQueued'),
  chunking: t('tools.scan.phaseChunking'),
  mapping: t('tools.scan.phaseMapping'),
  reducing: t('tools.scan.phaseReducing'),
  done: t('tools.scan.phaseDone'),
  error: t('tools.scan.phaseError'),
}))
const phaseLabel = computed(() => PHASE_LABELS.value[scanStatus.value?.phase ?? ''] ?? (scanStatus.value?.phase ?? '—'))
// Coarse overall progress across the funnel phases for the bar.
const progressPct = computed(() => {
  const s = scanStatus.value
  if (!s) return 0
  const frac = (d?: number, total?: number) => (total && total > 0 ? Math.min(1, (d ?? 0) / total) : 0)
  switch (s.phase) {
    case 'queued': case 'chunking': return 5
    case 'mapping': return Math.round(10 + 60 * frac(s.scanners_done, s.scanners))
    case 'reducing': return Math.round(70 + 25 * frac(s.reducers_done, s.reviewers))
    case 'done': return 100
    default: return s.phase === 'error' ? 100 : 0
  }
})

// Start scan form
const scanners = ref(6)
const reviewers = ref(2)
const scope = ref('apps packages services')
const starting = ref(false)

let _scanTimer: ReturnType<typeof setInterval> | null = null

async function fetchScanStatus() {
  scanLoading.value = true
  try {
    scanStatus.value = await api.scanStatus()
  } catch {
    // silent
  } finally {
    scanLoading.value = false
  }
}

async function fetchScanHistory() {
  historyLoading.value = true
  try {
    scanHistory.value = await api.scanList()
  } catch {
    // silent
  } finally {
    historyLoading.value = false
  }
}

async function fetchScanLog() {
  const dir = scanStatus.value?.scan_dir
  if (!dir) return
  try {
    const res = await api.scanLog(dir)
    if (res.ok) scanLog.value = res.lines
  } catch {
    // silent
  }
}

// When a run finishes (running flips true→false), pull the final log + refresh history.
watch(() => scanStatus.value?.running, (now, was) => {
  if (was && !now) {
    void fetchScanLog()
    void fetchScanHistory()
  }
})

async function startScan() {
  starting.value = true
  try {
    const res = await api.scanStart({
      scanners: scanners.value,
      reviewers: reviewers.value,
      scope: scope.value,
    })
    if (res.ok) {
      toast.add('success', t('tools.scan.launched'))
      scanLog.value = []
      await fetchScanStatus()
      void fetchScanLog()
    } else {
      toast.add('error', res.error ?? t('tools.scan.startError'))
    }
  } catch (e: unknown) {
    toast.add('error', t('tools.error', { error: e instanceof Error ? e.message : String(e) }))
  } finally {
    starting.value = false
  }
}

async function importScan(dirname: string) {
  if (!confirm(t('tools.scan.importConfirm'))) return
  importLoading.value = dirname
  try {
    const res = await api.scanImport(dirname)
    if (res.ok) {
      toast.add('success', t('tools.scan.imported', { added: res.added.length, skipped: res.skipped.length }))
      await fetchScanHistory()
    } else {
      toast.add('error', t('tools.scan.importError'))
    }
  } catch (e: unknown) {
    toast.add('error', t('tools.error', { error: e instanceof Error ? e.message : String(e) }))
  } finally {
    importLoading.value = null
  }
}

function formatTs(ts?: string): string {
  if (!ts) return '—'
  return ts.slice(0, 16).replace('T', ' ')
}

// ── Driver section — Ralph-only autonomous launcher ──
// Per auto-driver spec §5/§8: queue mode is never started manually from the UI (the driver
// reconciler picks up queued items on its own). The only spec-permitted manual launch is the
// autonomous goal-run (Ralph), which carries its own cost/wallclock budgets.
const costBudgetUsd = ref<number>(1.0)
const wallclockSec = ref<number>(3600)
const runSummary = ref<RunSummary | null>(null)

async function fetchRunSummary() {
  try {
    const res = await api.driverStatus()
    runSummary.value = res.runSummary ?? null
  } catch {
    // silent
  }
}

async function startDriver() {
  try {
    await loopStore.startDriver({
      runMode: 'ralph',
      costBudgetUsd: costBudgetUsd.value,
      wallclockSec: wallclockSec.value,
    })
    toast.add('success', t('tools.ralph.launched'))
    void fetchRunSummary()
  } catch (e: unknown) {
    toast.add('error', t('tools.error', { error: e instanceof Error ? e.message : String(e) }))
  }
}

async function stopDriver() {
  try {
    await loopStore.stopDriver()
    toast.add('success', t('tools.ralph.driverStopped'))
  } catch (e: unknown) {
    toast.add('error', t('tools.error', { error: e instanceof Error ? e.message : String(e) }))
  }
}

async function killDriver() {
  if (!confirm(t('tools.ralph.killConfirm'))) return
  try {
    await loopStore.killDriver()
    toast.add('success', t('tools.ralph.driverKilled'))
  } catch (e: unknown) {
    toast.add('error', t('tools.error', { error: e instanceof Error ? e.message : String(e) }))
  }
}

// ── Quick add section ──
const addId = ref('')
const addTitle = ref('')
const addProposal = ref('')
const adding = ref(false)

async function addItem() {
  if (!addId.value.trim() || !addTitle.value.trim() || !addProposal.value.trim()) {
    toast.add('warn', t('tools.quickAdd.fillAll'))
    return
  }
  adding.value = true
  try {
    const res = await api.addItem({
      id: addId.value.trim(),
      title: addTitle.value.trim(),
      proposal: addProposal.value.trim(),
      why: '',
      acceptance: '',
      touches: [],
    })
    if (res.ok) {
      toast.add('success', t('tools.quickAdd.added', { title: addTitle.value }))
      addId.value = ''
      addTitle.value = ''
      addProposal.value = ''
    } else {
      toast.add('error', t('tools.quickAdd.addError'))
    }
  } catch (e: unknown) {
    toast.add('error', t('tools.error', { error: e instanceof Error ? e.message : String(e) }))
  } finally {
    adding.value = false
  }
}

onMounted(() => {
  pageLoading.value = true
  Promise.all([
    ws.fetchWorkspaces(),
    fetchScanStatus(),
    fetchScanHistory(),
    fetchRunSummary(),
  ]).finally(() => { pageLoading.value = false })
  // Poll quickly while a scan runs so phase/progress/log update near-live; the watcher
  // captures the final state when it stops, so an idle tick costs just one status GET.
  _scanTimer = setInterval(() => {
    void fetchScanStatus()
    if (scanStatus.value?.running) void fetchScanLog()
  }, 2_500)
})

onUnmounted(() => {
  if (_scanTimer !== null) {
    clearInterval(_scanTimer)
    _scanTimer = null
  }
})
</script>

<template>
  <AppShell>
    <template #title>{{ t('tools.title') }}</template>

    <!-- Loading state -->
    <div v-if="pageLoading" class="loading-state" data-test="tools-loading">
      <span class="loading-spinner" />
      <span>{{ t('tools.loading') }}</span>
    </div>

    <div v-else class="tools-page">
      <!-- ── Section 1: Сканер репозитория ── -->
      <section class="tools-section">
        <h3>{{ t('tools.scan.title') }}</h3>

        <!-- Status indicator -->
        <div class="scan-status-card">
          <div class="status-row">
            <span class="status-label">{{ t('tools.scan.status') }}</span>
            <span v-if="scanLoading && !scanStatus" class="loading-inline">{{ t('tools.loading') }}</span>
            <template v-else-if="scanStatus">
              <span class="status-dot" :class="{ running: scanStatus.running }" />
              <span class="status-text">{{ scanStatus.running ? t('tools.scan.running') : t('tools.scan.stopped') }}</span>
            </template>
            <span v-else class="status-text muted">{{ t('tools.scan.noData') }}</span>
          </div>
          <div v-if="scanStatus && scanStatus.phase !== 'idle'" class="status-details">
            <div class="progress-track">
              <div class="progress-fill" :class="scanStatus.phase" :style="{ width: progressPct + '%' }" />
            </div>
            <div class="detail-row">
              <span class="detail-label">{{ t('tools.scan.phase') }}</span>
              <span class="detail-value">{{ phaseLabel }}<span v-if="scanStatus.detail" class="muted"> — {{ scanStatus.detail }}</span></span>
            </div>
            <div class="detail-row">
              <span class="detail-label">{{ t('tools.scan.scanners') }}</span>
              <span class="detail-value">{{ scanStatus.scanners_done ?? 0 }} / {{ scanStatus.scanners ?? 0 }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">{{ t('tools.scan.reviewers') }}</span>
              <span class="detail-value">{{ scanStatus.reducers_done ?? 0 }} / {{ scanStatus.reviewers ?? 0 }}</span>
            </div>
            <div v-if="scanStatus.n_proposals != null" class="detail-row">
              <span class="detail-label">{{ t('tools.scan.proposals') }}</span>
              <span class="detail-value">{{ scanStatus.n_proposals }}<span v-if="scanStatus.n_findings != null" class="muted"> {{ t('tools.scan.findings', { count: scanStatus.n_findings }) }}</span></span>
            </div>
            <div v-if="scanStatus.error" class="detail-row">
              <span class="detail-label">{{ t('tools.scan.errorLabel') }}</span>
              <span class="detail-value err">{{ scanStatus.error }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">{{ t('tools.scan.updated') }}</span>
              <span class="detail-value">{{ formatTs(scanStatus.updatedAt) }}</span>
            </div>
          </div>
        </div>

        <!-- Live worker log -->
        <div v-if="scanLog.length || scanStatus?.running" class="scan-log-block">
          <button class="log-toggle" @click="showLog = !showLog">
            {{ showLog ? '▾' : '▸' }} {{ t('tools.scan.workerLog', { count: scanLog.length }) }}
          </button>
          <pre v-if="showLog" class="scan-log" data-test="scan-log">{{ scanLog.length ? scanLog.join('\n') : t('tools.scan.logEmpty') }}</pre>
        </div>

        <!-- Start scan form -->
        <div v-if="!scanStatus?.running" class="scan-form">
          <div class="form-row">
            <label class="form-label">{{ t('tools.scan.scannersLabel') }}</label>
            <input v-model.number="scanners" type="number" min="1" max="50" class="form-input" />
          </div>
          <div class="form-row">
            <label class="form-label">{{ t('tools.scan.reviewersLabel') }}</label>
            <input v-model.number="reviewers" type="number" min="1" max="50" class="form-input" />
          </div>
          <div class="form-row form-row-scope">
            <label class="form-label">{{ t('tools.scan.scopeLabel') }}</label>
            <p class="scope-help">{{ t('tools.scan.scopeHelp') }}</p>
            <ScopePicker v-if="ws.activeId" :ws-id="ws.activeId" v-model="scope" />
            <p v-else class="scope-help muted">{{ t('tools.scan.noActiveRepo') }}</p>
            <details class="scope-raw">
              <summary>{{ t('tools.scan.setManual') }}</summary>
              <input v-model="scope" type="text" class="form-input" placeholder="apps packages services" />
            </details>
          </div>
          <button class="btn btn-primary" :disabled="starting" @click="startScan">
            <span v-if="starting" class="btn-spinner" />
            {{ starting ? t('tools.scan.starting') : t('tools.scan.start') }}
          </button>
        </div>
      </section>

      <!-- Scan history table -->
      <section class="tools-section">
        <h3>{{ t('tools.history.title') }}</h3>
        <div v-if="historyLoading && scanHistory.length === 0" class="loading">{{ t('tools.history.loading') }}</div>
        <table v-else class="tools-table">
          <thead>
            <tr>
              <th>{{ t('tools.history.dir') }}</th>
              <th>{{ t('tools.history.phase') }}</th>
              <th>{{ t('tools.history.scanners') }}</th>
              <th>{{ t('tools.history.proposals') }}</th>
              <th>{{ t('tools.history.date') }}</th>
              <th>{{ t('tools.history.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in scanHistory" :key="s.dir">
              <td class="mono-cell">{{ s.dir }}</td>
              <td class="mono-cell">{{ s.phase }}</td>
              <td class="mono-cell">{{ s.scanners ?? '—' }} / {{ s.reviewers ?? '—' }}</td>
              <td class="mono-cell">{{ s.n_proposals ?? '—' }}</td>
              <td class="mono-cell">{{ formatTs(s.updatedAt) }}</td>
              <td class="actions">
                <button
                  class="action-btn import"
                  :disabled="importLoading === s.dir"
                  @click="importScan(s.dir)"
                  :title="t('tools.history.importTitle')"
                >
                  {{ importLoading === s.dir ? t('tools.history.importing') : t('tools.history.importBtn') }}
                </button>
              </td>
            </tr>
            <tr v-if="scanHistory.length === 0">
              <td colspan="6" class="empty-row">{{ t('tools.history.empty') }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- Import selected scan findings → board (#7) -->
      <section class="tools-section" data-test="tools-scans-import">
        <h3>{{ t('tools.importSection.title') }}</h3>
        <ScansPanel />
      </section>

      <!-- ── Section 2: Автономный запуск (Ralph) ── -->
      <section class="tools-section">
        <h3>{{ t('tools.ralph.title') }}</h3>
        <p class="section-help">
          {{ t('tools.ralph.help') }}
        </p>
        <div class="driver-status-card">
          <div class="status-row">
            <span class="status-label">{{ t('tools.ralph.state') }}</span>
            <span class="status-dot" :class="{ running: loopStore.status.tmux }" />
            <span class="status-text">{{ loopStore.status.tmux ? t('tools.ralph.started') : t('tools.ralph.stopped') }}</span>
          </div>
          <div v-if="loopStore.status.driver_pid" class="detail-row">
            <span class="detail-label">{{ t('tools.ralph.driverPid') }}</span>
            <span class="detail-value mono">{{ loopStore.status.driver_pid }}</span>
          </div>
          <div v-if="(loopStore.status.opencode_pids ?? []).length > 0" class="detail-row">
            <span class="detail-label">{{ t('tools.ralph.opencodePids') }}</span>
            <span class="detail-value mono">{{ (loopStore.status.opencode_pids ?? []).join(', ') }}</span>
          </div>

          <!-- Ralph budgets (shown when driver is stopped) -->
          <div v-if="!loopStore.status.tmux" class="run-mode-controls">
            <div class="form-row">
              <label class="form-label">{{ t('tools.ralph.budgetLabel') }}</label>
              <input v-model.number="costBudgetUsd" type="number" min="0" step="0.1" class="form-input" />
            </div>
            <div class="form-row">
              <label class="form-label">{{ t('tools.ralph.timeLimitLabel') }}</label>
              <input v-model.number="wallclockSec" type="number" min="0" step="60" class="form-input" />
            </div>
          </div>

          <!-- Run summary (when available) -->
          <div v-if="runSummary" class="run-summary">
            <div class="detail-row">
              <span class="detail-label">{{ t('tools.ralph.mode') }}</span>
              <span class="detail-value mono">{{ runSummary.runMode }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">{{ t('tools.ralph.doneErrors') }}</span>
              <span class="detail-value mono">{{ runSummary.itemsDone }} / {{ runSummary.itemsFailed }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">{{ t('tools.ralph.cost') }}</span>
              <span class="detail-value mono">${{ runSummary.costUsd.toFixed(4) }}</span>
            </div>
            <div v-if="runSummary.stoppedReason" class="detail-row">
              <span class="detail-label">{{ t('tools.ralph.stopReason') }}</span>
              <span class="detail-value mono">{{ runSummary.stoppedReason }}</span>
            </div>
          </div>

          <div class="driver-actions">
            <button
              v-if="!loopStore.status.tmux"
              class="btn btn-primary"
              data-test="ralph-start"
              @click="startDriver"
            >
              {{ t('tools.ralph.startBtn') }}
            </button>
            <button
              v-if="loopStore.status.tmux"
              class="btn btn-warn"
              @click="stopDriver"
            >
              {{ t('tools.ralph.stopBtn') }}
            </button>
            <button
              v-if="loopStore.status.tmux"
              class="btn btn-kill"
              @click="killDriver"
            >
              {{ t('tools.ralph.killBtn') }}
            </button>
          </div>
        </div>
      </section>

      <!-- ── Section 3: Интеграции ── -->
      <section class="tools-section">
        <h3>{{ t('tools.integrations.title') }}</h3>
        <IntegrationsPanel />
      </section>

      <!-- ── Section 4: Ideas ── -->
      <section class="tools-section">
        <h3>{{ t('tools.ideas.title') }}</h3>
        <IdeasPanel />
      </section>

      <!-- ── Section 5: Insights ── -->
      <section class="tools-section" data-test="tools-insights">
        <h3>{{ t('tools.insights.title') }}</h3>
        <InsightsChat />
      </section>

      <!-- ── Section 6: Быстрое добавление ── -->
      <section class="tools-section">
        <h3>{{ t('tools.quickAdd.title') }}</h3>
        <div class="quick-add-form">
          <div class="form-row">
            <label class="form-label">{{ t('tools.quickAdd.idLabel') }}</label>
            <input v-model="addId" type="text" class="form-input" placeholder="my-task-id" />
          </div>
          <div class="form-row">
            <label class="form-label">{{ t('tools.quickAdd.titleLabel') }}</label>
            <input v-model="addTitle" type="text" class="form-input" :placeholder="t('tools.quickAdd.titlePlaceholder')" />
          </div>
          <div class="form-row">
            <label class="form-label">{{ t('tools.quickAdd.proposalLabel') }}</label>
            <textarea v-model="addProposal" class="form-textarea" rows="3" :placeholder="t('tools.quickAdd.proposalPlaceholder')" />
          </div>
          <button class="btn btn-primary" :disabled="adding" @click="addItem">
            <span v-if="adding" class="btn-spinner" />
            {{ adding ? t('tools.quickAdd.adding') : t('tools.quickAdd.addBtn') }}
          </button>
        </div>
      </section>
    </div>
  </AppShell>
</template>

<style scoped>
.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 60px 0;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 14px;
}

.loading-spinner {
  display: inline-block;
  width: 18px;
  height: 18px;
  border: 2px solid var(--border);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.tools-page {
  max-width: 900px;
}

.tools-section {
  margin-bottom: 28px;
}
.tools-section h3 {
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  margin: 0 0 12px;
}

/* ── Status card ── */
.scan-status-card,
.driver-status-card {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 14px;
  margin-bottom: 14px;
}

.status-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.status-label {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--muted);
  flex-shrink: 0;
}
.status-dot.running {
  background: var(--green);
  animation: pulse 2s ease-in-out infinite;
}
.status-text {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text);
}
.status-text.muted {
  color: var(--muted-soft);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.3; }
}

.status-details {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}

.detail-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.detail-label {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
  min-width: 100px;
}
.detail-value {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text);
}
.detail-value.mono {
  font-family: var(--mono);
}

.loading {
  text-align: center;
  padding: 30px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 12px;
}

.loading-inline {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
}

/* ── Form ── */
.scan-form,
.quick-add-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: 400px;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.form-label {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
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
}
.form-input:focus {
  border-color: var(--primary);
}
.progress-track {
  height: 6px; background: var(--panel-3, var(--panel-2)); border-radius: 3px;
  overflow: hidden; margin-bottom: 8px;
}
.progress-fill {
  height: 100%; background: var(--primary); border-radius: 3px;
  transition: width 0.4s ease;
}
.progress-fill.done { background: var(--green, #4caf50); }
.progress-fill.error { background: var(--rose, #e5484d); }
.detail-value .muted { color: var(--muted); }
.detail-value.err { color: var(--rose); font-family: var(--mono); }
.scan-log-block { margin-top: 10px; }
.log-toggle {
  background: none; border: none; color: var(--muted); cursor: pointer;
  font-family: var(--mono); font-size: 11px; padding: 2px 0;
}
.log-toggle:hover { color: var(--text); }
.scan-log {
  margin: 6px 0 0; max-height: 240px; overflow: auto;
  background: var(--panel-2); border: 1px solid var(--border); border-radius: 6px;
  padding: 8px 10px; font-family: var(--mono); font-size: 11px; line-height: 1.5;
  color: var(--text); white-space: pre-wrap; word-break: break-word;
}
.form-row-scope { gap: 6px; }
.scope-help { font-size: 11px; color: var(--muted); margin: 0; line-height: 1.4; }
.scope-help.muted { color: var(--muted); }
.scope-raw { margin-top: 2px; }
.scope-raw summary { font-size: 11px; color: var(--muted); cursor: pointer; }
.scope-raw .form-input { width: 100%; margin-top: 6px; box-sizing: border-box; }
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
  resize: vertical;
}
.form-textarea:focus {
  border-color: var(--primary);
}

/* ── Table ── */
.tools-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.tools-table th {
  text-align: left;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
}
.tools-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}
.mono-cell {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text);
}
.empty-row {
  text-align: center;
  color: var(--muted-soft);
  padding: 30px;
}

/* ── Buttons ── */
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
.btn-warn { border-color: var(--amber); color: var(--amber); }
.btn-kill { border-color: var(--rose); color: var(--rose); }

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

.actions {
  display: flex;
  gap: 4px;
}

.action-btn {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 11px;
  padding: 3px 8px;
  cursor: pointer;
  transition: color 0.12s, border-color 0.12s;
}
.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.action-btn:hover:not(:disabled) { color: var(--text); border-color: var(--border-2); }
.action-btn.import:hover:not(:disabled) { color: var(--blue); border-color: var(--blue); }

.section-help {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
  margin: -6px 0 12px;
  max-width: 600px;
}

.run-mode-controls {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
  max-width: 300px;
}

.run-summary {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 10px;
  padding: 8px;
  background: var(--panel-3, var(--panel));
  border-radius: 4px;
  border: 1px solid var(--border);
}

.driver-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}
</style>
