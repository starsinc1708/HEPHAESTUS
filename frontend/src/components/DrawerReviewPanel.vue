<script setup lang="ts">
// Presentational «Ревью» tab panel extracted from TaskDrawer (ARCH/maintainability —
// TaskDrawer was >1000 lines). Pure props, no side effects.
import { useI18n } from 'vue-i18n'
import type { Verdict, IterReviewsResponse, ValidationResult } from '@/types/api'
import ValidationPanel from './ValidationPanel.vue'

const { t } = useI18n()

defineProps<{
  validation: ValidationResult | null
  verdicts: Verdict[]
  reviews: IterReviewsResponse | null
}>()

function getFinalDecision(fd: Record<string, unknown>): string {
  if (typeof fd === 'object' && fd !== null && 'final_decision' in fd) {
    const inner = fd.final_decision
    if (typeof inner === 'string') return inner
  }
  return '—'
}
</script>

<template>
  <div class="review-list">
    <ValidationPanel :validation="validation" />
    <div v-for="(v, i) in verdicts" :key="i" class="verdict-row">
      <span class="v-reviewer">{{ v.reviewer }}</span>
      <span class="v-tier">{{ v.tier }}</span>
      <span class="v-verdict" :class="v.verdict">{{ v.verdict }}</span>
      <span v-if="v.confidence != null" class="v-conf">{{ ((v.confidence ?? 0) * 100).toFixed(0) }}%</span>
    </div>
    <div v-if="reviews?.final_decision" class="final-decision">
      <strong>{{ t('drawerReview.decision') }}</strong> {{ getFinalDecision(reviews.final_decision) }}
    </div>
    <div v-if="verdicts.length === 0 && !validation" class="tab-empty">{{ t('drawerReview.noReview') }}</div>
  </div>
</template>

<style scoped>
.review-list { display: flex; flex-direction: column; gap: 6px; }
.verdict-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 8px;
  background: var(--panel-2);
  border-radius: 4px;
}
.v-reviewer { font-family: var(--mono); font-size: 11px; color: var(--primary); font-weight: 600; }
.v-tier { font-size: 10px; color: var(--muted); }
.v-verdict {
  font-family: var(--mono);
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 3px;
}
.v-verdict.approve, .v-verdict.APPROVE { color: var(--green); background: rgba(52,211,153,0.12); }
.v-verdict.reject, .v-verdict.REJECT { color: var(--rose); background: rgba(248,113,113,0.12); }
.v-verdict.needs_work, .v-verdict.NEEDS_WORK { color: var(--amber); background: rgba(251,191,36,0.12); }
.v-conf { font-family: var(--mono); font-size: 10px; color: var(--muted); margin-left: auto; }
.final-decision {
  margin-top: 12px;
  padding: 10px;
  background: var(--panel-3);
  border-radius: 6px;
  font-size: 13px;
  color: var(--text);
}
.tab-empty { text-align: center; padding: 30px 0; color: var(--muted); font-size: 13px; }
</style>
