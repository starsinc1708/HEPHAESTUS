<script setup lang="ts">
// One readable, live-updating view of the implementer's conversation for a single iteration.
// Replaces the old Активность / Инструменты / Таймлайн / Live tabs (all of which showed the same
// `output.primary` event stream, the Live one as raw-JSON rows). Reuses the #5 markdown renderer
// (ConversationPane) and the #5 live-tail discipline (SSE as a "changed" signal → debounced
// refetch of the full, nicely-parsed conversation).
import { ref, watch, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ConversationMessage } from '@/types/api'
import { useConversationStore } from '@/stores/conversation'
import ConversationPane from './ConversationPane.vue'

const { t } = useI18n()

const props = defineProps<{
  iterDir: string | null
  running?: boolean
}>()

const conversationStore = useConversationStore()
const messages = ref<ConversationMessage[]>([])
const streaming = ref(false)

const PRIMARY = 'output.primary'
const FALLBACK = 'output.fallback'

let es: EventSource | null = null
let debounceTimer: ReturnType<typeof setTimeout> | null = null

function clearDebounce(): void {
  if (debounceTimer !== null) {
    clearTimeout(debounceTimer)
    debounceTimer = null
  }
}

function closeStream(): void {
  if (es) {
    es.close()
    es = null
  }
  clearDebounce()
  streaming.value = false
}

async function refetch(force = false): Promise<void> {
  const dir = props.iterDir
  if (!dir) {
    messages.value = []
    return
  }
  let msgs = await conversationStore.fetchMessages(dir, PRIMARY, force)
  // The primary agent may have failed and the fallback agent run instead.
  if (!msgs.length) {
    const fb = await conversationStore.fetchMessages(dir, FALLBACK, force)
    if (fb.length) msgs = fb
  }
  // Guard against a race where the iteration changed while awaiting.
  if (props.iterDir === dir) messages.value = msgs
}

function scheduleRefetch(): void {
  clearDebounce()
  debounceTimer = setTimeout(() => {
    debounceTimer = null
    void refetch(true)
  }, 700)
}

function openStream(): void {
  closeStream()
  if (!props.running || !props.iterDir) return
  if (typeof EventSource === 'undefined') return // jsdom / tests → static only
  const url = `/api/iter/${encodeURIComponent(props.iterDir)}/stream?stream=primary`
  es = new EventSource(url)
  streaming.value = true
  es.onmessage = () => { scheduleRefetch() }
  es.addEventListener('done', () => {
    clearDebounce()
    void refetch(true)
    streaming.value = false
    if (es) { es.close(); es = null }
  })
  es.onerror = () => { /* EventSource auto-reconnects */ }
}

watch(
  () => [props.iterDir, props.running],
  async () => {
    closeStream()
    await refetch()
    openStream()
  },
  { immediate: true },
)

onBeforeUnmount(closeStream)
</script>

<template>
  <ConversationPane
    data-test="dialog-pane"
    :messages="messages"
    :loading="conversationStore.loadingMessages"
    :streaming="streaming"
    :title="t('dialog.title')"
  />
</template>
