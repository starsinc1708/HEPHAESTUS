<script setup lang="ts">
import { onMounted, onUnmounted, ref, nextTick, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { StateSnapshot } from '@/types/api'
import { api } from '@/api/client'

const { t } = useI18n()

const MAX_LOG_LINES = 1000

const emit = defineEmits<{ (e: 'close'): void }>()

const logLines = ref<string[]>([])
const loading = ref(false)
const viewerRef = ref<HTMLElement | null>(null)
let _timer: ReturnType<typeof setInterval> | null = null

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

async function fetchLogs() {
  try {
    loading.value = true
    const state: StateSnapshot = await api.getState()
    const raw = state.log_tail ?? []
    if (raw.length > MAX_LOG_LINES) {
      logLines.value = raw.slice(raw.length - MAX_LOG_LINES)
    } else {
      logLines.value = raw
    }
  } catch {
    // silent
  } finally {
    loading.value = false
  }
}

function scrollToBottom() {
  void nextTick(() => {
    if (viewerRef.value) {
      viewerRef.value.scrollTop = viewerRef.value.scrollHeight
    }
  })
}

watch(() => logLines.value.length, () => scrollToBottom())

onMounted(() => {
  void fetchLogs().then(() => scrollToBottom())
  _timer = setInterval(() => {
    void fetchLogs()
  }, 3000)
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  if (_timer !== null) {
    clearInterval(_timer)
    _timer = null
  }
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <aside
    class="logs-drawer"
    data-test="logs-drawer"
    role="dialog"
    aria-modal="true"
    :aria-label="t('shell.logs')"
  >
    <header class="drawer-header">
      <span class="drawer-title">{{ t('shell.logs') }}</span>
      <button class="drawer-close" :title="t('shell.logsClose')" @click="$emit('close')">✕</button>
    </header>
    <div ref="viewerRef" class="log-viewer">
      <div v-for="(line, i) in logLines" :key="i" class="log-line">{{ line }}</div>
      <div v-if="logLines.length === 0" class="log-empty">
        {{ loading ? t('shell.logsLoading') : t('shell.logsEmpty') }}
      </div>
    </div>
  </aside>
</template>

<style scoped>
.logs-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 460px;
  max-width: 90vw;
  z-index: 300;
  background: var(--panel);
  border-left: 1px solid var(--border);
  box-shadow: -8px 0 24px rgba(0, 0, 0, 0.35);
  display: flex;
  flex-direction: column;
}

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.drawer-title {
  font-size: 14px;
  font-weight: 600;
}

.drawer-close {
  background: transparent;
  border: none;
  color: var(--muted);
  font-size: 14px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: background 0.12s, color 0.12s;
}
.drawer-close:hover {
  background: var(--panel-2);
  color: var(--text);
}

.log-viewer {
  flex: 1;
  padding: 12px;
  font-family: var(--mono);
  font-size: 11px;
  line-height: 1.6;
  overflow: auto;
}

.log-line {
  color: var(--text);
  padding: 1px 4px;
  white-space: pre-wrap;
  word-break: break-all;
  border-radius: 2px;
}

.log-empty {
  color: var(--muted);
  text-align: center;
  padding: 20px;
}
</style>
