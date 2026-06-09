<script setup lang="ts">
import { nextTick, ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import { useToastStore } from '@/stores/toast'
import { useAgentJob } from '@/composables/useAgentJob'
import LiveConsole from '@/components/LiveConsole.vue'

const { t } = useI18n()
const toast = useToastStore()

interface Turn {
  role: 'user' | 'assistant'
  content: string
}

const turns = ref<Turn[]>([])
const question = ref('')
const sending = ref(false)
const sessionId = ref<string | undefined>(undefined)
const streamUrl = ref<string | undefined>(undefined)
const streaming = ref(false)

const rebuildJob = useAgentJob()
const rebuilding = computed(() => rebuildJob.status.value === 'running')

const transcript = ref<HTMLElement | null>(null)

async function scrollDown() {
  await nextTick()
  if (transcript.value) transcript.value.scrollTop = transcript.value.scrollHeight
}

async function sendInsight() {
  const q = question.value.trim()
  if (!q || sending.value) return

  turns.value.push({ role: 'user', content: q })
  question.value = ''
  sending.value = true
  streaming.value = false
  streamUrl.value = undefined
  await scrollDown()

  try {
    const res = await api.askInsights(q, sessionId.value)
    if (res.ok) {
      sessionId.value = res.sessionId
      if (res.iterDir) {
        streamUrl.value = `/api/v1/insights/${encodeURIComponent(res.iterDir)}/stream`
        streaming.value = true
      }
      turns.value.push({ role: 'assistant', content: res.answer })
      await scrollDown()
    } else {
      toast.add('error', t('tools.insightsChat.answerError'))
    }
  } catch (e: unknown) {
    toast.add('error', t('tools.error', { error: e instanceof Error ? e.message : String(e) }))
  } finally {
    sending.value = false
    // keep streaming console visible until next question; do not reset streamUrl here
  }
}

async function rebuildMap() {
  await rebuildJob.run(() => api.rebuildMap())

  if (rebuildJob.status.value === 'done' && rebuildJob.result.value) {
    toast.add('success', t('tools.insightsChat.mapRebuilt', { count: rebuildJob.result.value.count }))
  } else if (rebuildJob.status.value === 'failed') {
    toast.add('error', t('tools.insightsChat.mapRebuildError', { error: rebuildJob.error.value ?? '' }))
  }
}

function onEnter(e: KeyboardEvent) {
  if (!e.shiftKey) {
    e.preventDefault()
    void sendInsight()
  }
}
</script>

<template>
  <div class="insights-chat">
    <!-- Toolbar -->
    <div class="chat-toolbar">
      <span class="chat-title">{{ t('tools.insightsChat.title') }}</span>
      <button
        class="btn btn-secondary"
        data-test="rebuild-map"
        :disabled="rebuilding"
        @click="rebuildMap"
      >
        <span v-if="rebuilding" class="btn-spinner" />
        {{ rebuilding ? t('tools.insightsChat.rebuilding') : t('tools.insightsChat.rebuildBtn') }}
      </button>
    </div>

    <!-- Transcript -->
    <div ref="transcript" class="chat-transcript">
      <div v-if="turns.length === 0" class="chat-empty">
        {{ t('tools.insightsChat.empty') }}
      </div>
      <div
        v-for="(turn, idx) in turns"
        :key="idx"
        class="chat-turn"
        :class="'turn-' + turn.role"
        :data-test="turn.role === 'assistant' ? 'assistant-bubble' : 'user-bubble'"
      >
        <span class="turn-role">{{ turn.role === 'user' ? t('tools.insightsChat.userRole') : t('tools.insightsChat.assistantRole') }}</span>
        <span class="turn-content">{{ turn.content }}</span>
      </div>

      <!-- Live rebuild-map stream -->
      <div v-if="rebuilding && rebuildJob.streamUrl.value" class="chat-stream">
        <LiveConsole
          :iter-dir="null"
          :active="true"
          :stream-url="rebuildJob.streamUrl.value"
        />
      </div>

      <!-- Live investigation stream (shown while waiting or after last answer) -->
      <div v-if="streamUrl" class="chat-stream">
        <LiveConsole
          :iter-dir="null"
          :active="true"
          :stream-url="streamUrl"
        />
      </div>

      <!-- Thinking indicator -->
      <div v-if="sending" class="chat-thinking">
        <span class="thinking-dot" />
        <span class="thinking-dot" />
        <span class="thinking-dot" />
      </div>
    </div>

    <!-- Input area -->
    <div class="chat-input-area">
      <textarea
        v-model="question"
        class="chat-input"
        rows="2"
        :placeholder="t('tools.insightsChat.placeholder')"
        :disabled="sending"
        @keydown.enter="onEnter"
      />
      <button
        class="btn btn-primary"
        data-test="send-insight"
        :disabled="sending || !question.trim()"
        @click="sendInsight"
      >
        <span v-if="sending" class="btn-spinner" />
        {{ sending ? t('tools.insightsChat.sending') : t('tools.insightsChat.sendBtn') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.insights-chat {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 0;
}

.chat-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0 12px;
  flex-shrink: 0;
}

.chat-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  font-family: var(--mono);
}

.chat-transcript {
  flex: 1;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 0 12px;
  min-height: 200px;
  max-height: 60vh;
}

.chat-empty {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--muted);
  padding: 16px 0;
}

.chat-turn {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 85%;
}

.turn-user {
  align-self: flex-end;
  align-items: flex-end;
}

.turn-assistant {
  align-self: flex-start;
  align-items: flex-start;
}

.turn-role {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.turn-content {
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.5;
  padding: 8px 12px;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
}

.turn-user .turn-content {
  background: color-mix(in srgb, var(--primary) 12%, var(--panel-2));
  border: 1px solid color-mix(in srgb, var(--primary) 30%, transparent);
  color: var(--text);
}

.turn-assistant .turn-content {
  background: var(--panel-2);
  border: 1px solid var(--border);
  color: var(--text);
}

.chat-stream {
  margin-top: 4px;
}

.chat-thinking {
  display: flex;
  gap: 4px;
  align-items: center;
  padding: 8px 0;
}

.thinking-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--muted);
  animation: blink 1.4s ease-in-out infinite;
}
.thinking-dot:nth-child(2) { animation-delay: 0.2s; }
.thinking-dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes blink { 0%, 80%, 100% { opacity: 0.2; } 40% { opacity: 1; } }

.chat-input-area {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  flex-shrink: 0;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}

.chat-input {
  flex: 1;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-family: var(--mono);
  font-size: 12px;
  padding: 8px 10px;
  outline: none;
  resize: vertical;
  transition: border-color 0.15s;
}
.chat-input:focus { border-color: var(--primary); }
.chat-input:disabled { opacity: 0.6; }

.btn {
  font-family: var(--mono);
  font-size: 12px;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 6px 14px;
  cursor: pointer;
  background: var(--panel-2);
  color: var(--text);
  transition: background 0.12s, opacity 0.12s;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.btn:hover:not(:disabled) { background: var(--panel-3, var(--panel)); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { border-color: var(--primary); color: var(--primary); }
.btn-secondary { border-color: var(--blue, #4aa3ff); color: var(--blue, #4aa3ff); }

.btn-spinner {
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 1.5px solid var(--border);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
