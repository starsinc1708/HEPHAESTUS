<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ConversationMessage } from '@/types/api'
import { renderMarkdown } from '@/utils/markdown'

const { t } = useI18n()
const props = defineProps<{
  messages: ConversationMessage[]
  loading?: boolean
  streaming?: boolean
  title?: string
}>()

// Never hang the DOM on a giant stream: render only the last MAX_RENDER.
const MAX_RENDER = 800

const truncated = computed(() => props.messages.length > MAX_RENDER)
// offset = how many leading messages we dropped (so indices stay globally stable
// and our expand/collapse Sets keep pointing at the right message).
const offset = computed(() => (truncated.value ? props.messages.length - MAX_RENDER : 0))
const shown = computed(() =>
  truncated.value ? props.messages.slice(offset.value) : props.messages,
)

// Controlled (not native <details>) so jsdom tests are deterministic. Keyed by the
// message's GLOBAL index so the toggle survives the truncation slice.
const expandedThinking = ref<Set<number>>(new Set())
const expandedTools = ref<Set<number>>(new Set())

function toggle(set: Set<number>, idx: number): void {
  // reassign so Vue's reactivity for Set mutation is unambiguous
  const next = new Set(set)
  if (next.has(idx)) next.delete(idx)
  else next.add(idx)
  if (set === expandedThinking.value) expandedThinking.value = next
  else expandedTools.value = next
}

function roleLabel(role: string | null | undefined): string {
  return role === 'user' ? t('conversation.user') : t('conversation.assistant')
}

function toolInputPreview(input: unknown): string {
  if (input == null) return ''
  let s: string
  if (typeof input === 'string') s = input
  else {
    try { s = JSON.stringify(input) } catch { s = String(input) }
  }
  s = s.replace(/\s+/g, ' ').trim()
  return s.length > 80 ? s.slice(0, 80) + '…' : s
}

function prettyInput(input: unknown): string {
  if (input == null) return ''
  try { return JSON.stringify(input, null, 2) } catch { return String(input) }
}

function tokenParts(tokens: Record<string, number>): string {
  const parts: string[] = []
  if (tokens.input != null) parts.push(`↑${tokens.input}`)
  if (tokens.output != null) parts.push(`↓${tokens.output}`)
  if (tokens.reasoning != null) parts.push(`💭${tokens.reasoning}`)
  return parts.join(' ')
}
</script>

<template>
  <div class="conv-pane" data-test="conv-pane">
    <div v-if="title || streaming" class="pane-head">
      <span v-if="title" class="title">{{ title }}</span>
      <span v-if="streaming" class="streaming">
        <span class="dot" />
        <span class="st-label">{{ t('conversation.agentWorking') }}</span>
      </span>
    </div>

    <div v-if="loading && !messages.length" class="state muted" data-test="conv-loading">{{ t('conversation.loading') }}</div>
    <div v-else-if="!messages.length" class="state muted" data-test="conv-empty">{{ t('conversation.empty') }}</div>

    <template v-else>
      <div v-if="truncated" class="trunc muted" data-test="conv-truncated">
        {{ t('conversation.showingLast', { shown: MAX_RENDER, total: messages.length }) }}
      </div>

      <div class="msgs">
        <template v-for="(m, i) in shown" :key="offset + i">
          <!-- text -->
          <div
            v-if="m.kind === 'text'"
            class="msg msg-text"
            :class="m.role === 'user' ? 'is-user' : 'is-assistant'"
            data-test="msg-text"
          >
            <div class="role-label">{{ roleLabel(m.role) }}</div>
            <!-- renderMarkdown is the DOMPurify XSS gate; never v-html raw text -->
            <div class="markdown-body" v-html="renderMarkdown(m.text)" />
            <div v-if="m.tokens" class="tokens muted" data-test="msg-tokens">{{ tokenParts(m.tokens) }}</div>
          </div>

          <!-- thinking -->
          <div v-else-if="m.kind === 'thinking'" class="msg msg-thinking" data-test="msg-thinking">
            <div
              class="think-head"
              data-test="msg-thinking-toggle"
              role="button"
              tabindex="0"
              :aria-expanded="expandedThinking.has(offset + i)"
              @click="toggle(expandedThinking, offset + i)"
              @keydown.enter.prevent="toggle(expandedThinking, offset + i)"
              @keydown.space.prevent="toggle(expandedThinking, offset + i)"
            >
              <span class="caret">{{ expandedThinking.has(offset + i) ? '▾' : '▸' }}</span>
              <span>{{ t('conversation.thinking') }}</span>
            </div>
            <pre
              v-if="expandedThinking.has(offset + i)"
              class="think-body"
              data-test="msg-thinking-body"
            >{{ m.thinking }}</pre>
            <div v-if="m.tokens" class="tokens muted" data-test="msg-tokens">{{ tokenParts(m.tokens) }}</div>
          </div>

          <!-- tool -->
          <div v-else-if="m.kind === 'tool'" class="msg msg-tool" data-test="msg-tool">
            <div
              class="tool-head"
              data-test="msg-tool-toggle"
              role="button"
              tabindex="0"
              :aria-expanded="expandedTools.has(offset + i)"
              @click="toggle(expandedTools, offset + i)"
              @keydown.enter.prevent="toggle(expandedTools, offset + i)"
              @keydown.space.prevent="toggle(expandedTools, offset + i)"
            >
              <span class="caret">{{ expandedTools.has(offset + i) ? '▾' : '▸' }}</span>
              <span class="tool-name">🔧 {{ m.tool?.name ?? 'tool' }}</span>
              <span class="tool-preview muted">{{ toolInputPreview(m.tool?.input) }}</span>
            </div>
            <div v-if="expandedTools.has(offset + i)" class="tool-body" data-test="msg-tool-body">
              <div v-if="m.tool?.input != null" class="tool-section">
                <div class="tool-section-label muted">{{ t('conversation.toolInput') }}</div>
                <pre class="code">{{ prettyInput(m.tool?.input) }}</pre>
              </div>
              <div v-if="m.tool?.output != null" class="tool-section">
                <div class="tool-section-label muted">{{ t('conversation.toolOutput') }}</div>
                <pre class="code">{{ m.tool?.output }}</pre>
              </div>
            </div>
            <div v-if="m.tokens" class="tokens muted" data-test="msg-tokens">{{ tokenParts(m.tokens) }}</div>
          </div>

          <!-- tool_result (orphan / unpaired) -->
          <div v-else-if="m.kind === 'tool_result'" class="msg msg-tool msg-tool-result" data-test="msg-tool-result">
            <div class="tool-head static">
              <span class="tool-name">{{ t('conversation.result') }}</span>
            </div>
            <pre class="code">{{ m.tool?.output ?? '' }}</pre>
            <div v-if="m.tokens" class="tokens muted" data-test="msg-tokens">{{ tokenParts(m.tokens) }}</div>
          </div>
        </template>
      </div>
    </template>
  </div>
