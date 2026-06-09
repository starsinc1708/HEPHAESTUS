<script setup lang="ts">
import { ref, watch, computed, nextTick, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ParsedEvent } from '@/types/api'

const props = defineProps<{
  iterDir: string | null
  stream?: string
  active: boolean   // only hold an open SSE connection while the tab is visible
  streamUrl?: string
}>()
const { t } = useI18n()

type Status = 'idle' | 'connecting' | 'streaming' | 'done' | 'error'
const status = ref<Status>('idle')
// keyed by event idx so a reconnect (server re-streams from 0) dedupes instead of duplicating
const byIdx = ref<Map<number, ParsedEvent>>(new Map())
const events = computed(() => [...byIdx.value.values()].sort((a, b) => a.idx - b.idx))

let es: EventSource | null = null
let lastDir: string | null = null   // only reset events when the iteration actually changes
const scroller = ref<HTMLElement | null>(null)
const stick = ref(true)   // auto-scroll unless the user scrolled up

function onScroll() {
  const el = scroller.value
  if (!el) return
  stick.value = el.scrollHeight - el.scrollTop - el.clientHeight < 40
}
function scrollToEnd() {
  if (!stick.value) return
  void nextTick(() => { const el = scroller.value; if (el) el.scrollTop = el.scrollHeight })
}

function close() {
  if (es) { es.close(); es = null }
}

function connect() {
  close()
  if (!props.streamUrl && !props.iterDir) { byIdx.value = new Map(); lastDir = null; status.value = 'idle'; return }
  // Keep already-streamed events when the parent re-renders / re-polls the same iteration
  // (a poll replaces the item object → watch re-fires); only wipe on a genuinely new iter.
  const effectiveDir = props.streamUrl ?? props.iterDir
  if (effectiveDir !== lastDir) { byIdx.value = new Map(); lastDir = effectiveDir }
  status.value = 'connecting'
  const url = props.streamUrl
    ?? `/api/iter/${encodeURIComponent(props.iterDir!)}/stream?stream=${props.stream ?? 'primary'}`
  if (typeof EventSource === 'undefined') { status.value = 'error'; return }
  es = new EventSource(url)
  es.onopen = () => { if (status.value !== 'done') status.value = 'streaming' }
  es.onmessage = (e) => {
    try {
      const ev = JSON.parse(e.data) as ParsedEvent
      byIdx.value.set(ev.idx, ev)
      status.value = 'streaming'
      scrollToEnd()
    } catch { /* ignore malformed frame */ }
  }
  es.addEventListener('done', () => { status.value = 'done'; close() })
  es.onerror = () => {
    // EventSource auto-reconnects; only surface an error if we never got anything
    if (status.value !== 'done') status.value = byIdx.value.size ? 'streaming' : 'error'
  }
}

watch(() => [props.active, props.iterDir, props.streamUrl], () => {
  if (props.active && (props.streamUrl || props.iterDir)) connect()
  else close()
}, { immediate: true })

onBeforeUnmount(close)

const KIND_LABEL = computed(() => ({
  tool_call: t('agents.liveConsole.kindToolCall'),
  tool_result: t('agents.liveConsole.kindToolResult'),
  reasoning: t('agents.liveConsole.kindReasoning'),
  text: t('agents.liveConsole.kindText'),
  session: t('agents.liveConsole.kindSession'),
  finish: t('agents.liveConsole.kindFinish'),
  raw: t('agents.liveConsole.kindRaw'),
}))
function bodyOf(e: ParsedEvent): string {
  if (e.kind === 'tool_call') return `${e.tool ?? ''} ${e.args_preview ?? ''}`.trim()
  if (e.kind === 'tool_result') return (e.output_preview ?? e.text ?? '').trim()
  return (e.text ?? '').trim()
}
</script>

<template>
  <div class="live">
    <div class="live-bar">
      <span class="dot" :class="status" />
      <span class="st-label">{{
        status === 'streaming' ? t('agents.liveConsole.streaming')
        : status === 'connecting' ? t('agents.liveConsole.connecting')
        : status === 'done' ? t('agents.liveConsole.done')
        : status === 'error' ? t('agents.liveConsole.error')
        : t('agents.liveConsole.idle')
      }}</span>
      <span class="muted small">{{ events.length }} {{ t('agents.liveConsole.events') }} · {{ stream ?? 'primary' }}</span>
    </div>

    <div ref="scroller" class="term" @scroll="onScroll">
      <div v-for="e in events" :key="e.idx" class="row" :class="'k-' + e.kind">
        <span class="ic">{{ e.icon || KIND_LABEL[e.kind] || '·' }}</span>
        <span class="kd">{{ KIND_LABEL[e.kind] ?? e.kind }}</span>
        <span class="bd">{{ bodyOf(e) || '—' }}</span>
        <span v-if="e.kind === 'tool_result' && e.status" class="rc" :class="e.status">{{ e.status }}</span>
      </div>
      <div v-if="!events.length && status !== 'connecting'" class="muted empty">
        {{ status === 'error' ? t('agents.liveConsole.streamUnavailable') : t('agents.liveConsole.noEvents') }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.live { display: flex; flex-direction: column; height: 100%; min-height: 320px; gap: 8px; }
.live-bar { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.st-label { color: var(--text); }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
.dot.streaming { background: var(--green, #4caf50); animation: pulse 1.4s ease-in-out infinite; }
.dot.connecting { background: var(--amber, #ffb300); animation: pulse 1.4s ease-in-out infinite; }
.dot.done { background: var(--blue, #4aa3ff); }
.dot.error { background: var(--rose, #e5484d); }
@keyframes pulse { 0%,100% { opacity: 1 } 50% { opacity: .3 } }

.term {
  flex: 1; overflow: auto; background: #0b0d10; border: 1px solid var(--border);
  border-radius: 6px; padding: 8px 10px; font-family: var(--mono);
  font-size: 12px; line-height: 1.55; max-height: 60vh;
}
.row { display: flex; gap: 8px; align-items: baseline; padding: 1px 0; white-space: pre-wrap; word-break: break-word; }
.ic { flex-shrink: 0; width: 16px; text-align: center; }
.kd { flex-shrink: 0; width: 44px; color: var(--muted); font-size: 10px; text-transform: uppercase; }
.bd { flex: 1; color: #d6dee6; }
.rc { flex-shrink: 0; font-size: 10px; padding: 0 5px; border-radius: 3px; }
.rc.ok, .rc.success { color: var(--green, #4caf50); }
.rc.error, .rc.failed { color: var(--rose, #e5484d); }
.k-tool_call .bd { color: #7fd1ff; }
.k-tool_call .ic { color: #4aa3ff; }
.k-reasoning .bd { color: #9aa6b2; font-style: italic; }
.k-finish .bd { color: var(--green, #4caf50); }
.k-finish .ic { color: var(--green, #4caf50); }
.k-session .bd, .k-raw .bd { color: #6b7682; }
.muted { color: var(--muted); }
.small { font-size: 11px; }
.empty { padding: 12px 4px; }
</style>
