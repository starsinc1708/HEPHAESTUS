<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Item } from '@/types/api'
import { api } from '@/api/client'
import { useLoopStore } from '@/stores/loop'
import LiveConsole from '@/components/LiveConsole.vue'
import StatusBadge from '@/components/StatusBadge.vue'

const loopStore = useLoopStore()
const { t } = useI18n()

const driver = computed(() => loopStore.driver)

// Auto-driver status indicator text (Sub-project #3).
const indicatorText = computed(() => {
  const d = driver.value
  if (d.paused) return t('agents.controls.paused')
  if (d.process.state === 'running') {
    return t('agents.controls.running', { inProgress: d.inProgress, queued: d.queued })
  }
  return t('agents.controls.idle')
})

// ---- live running tasks (loop monitor) ----
const items = ref<Item[]>([])
let timer: ReturnType<typeof setInterval> | null = null

const running = computed(() =>
  items.value.filter(i => i.status === 'in_progress' && i.lastIter))

async function refresh() {
  try {
    const s = await api.getState()
    items.value = s.items
  } catch { /* keep last */ }
}

onMounted(() => {
  // Driver/loop polling is owned by AppShell (the persistent root); here we just READ
  // loopStore.driver and keep our own live-running-tasks grid fresh.
  void refresh()
  timer = setInterval(refresh, 2500)   // pick up newly-started / finished tasks
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="run">
    <!-- auto-driver status + pause/resume toggle (Sub-project #3) -->
    <div class="run-controls">
      <div class="state">
        <span
          class="driver-indicator"
          :class="{ 'is-running': driver.process.state === 'running' && !driver.paused, 'is-paused': driver.paused }"
          data-test="driver-indicator"
        >
          <span class="dot" />
          {{ indicatorText }}
        </span>
      </div>
      <div class="control-btns">
        <button
          v-if="driver.paused"
          class="btn btn-primary"
          data-test="driver-toggle"
          @click="loopStore.resumeDriver()"
        >{{ t('agents.controls.resume') }}</button>
        <button
          v-else-if="driver.process.state === 'running'"
          class="btn btn-warn"
          data-test="driver-toggle"
          @click="loopStore.pauseDriver()"
        >{{ t('agents.controls.stop') }}</button>
        <button
          class="btn btn-danger"
          data-test="loop-kill"
          @click="loopStore.killDriver()"
        >{{ t('agents.controls.kill') }}</button>
      </div>
    </div>

    <!-- live running tasks -->
    <div class="running">
      <div class="hdr">
        <span class="count">{{ running.length }}</span>
        <span class="muted">{{ running.length === 1 ? t('agents.controls.taskRunning') : t('agents.controls.tasksRunning') }}</span>
      </div>

      <div v-if="!running.length" class="empty muted">
        {{ t('agents.controls.noRunning') }}
      </div>

      <div v-else class="grid">
        <section v-for="it in running" :key="it.id" class="run-card">
          <header class="rc-head">
            <StatusBadge :status="it.status" />
            <span class="rc-title" :title="it.title">{{ it.title || it.id }}</span>
            <span class="rc-iter mono muted">{{ it.lastIter }}</span>
          </header>
          <LiveConsole :iter-dir="it.lastIter ?? null" :active="true" stream="primary" />
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.run { display: flex; flex-direction: column; gap: 16px; }

.run-controls {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px;
}
.state { display: flex; align-items: center; gap: 8px; }
.driver-indicator {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 13px; font-weight: 600; color: var(--muted);
}
.driver-indicator .dot {
  width: 8px; height: 8px; border-radius: 50%; background: var(--muted); flex-shrink: 0;
}
.driver-indicator.is-running { color: var(--green); }
.driver-indicator.is-running .dot { background: var(--green); animation: driver-pulse 1.5s ease-in-out infinite; }
.driver-indicator.is-paused { color: var(--amber); }
.driver-indicator.is-paused .dot { background: var(--amber); }
@keyframes driver-pulse {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.4; }
}
.control-btns { display: flex; gap: 8px; }
.btn {
  font-family: var(--mono); font-size: 12px; border: 1px solid var(--border);
  border-radius: 4px; padding: 6px 14px; cursor: pointer; background: var(--panel-2); color: var(--text);
}
.btn:hover { background: var(--panel-3); }
.btn-primary { border-color: var(--primary); color: var(--primary); }
.btn-warn { border-color: var(--amber); color: var(--amber); }
.btn-danger { border-color: var(--rose); color: var(--rose); }

.running { display: flex; flex-direction: column; gap: 14px; }
.hdr { display: flex; align-items: baseline; gap: 8px; }
.count { font-size: 22px; font-weight: 700; color: var(--primary); font-family: var(--mono); }
.muted { color: var(--muted); }
.empty { padding: 24px 8px; font-size: 13px; }
.grid {
  display: grid; gap: 14px;
  grid-template-columns: repeat(auto-fit, minmax(440px, 1fr));
}
.run-card {
  background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
  padding: 12px; display: flex; flex-direction: column; gap: 8px; min-height: 380px;
}
.rc-head { display: flex; align-items: center; gap: 8px; min-width: 0; }
.rc-title { font-weight: 600; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
.rc-iter { font-size: 11px; flex-shrink: 0; }
.mono { font-family: var(--mono); }
</style>
