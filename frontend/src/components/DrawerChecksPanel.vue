<script setup lang="ts">
// Presentational «Проверки» tab panel extracted from TaskDrawer (maintainability). Pure props.
import { useI18n } from 'vue-i18n'
import type { VerifyOutcome } from '@/types/api'

const { t } = useI18n()

defineProps<{
  verifyOutcome: VerifyOutcome | null
  scopeExtra: string[]
  checksError: boolean
}>()
</script>

<template>
  <div class="checks-panel" data-test="checks-panel">
    <div v-if="checksError" class="tab-empty" data-test="checks-error">
      {{ t('drawerChecks.loadError') }}
    </div>
    <template v-else>
      <div v-if="verifyOutcome" class="checks-outcome">
        <div class="outcome-header">
          <span class="outcome-badge" :class="{ green: verifyOutcome.passed, red: !verifyOutcome.passed }">
            {{ verifyOutcome.passed ? t('drawerChecks.passed') : t('drawerChecks.failed') }}
          </span>
          <span class="outcome-title">{{ t('drawerChecks.resultsTitle') }}</span>
        </div>
        <div class="checks-stats">
          <div class="stat-row">
            <span>{{ t('drawerChecks.checksRun') }}</span>
            <span class="mono">{{ verifyOutcome.checks_ran }}</span>
          </div>
          <div class="stat-row">
            <span>{{ t('drawerChecks.honestyStatus') }}</span>
            <span class="mono">{{ verifyOutcome.unverified ? t('drawerChecks.honestyYes') : t('drawerChecks.honestyNo') }}</span>
          </div>
          <div v-if="verifyOutcome.detail" class="detail-box">
            <strong>{{ t('drawerChecks.details') }}</strong> {{ verifyOutcome.detail }}
          </div>
        </div>
      </div>
      <div v-if="scopeExtra.length" class="scope-warning" data-test="scope-warning">
        <strong>{{ t('drawerChecks.outOfScope') }}</strong>
        <ul class="scope-list">
          <li v-for="f in scopeExtra" :key="f" class="mono">{{ f }}</li>
        </ul>
      </div>
      <div v-if="!verifyOutcome && !scopeExtra.length" class="tab-empty">
        {{ t('drawerChecks.noData') }}
      </div>
    </template>
  </div>
</template>

<style scoped>
.checks-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.scope-warning {
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.4);
  border-radius: 6px;
  padding: 12px 16px;
  font-size: 13px;
  color: var(--amber, #f59e0b);
}
.scope-list {
  margin: 6px 0 0;
  padding-left: 18px;
}
.checks-outcome {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 16px;
}
.outcome-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.outcome-badge {
  font-size: 11px;
  text-transform: uppercase;
  font-weight: bold;
  padding: 4px 8px;
  border-radius: 4px;
}
.outcome-badge.green {
  background: rgba(16, 185, 129, 0.15);
  color: rgb(52, 211, 153);
}
.outcome-badge.red {
  background: rgba(239, 68, 68, 0.15);
  color: rgb(248, 113, 113);
}
.outcome-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.checks-stats {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.stat-row {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: var(--muted);
}
.detail-box {
  margin-top: 12px;
  font-size: 13px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 8px 12px;
  color: var(--text);
  white-space: pre-wrap;
}
.tab-empty { text-align: center; padding: 30px 0; color: var(--muted); font-size: 13px; }
.mono { font-family: var(--mono); }
</style>
