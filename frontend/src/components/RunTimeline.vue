<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ParsedEvent } from '@/types/api'

const props = defineProps<{
  attempts: number
  iterDir: string | null
  events?: ParsedEvent[]
}>()
const { t } = useI18n()

const KIND_LABEL = computed(() => ({
  tool_call: t('agents.timeline.toolCall'),
  tool_result: t('agents.timeline.toolResult'),
  reasoning: t('agents.timeline.reasoning'),
  text: t('agents.timeline.text'),
  session: t('agents.timeline.session'),
  finish: t('agents.timeline.finish'),
  raw: t('agents.timeline.raw'),
}))

const rows = computed(() => props.events ?? [])
const t0 = computed(() => {
  const first = rows.value.find(e => e.ts_ms != null)?.ts_ms
  return typeof first === 'number' ? first : null
})

function rel(e: ParsedEvent): string {
  if (e.ts_ms == null || t0.value == null) return ''
  const s = Math.max(0, (e.ts_ms - t0.value) / 1000)
  return s < 60 ? `+${s.toFixed(1)}s` : `+${Math.floor(s / 60)}m${Math.round(s % 60)}s`
}
function line(e: ParsedEvent): string {
  const txt = (e.tool ? `${e.tool} ${e.args_preview ?? ''}` : (e.text ?? '')).trim()
  const oneLine = txt.split('\n')[0]
  return oneLine.length > 140 ? oneLine.slice(0, 140) + '…' : oneLine
}

const revisionLoops = computed(() =>
  Array.from({ length: Math.max(0, props.attempts) }, (_, i) => i + 1))
</script>

<template>
  <div class="run-timeline">
    <div class="iter-label" v-if="iterDir">{{ iterDir }}</div>

    <div v-if="revisionLoops.length" class="revisions">
      <span class="rev-label">{{ t('agents.timeline.revisions') }}</span>
      <span v-for="r in revisionLoops" :key="r" class="rev-chip">r{{ r }}</span>
    </div>

    <ol v-if="rows.length" class="events">
      <li v-for="e in rows" :key="e.idx" class="ev" :class="'ev-' + e.kind">
        <span class="ev-icon">{{ e.icon || '·' }}</span>
        <div class="ev-body">
          <div class="ev-head">
            <span class="ev-kind">{{ KIND_LABEL[e.kind] ?? e.kind }}</span>
            <span v-if="rel(e)" class="ev-time">{{ rel(e) }}</span>
          </div>
          <div class="ev-text mono">{{ line(e) || '—' }}</div>
        </div>
      </li>
    </ol>
    <div v-else class="empty muted">{{ t('agents.timeline.noEvents') }}</div>
  </div>
</template>

<style scoped>
.run-timeline { display: flex; flex-direction: column; gap: 10px; }
.iter-label { font-family: var(--mono); font-size: 11px; color: var(--muted); }
.revisions { display: flex; align-items: center; gap: 6px; }
.rev-label { font-size: 11px; color: var(--muted); }
.rev-chip { background: var(--amber, #ffb300); color: #000; padding: 1px 6px; border-radius: 4px; font-size: 11px; }
.events { list-style: none; margin: 0; padding: 0; border-left: 2px solid var(--border); }
.ev { display: flex; gap: 8px; padding: 5px 0 5px 10px; position: relative; }
.ev-icon { flex-shrink: 0; width: 18px; text-align: center; font-size: 13px; }
.ev-body { min-width: 0; flex: 1; }
.ev-head { display: flex; gap: 8px; align-items: baseline; }
.ev-kind { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.03em; }
.ev-time { font-family: var(--mono); font-size: 10px; color: var(--muted); }
.ev-text { font-size: 12px; color: var(--text); white-space: pre-wrap; word-break: break-word; }
.ev-tool_call .ev-icon { color: var(--blue, #4aa3ff); }
.ev-finish .ev-icon { color: var(--green, #4caf50); }
.mono { font-family: var(--mono); }
.empty { font-size: 12px; padding: 8px 0; }
.muted { color: var(--muted); }
</style>
