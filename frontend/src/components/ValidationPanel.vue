<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ValidationResult, LensVerdict } from '@/types/api'

const { t } = useI18n()
const props = defineProps<{ validation: ValidationResult | null }>()

const lensRows = computed<LensVerdict[]>(() => props.validation?.layer1 ?? [])
const arbiterRows = computed(() => props.validation?.layer2Summary ?? [])
const isPass = computed(() => props.validation?.gate === 'pass')

function verdictClass(v: string): string {
  if (v === 'approve') return 'v-approve'
  if (v === 'reject') return 'v-reject'
  return 'v-revision'
}
// arbiter objects are loosely typed — pull the readable fields, fall back to JSON.
function arbVerdict(a: unknown): string {
  const o = a as Record<string, unknown>
  return String(o?.verdict ?? o?.gate ?? o?.decision ?? '')
}
function arbReason(a: unknown): string {
  const o = a as Record<string, unknown>
  return String(o?.reasoning ?? o?.notes ?? o?.summary ?? (o?.verdict ? '' : JSON.stringify(a)))
}
</script>

<template>
  <div v-if="!validation" data-test="no-validation" class="muted">
    {{ t('validation.notRun') }}
  </div>
  <div v-else class="validation-panel">
    <!-- Gate banner: the headline verdict + WHY (blocking) right at the top -->
    <section class="gate-banner" :class="isPass ? 'g-pass' : 'g-rev'" data-test="gate">
      <div class="gate-head">
        <span class="gate-ico">{{ isPass ? '✓' : '⚠' }}</span>
        <span class="gate-title">{{ isPass ? t('validation.reviewPassed') : t('validation.sentToRevision') }}</span>
        <span v-if="validation.revision" class="muted small">{{ t('validation.revision', { n: validation.revision }) }}</span>
      </div>
      <div v-if="!isPass && validation.blocking.length" class="blocking">
        <div class="bl-label">{{ t('validation.reasons') }}</div>
        <ul>
          <li v-for="(b, i) in validation.blocking" :key="i" data-test="blocking-item">{{ b }}</li>
        </ul>
      </div>
      <div v-else-if="!isPass" class="muted small">{{ t('validation.gateFailed') }}</div>
      <div v-if="validation.notes" class="notes muted">{{ validation.notes }}</div>
    </section>

    <section class="layer">
      <h4>{{ t('validation.layer1', { n: lensRows.length }) }}</h4>
      <div v-for="lv in lensRows" :key="lv.lens" data-test="lens-row" class="lens-row" :class="verdictClass(lv.verdict)">
        <span class="lens-name">{{ lv.lens }}</span>
        <span class="lens-verdict">{{ lv.verdict }}</span>
        <span class="lens-conf">{{ Math.round(lv.confidence * 100) }}%</span>
        <span class="lens-reason">{{ lv.reasoning }}</span>
      </div>
    </section>

    <section v-if="arbiterRows.length" class="layer">
      <h4>{{ t('validation.layer2', { n: arbiterRows.length }) }}</h4>
      <div v-for="(a, i) in arbiterRows" :key="i" data-test="arbiter-row"
           class="arbiter-row" :class="verdictClass(arbVerdict(a))">
        <span class="lens-verdict">{{ arbVerdict(a) || 'arbiter' }}</span>
        <span class="lens-reason">{{ arbReason(a) }}</span>
      </div>
    </section>
  </div>
</template>

<style scoped>
.validation-panel { display: flex; flex-direction: column; gap: 12px; }
.gate-banner { border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.g-pass { border-color: var(--green, #4caf50); }
.g-rev { border-color: var(--amber, #ffb300); background: rgba(255, 179, 0, 0.06); }
.gate-head { display: flex; align-items: center; gap: 8px; }
.gate-ico { font-size: 15px; }
.g-pass .gate-ico, .g-pass .gate-title { color: var(--green, #4caf50); }
.g-rev .gate-ico, .g-rev .gate-title { color: var(--amber, #ffb300); }
.gate-title { font-weight: 600; }
.blocking { margin-top: 8px; }
.bl-label { font-size: 12px; color: var(--muted); margin-bottom: 2px; }
.blocking ul { margin: 0; padding-left: 18px; }
.blocking li { font-size: 13px; color: var(--text); margin: 2px 0; }
.notes { margin-top: 8px; font-size: 12px; line-height: 1.4; }
.layer h4 { font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); margin: 0 0 6px; }
.lens-row { display: grid; grid-template-columns: 110px 90px 44px 1fr; gap: 8px; padding: 4px 0; font-size: 12px; align-items: baseline; }
.arbiter-row { display: grid; grid-template-columns: 90px 1fr; gap: 8px; padding: 4px 0; font-size: 12px; align-items: baseline; }
.lens-name { font-family: var(--mono); }
.lens-reason { color: var(--text); white-space: pre-wrap; word-break: break-word; }
.v-approve .lens-verdict { color: var(--green, #4caf50); }
.v-revision .lens-verdict { color: var(--amber, #ffb300); }
.v-reject .lens-verdict { color: var(--rose, #e53935); }
.muted { color: var(--muted); }
.small { font-size: 11px; }
</style>
