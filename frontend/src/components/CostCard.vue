<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import type { CostSummary } from '@/types/api'
import { api } from '@/api/client'

const { t } = useI18n()
const data = ref<CostSummary | null>(null)
const loading = ref(false)

async function fetchCost() {
  loading.value = true
  try {
    data.value = await api.getCostSummary()
  } catch {
    // never-crash
  } finally {
    loading.value = false
  }
}

function fmt(v: number): string {
  return v.toLocaleString()
}

onMounted(fetchCost)
</script>

<template>
  <div class="card cost-card" data-test="cost-card">
    <h3>{{ t('cost.title') }}</h3>
    <div v-if="loading && !data" class="muted small">{{ t('cost.loading') }}</div>
    <div v-else-if="data" class="cost-body">
      <div class="cost-stat">
        <span class="cost-label">{{ t('cost.total') }}</span>
        <span class="cost-value mono" data-test="cost-total">${{ data.totalCostUsd.toFixed(4) }}</span>
      </div>
      <div class="cost-stat">
        <span class="cost-label">{{ t('cost.tokens') }}</span>
        <span class="cost-value mono" data-test="cost-tokens">{{ fmt(data.totalTokens) }}</span>
      </div>
      <div v-if="data.budgetUsd != null && data.budgetUsd > 0" class="cost-stat" data-test="cost-budget">
        <span class="cost-label">{{ t('cost.budget') }}</span>
        <span class="cost-value mono">${{ data.budgetUsd.toFixed(2) }}</span>
        <span class="cost-pct mono">{{ ((data.totalCostUsd / data.budgetUsd) * 100).toFixed(1) }}%</span>
      </div>
      <div v-if="data.topTasks.length" class="cost-tasks">
        <div v-for="t in data.topTasks.slice(0, 5)" :key="t.id" class="cost-task" data-test="cost-task">
          <span class="muted small">{{ t.title }}</span>
          <span class="mono small">${{ t.costUsd.toFixed(4) }}</span>
        </div>
      </div>
    </div>
    <div v-else class="muted small">{{ t('cost.noData') }}</div>
  </div>
</template>

<style scoped>
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.card h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin: 0 0 8px; }
.muted { color: var(--muted); }
.small { font-size: 11px; }
.mono { font-family: var(--mono); }
.cost-body { display: flex; flex-direction: column; gap: 8px; }
.cost-stat { display: flex; align-items: center; gap: 8px; }
.cost-label { color: var(--muted); font-size: 12px; min-width: 60px; }
.cost-value { font-size: 14px; font-weight: 600; }
.cost-pct { font-size: 11px; color: var(--muted); }
.cost-tasks { margin-top: 4px; display: flex; flex-direction: column; gap: 4px; border-top: 1px solid var(--border); padding-top: 8px; }
.cost-task { display: flex; justify-content: space-between; align-items: center; }
</style>
