<script setup lang="ts">
// FEAT-005: run history / analytics. Shows the most recent finished orchestrator
// runs (mode, items done/failed, cost, duration, why it stopped) — a lightweight
// audit trail beyond the single live RunSummary.
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RunSummary } from '@/types/api'
import { api } from '@/api/client'

const { t } = useI18n()
const runs = ref<RunSummary[]>([])
const total = ref(0)
const loading = ref(false)
const loaded = ref(false)

const PAGE = 8

async function fetchRuns() {
  loading.value = true
  try {
    const r = await api.driverRuns(0, PAGE)
    if (r.ok) {
      runs.value = r.runs
      total.value = r.total
    }
  } catch {
    // never-crash
  } finally {
    loading.value = false
    loaded.value = true
  }
}

function duration(run: RunSummary): string {
  const end = run.endedAtMs ?? 0
  if (!run.startedAtMs || !end || end <= run.startedAtMs) return '—'
  const sec = Math.round((end - run.startedAtMs) / 1000)
  if (sec < 60) return t('runHistory.durS', { n: sec })
  const m = Math.floor(sec / 60)
  const s = sec % 60
  if (m < 60) return s ? t('runHistory.durMS', { m, s }) : t('runHistory.durM', { n: m })
  return t('runHistory.durHM', { h: Math.floor(m / 60), m: m % 60 })
}

// Aggregate analytics across the loaded window.
const totals = computed(() => ({
  done: runs.value.reduce((a, r) => a + r.itemsDone, 0),
  failed: runs.value.reduce((a, r) => a + r.itemsFailed, 0),
  cost: runs.value.reduce((a, r) => a + r.costUsd, 0),
}))

function shortReason(r: RunSummary): string {
  const reason = (r.stoppedReason ?? '').trim()
  if (!reason) return r.itemsFailed > 0 ? t('runHistory.stopped') : t('runHistory.finished')
  return reason.length > 40 ? reason.slice(0, 39) + '…' : reason
}

onMounted(fetchRuns)
</script>

<template>
  <div class="card run-history" data-test="run-history">
    <h3>{{ t('runHistory.title') }}</h3>
    <div v-if="loading && !loaded" class="muted small">{{ t('runHistory.loading') }}</div>
    <div v-else-if="runs.length === 0" class="muted small" data-test="run-history-empty">
      {{ t('runHistory.empty') }}
    </div>
    <template v-else>
      <div class="rh-totals" data-test="run-history-totals">
        <span class="rh-chip ok">✓ {{ totals.done }}</span>
        <span class="rh-chip fail">✗ {{ totals.failed }}</span>
        <span class="rh-chip mono">${{ totals.cost.toFixed(4) }}</span>
        <span v-if="total > runs.length" class="muted small">{{ t('runHistory.ofTotal', { total }) }}</span>
      </div>
      <ul class="rh-list">
        <li v-for="(r, i) in runs" :key="i" class="rh-row" data-test="run-history-row">
          <span class="rh-mode mono" :class="r.runMode === 'ralph' ? 'ralph' : 'queue'">{{ r.runMode }}</span>
          <span class="rh-counts mono">
            <span class="ok">{{ r.itemsDone }}</span>/<span class="fail">{{ r.itemsFailed }}</span>
          </span>
          <span class="rh-cost mono">${{ r.costUsd.toFixed(3) }}</span>
          <span class="rh-dur mono muted">{{ duration(r) }}</span>
          <span class="rh-reason muted small" :title="r.stoppedReason ?? ''">{{ shortReason(r) }}</span>
        </li>
      </ul>
    </template>
  </div>
</template>

<style scoped>
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.card h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin: 0 0 8px; }
.muted { color: var(--muted); }
.small { font-size: 11px; }
.mono { font-family: var(--mono); }
.ok { color: var(--green); }
.fail { color: var(--rose); }

.rh-totals { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.rh-chip {
  font-family: var(--mono);
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--panel-2);
  border: 1px solid var(--border);
}

.rh-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.rh-row {
  display: grid;
  grid-template-columns: 46px 42px auto auto;
  grid-template-areas: 'mode counts cost dur' 'reason reason reason reason';
  align-items: center;
  gap: 2px 8px;
  padding: 4px 0;
  border-top: 1px solid var(--border);
  font-size: 12px;
}
.rh-row:first-child { border-top: none; }
.rh-mode { grid-area: mode; font-size: 10px; padding: 1px 5px; border-radius: 4px; text-align: center; }
.rh-mode.ralph { color: var(--violet); background: color-mix(in srgb, var(--violet) 12%, transparent); }
.rh-mode.queue { color: var(--cyan); background: color-mix(in srgb, var(--cyan) 12%, transparent); }
.rh-counts { grid-area: counts; }
.rh-cost { grid-area: cost; text-align: right; }
.rh-dur { grid-area: dur; text-align: right; font-size: 11px; }
.rh-reason { grid-area: reason; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
