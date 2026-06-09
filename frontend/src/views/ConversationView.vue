<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import type { ConversationAgentRun, ConversationMessage } from '@/types/api'
import { useConversationStore } from '@/stores/conversation'
import ConversationTree from '@/components/ConversationTree.vue'
import ConversationPane from '@/components/ConversationPane.vue'

const props = defineProps<{ id: string }>()
const { t } = useI18n()

const router = useRouter()
const conversationStore = useConversationStore()

// ── Local selection state (NOT in the store) ──
const selected = ref<{ dir: string; agent: ConversationAgentRun } | null>(null)
const messages = ref<ConversationMessage[]>([])
const isStreaming = ref(false)

const selectedKey = computed(() =>
  selected.value ? `${selected.value.dir}::${selected.value.agent.stream}` : null,
)

const iterations = computed(() => conversationStore.tree?.iterations ?? [])

// ── Humanized pane title ──
function roleLabel(role: string): string {
  if (role === 'implementer') return t('conversation.roleImplementer')
  if (role === 'arbiter') return t('conversation.roleArbiter')
  if (role === 'final') return t('conversation.roleFinal')
  if (role.startsWith('validator:')) {
    const lens = role.split(':', 2)[1] ?? ''
    return t('conversation.validator', { lens })
  }
  return role
}
const paneTitle = computed(() => {
  const a = selected.value?.agent
  return a ? `${roleLabel(a.role)} · r${a.revision}` : ''
})

// ── Default selection: last iteration's current implementer (output.primary) ──
function pickDefault(): { dir: string; agent: ConversationAgentRun } | null {
  const iters = iterations.value
  if (!iters.length) return null
  // Search from the LAST iteration backwards for an implement-stage current output.primary.
  for (let i = iters.length - 1; i >= 0; i--) {
    const iter = iters[i]
    for (const stage of iter.stages) {
      if (stage.stage !== 'implement') continue
      const cur = stage.agents.find((a) => a.current && a.stream === 'output.primary')
      if (cur) return { dir: iter.dir, agent: cur }
    }
  }
  // Fallback: first agent of the first iteration that has one.
  for (const iter of iters) {
    for (const stage of iter.stages) {
      if (stage.agents.length) return { dir: iter.dir, agent: stage.agents[0] }
    }
  }
  return null
}

// ── Live-tail (mirror LiveConsole lifecycle discipline) ──
function sseStreamFor(stream: string): string | null {
  if (stream === 'output.primary') return 'primary'
  if (stream === 'output.fallback') return 'fallback'
  return null // archived revisions / validation streams are static (no live SSE)
}

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
  isStreaming.value = false
}

async function refetchSelected(force = false): Promise<void> {
  const sel = selected.value
  if (!sel) return
  const msgs = await conversationStore.fetchMessages(sel.dir, sel.agent.stream, force)
  // Guard against a race where selection changed while awaiting.
  if (selected.value === sel) messages.value = msgs
}

function scheduleRefetch(): void {
  clearDebounce()
  debounceTimer = setTimeout(() => {
    debounceTimer = null
    void refetchSelected(true)
  }, 700)
}

function openStream(dir: string, agent: ConversationAgentRun): void {
  closeStream()
  if (typeof EventSource === 'undefined') return // jsdom / tests → skip live-tail
  if (!agent.current) return
  const sse = sseStreamFor(agent.stream)
  if (!sse) return
  const url = `/api/iter/${encodeURIComponent(dir)}/stream?stream=${sse}`
  es = new EventSource(url)
  isStreaming.value = true
  // SSE frames are truncated ParsedEvents — use only as a "changed" signal.
  es.onmessage = () => { scheduleRefetch() }
  es.addEventListener('done', () => {
    clearDebounce()
    void refetchSelected(true)
    isStreaming.value = false
    if (es) { es.close(); es = null }
  })
  es.onerror = () => {
    // EventSource auto-reconnects; nothing to surface here.
  }
}

// ── Selection ──
async function select(dir: string, agent: ConversationAgentRun): Promise<void> {
  closeStream()
  selected.value = { dir, agent }
  messages.value = await conversationStore.fetchMessages(dir, agent.stream)
  openStream(dir, agent)
}

function onTreeSelect(payload: { dir: string; agent: ConversationAgentRun }): void {
  void select(payload.dir, payload.agent)
}

// ── Load tree (on mount + when id changes) ──
async function load(): Promise<void> {
  closeStream()
  selected.value = null
  messages.value = []
  await conversationStore.loadTree(props.id)
  const def = pickDefault()
  if (def) await select(def.dir, def.agent)
}

watch(() => props.id, () => { void load() }, { immediate: true })

function goBack(): void {
  router.push({ name: 'board-task', params: { id: props.id } })
}

onBeforeUnmount(() => {
  closeStream()
  conversationStore.clear()
})
</script>

<template>
  <div class="conv-view" data-test="conv-view">
    <header class="conv-header">
      <button class="back-btn" data-test="conv-back" @click="goBack">{{ t('conversation.backToBoard') }}</button>
      <span class="task-id">{{ id }}</span>
    </header>

    <div
      v-if="conversationStore.loadingTree && !conversationStore.tree"
      class="conv-state muted"
      data-test="conv-tree-loading"
    >
      {{ t('conversation.loadingConversations') }}
    </div>

    <div
      v-else-if="!iterations.length"
      class="conv-state muted"
      data-test="conv-tree-empty"
    >
      {{ t('conversation.noConversations') }}
    </div>

    <div v-else class="conv-body">
      <aside class="conv-side">
        <ConversationTree
          :iterations="iterations"
          :selected-key="selectedKey"
          @select="onTreeSelect"
        />
      </aside>
      <main class="conv-main">
        <ConversationPane
          :messages="messages"
          :loading="conversationStore.loadingMessages"
          :streaming="isStreaming"
          :title="paneTitle"
        />
      </main>
    </div>
  </div>
</template>

<style scoped>
.conv-view {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  color: var(--text);
  font-family: var(--sans);
}
.conv-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--panel);
  flex-shrink: 0;
}
.back-btn {
  font-family: var(--mono);
  font-size: 12px;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 5px 10px;
  cursor: pointer;
  background: var(--panel-2);
  color: var(--text);
  transition: background 0.12s;
}
.back-btn:hover { background: var(--panel-3); }
.task-id {
  font-family: var(--mono);
  font-size: 13px;
  font-weight: 600;
}
.conv-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
}
.conv-body {
  flex: 1;
  display: flex;
  min-height: 0;
}
.conv-side {
  width: 320px;
  flex-shrink: 0;
  overflow-y: auto;
  border-right: 1px solid var(--border);
  padding: 12px 8px;
  background: var(--panel);
}
.conv-main {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 12px 16px;
}
.muted { color: var(--muted); }
</style>