</template>

<style scoped>
.conv-pane {
  display: flex;
  flex-direction: column;
  gap: 8px;
  height: 100%;
  overflow-y: auto;
  font-family: var(--sans);
  font-size: 13px;
  color: var(--text);
}
.pane-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  background: var(--panel);
  z-index: 1;
}
.title {
  font-weight: 600;
  font-size: 13px;
}
.streaming {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--green);
}
.streaming .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--green);
  animation: pulse 1.4s ease-in-out infinite;
}
@keyframes pulse { 0%, 100% { opacity: 1 } 50% { opacity: 0.3 } }
.st-label { color: var(--green); }

.state {
  padding: 16px 8px;
  font-size: 12px;
}
.trunc {
  padding: 6px 8px;
  font-size: 11px;
  font-style: italic;
}
.msgs {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 0 4px 8px;
}

.msg {
  border-radius: 6px;
}
.msg-text {
  padding: 8px 12px;
  border-left: 3px solid var(--border-2);
  background: var(--panel);
}
.msg-text.is-user {
  border-left-color: var(--blue);
}
.msg-text.is-assistant {
  border-left-color: var(--violet);
}
.role-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
  margin-bottom: 4px;
}

.markdown-body {
  line-height: 1.55;
  word-break: break-word;
}
.markdown-body :deep(pre) {
  background: #0b0d10;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
  overflow-x: auto;
  font-family: var(--mono);
  font-size: 12px;
}
.markdown-body :deep(code) {
  font-family: var(--mono);
  font-size: 12px;
}
.markdown-body :deep(a) { color: var(--cyan); }
.markdown-body :deep(p) { margin: 4px 0; }

.msg-thinking,
.msg-tool {
  border: 1px solid var(--border);
  background: var(--panel-2);
  padding: 6px 8px;
}

.think-head,
.tool-head {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
}
.tool-head.static { cursor: default; }
.think-head:focus-visible,
.tool-head:focus-visible {
  outline: 1px solid var(--border-2);
  border-radius: 4px;
}
.caret {
  flex-shrink: 0;
  width: 12px;
  color: var(--muted);
  font-size: 10px;
}
.think-head { color: var(--violet); font-style: italic; }
.tool-name { color: var(--cyan); font-family: var(--mono); }
.tool-preview {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--mono);
  font-size: 11px;
}

.think-body {
  margin: 6px 0 0;
  padding: 6px 8px;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.5;
  color: #9aa6b2;
  background: #0b0d10;
  border-radius: 6px;
}

.tool-body {
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.tool-section-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 2px;
}
.code {
  margin: 0;
  padding: 8px 10px;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.5;
  color: #d6dee6;
  background: #0b0d10;
  border: 1px solid var(--border);
  border-radius: 6px;
  max-height: 360px;
  overflow: auto;
}
.msg-tool-result .code { margin-top: 6px; }

.tokens {
  margin-top: 6px;
  font-family: var(--mono);
  font-size: 10px;
}
.muted { color: var(--muted); }
</style>
