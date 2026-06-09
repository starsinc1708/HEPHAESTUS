<script setup lang="ts">
import { onMounted, onUnmounted, watch, computed, ref, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useBoardStore } from '@/stores/board'
import { useTaskStore } from '@/stores/task'
import { useToastStore } from '@/stores/toast'
import { api } from '@/api/client'
import type { Item } from '@/types/api'
import { useKeyboardShortcuts, type ShortcutDef } from '@/composables/useKeyboardShortcuts'
import AppShell from '@/components/AppShell.vue'
import KanbanBoard from '@/components/KanbanBoard.vue'
import DepGraph from '@/components/DepGraph.vue'
import TaskDrawer from '@/components/TaskDrawer.vue'
import GoalModal from '@/components/GoalModal.vue'
import ShortcutsHelp from '@/components/ShortcutsHelp.vue'
import CostCard from '@/components/CostCard.vue'
import RunHistoryCard from '@/components/RunHistoryCard.vue'

const route = useRoute()
const { t } = useI18n()
const boardStore = useBoardStore()
const taskStore = useTaskStore()

const activeItem = computed(() => {
  const id = taskStore.activeDrawerTaskId
  if (!id) return null
  return boardStore.items.find(it => it.id === id) ?? null
})

function onTaskClick(id: string) {
  const item = boardStore.items.find(it => it.id === id)
  taskStore.openDrawer(id, 0, item?.lastIter ?? undefined)
}

// Open drawer from route param
watch(() => route.params.id, (id) => {
  if (typeof id === 'string' && id) {
    const item = boardStore.items.find(it => it.id === id)
    taskStore.openDrawer(id, 0, item?.lastIter ?? undefined)
  }
}, { immediate: true })

onMounted(() => {
  boardStore.startPolling(3000)
})

onUnmounted(() => {
  boardStore.stopPolling()
})

async function onReorder(_status: string, ids: string[]) {
  await boardStore.reorderItems(ids)
}

async function onMoveTop(id: string) {
  await boardStore.moveTop(id)
}

async function onRun(id: string) {
  await boardStore.runTask(id)
}

async function onUnqueue(id: string) {
  await boardStore.unqueueTask(id)
}

// Cross-column DnD: pending→queued = send-to-run, queued→pending = un-send.
async function onMove(payload: { id: string; from: string; to: string }) {
  if (payload.from === 'pending' && payload.to === 'queued') {
    await boardStore.runTask(payload.id)
  } else if (payload.from === 'queued' && payload.to === 'pending') {
    await boardStore.unqueueTask(payload.id)
  }
  // other combinations ignored
}

// Search debounce
const searchInput = ref('')
let _debounceTimer: ReturnType<typeof setTimeout> | null = null

watch(searchInput, (val) => {
  if (_debounceTimer !== null) clearTimeout(_debounceTimer)
  _debounceTimer = setTimeout(() => {
    boardStore.filter = val
  }, 300)
})

function clearSearch() {
  searchInput.value = ''
  boardStore.filter = ''
}

// Clickable stats — quick filter by status
const activeStatusFilter = ref<string | null>(null)

// Finished tasks (done/merged) are SHOWN by default so completed work doesn't vanish.
// This toggle optionally HIDES them to declutter a busy board.
const hideFinished = ref(false)

// §5 Board view mode: kanban columns ↔ dependency graph.
const viewMode = ref<'columns' | 'graph'>('columns')

const displayedItems = computed(() => {
  if (!hideFinished.value) return boardStore.filteredItems
  // Hiding finished — but an explicit «Готово»/«Слито» stat filter means those items ARE the point.
  const explicitDone = activeStatusFilter.value === 'done' || activeStatusFilter.value === 'merged'
  if (explicitDone) return boardStore.filteredItems
  return boardStore.filteredItems.filter(it => it.status !== 'done' && it.status !== 'merged')
})

const statusStats = computed(() => [
  { key: t('status.pending'), status: 'pending', value: boardStore.summary.pending },
  { key: t('status.queued'), status: 'queued', value: boardStore.summary.queued },
  { key: t('status.in_progress'), status: 'in_progress', value: boardStore.summary.in_progress },
  { key: t('status.done'), status: 'done', value: boardStore.summary.done },
  { key: t('status.merged'), status: 'merged', value: boardStore.summary.merged },
  { key: t('board.statErrors'), status: 'failed', value: boardStore.summary.failed_total },
])

async function onRequeueFailed() {
  const toast = useToastStore()
  try {
    const res = await api.requeueFailed()
    toast.add('success', t('board.requeued', res.count))
    await boardStore.fetchState()
  } catch (e: unknown) {
    toast.add('error', t('board.requeueError', { error: e instanceof Error ? e.message : String(e) }))
  }
}

function toggleStatusFilter(status: string) {
  if (activeStatusFilter.value === status) {
    activeStatusFilter.value = null
    searchInput.value = ''
    boardStore.filter = ''
  } else {
    activeStatusFilter.value = status
    searchInput.value = status
    boardStore.filter = status
  }
}

// ── UI-006: keyboard shortcuts ──────────────────────────────────────────────
const selectedId = ref<string | null>(null)
const helpOpen = ref(false)
const searchEl = ref<HTMLInputElement | null>(null)
const goalModalRef = ref<InstanceType<typeof GoalModal> | null>(null)

// j/k navigation order. In columns mode follow the visual column layout
// (top-to-bottom within a column, then the next column) so the highlight moves
// predictably; in graph mode fall back to the raw displayed order.
const NAV_STATUS_ORDER = ['pending', 'queued', 'in_progress', 'in_review', 'needs_revision', 'done', 'failed']
const navItems = computed<Item[]>(() => {
  if (viewMode.value === 'graph') return displayedItems.value
  const buckets: Record<string, Item[]> = {}
  for (const s of NAV_STATUS_ORDER) buckets[s] = []
  for (const it of displayedItems.value) {
    const key = it.status.startsWith('failed') ? 'failed' : it.status === 'merged' ? 'done' : it.status
    if (buckets[key]) buckets[key].push(it)
  }
  return NAV_STATUS_ORDER.flatMap(s => buckets[s])
})

function scrollSelectedIntoView() {
  if (!selectedId.value) return
  // Escape only what a double-quoted attribute selector needs; avoids relying on
  // CSS.escape, which isn't present in every environment (e.g. jsdom).
  const safe = selectedId.value.replace(/["\\]/g, '\\$&')
  const el = document.querySelector(`[data-id="${safe}"]`)
  el?.scrollIntoView({ block: 'nearest' })
}

function moveSelection(delta: number) {
  const list = navItems.value
  if (list.length === 0) return
  const cur = selectedId.value ? list.findIndex(i => i.id === selectedId.value) : -1
  let next = cur === -1 ? (delta > 0 ? 0 : list.length - 1) : cur + delta
  next = Math.max(0, Math.min(list.length - 1, next))
  selectedId.value = list[next].id
  nextTick(scrollSelectedIntoView)
}

function openSelected() {
  if (selectedId.value) onTaskClick(selectedId.value)
}

function runSelected() {
  if (!selectedId.value) return
  const item = boardStore.items.find(i => i.id === selectedId.value)
  if (item && (item.status === 'pending' || item.status === 'needs_revision')) {
    boardStore.runTask(item.id)
  }
}

function onEscape() {
  if (helpOpen.value) { helpOpen.value = false; return }
  if (taskStore.activeDrawerTaskId) return // TaskDrawer owns its own Escape→close
  if (selectedId.value) { selectedId.value = null; return }
  if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
}

// descKey '' => alias hidden from the cheat sheet (the bare Enter duplicates `o`).
const SHORTCUTS: { key: string; display: string; descKey: string; handler: (e: KeyboardEvent) => void; allowInInput?: boolean }[] = [
  { key: 'j', display: 'j', descKey: 'shortcuts.next', handler: () => moveSelection(1) },
  { key: 'k', display: 'k', descKey: 'shortcuts.prev', handler: () => moveSelection(-1) },
  { key: 'o', display: 'o / ↵', descKey: 'shortcuts.open', handler: openSelected },
  { key: 'Enter', display: '', descKey: '', handler: openSelected },
  { key: 'r', display: 'r', descKey: 'shortcuts.run', handler: runSelected },
  { key: 'n', display: 'n', descKey: 'shortcuts.newGoal', handler: () => goalModalRef.value?.openModal() },
  { key: '/', display: '/', descKey: 'shortcuts.search', handler: () => searchEl.value?.focus() },
  { key: 'g', display: 'g', descKey: 'shortcuts.toggleView', handler: () => { viewMode.value = viewMode.value === 'columns' ? 'graph' : 'columns' } },
  { key: 'f', display: 'f', descKey: 'shortcuts.toggleFinished', handler: () => { hideFinished.value = !hideFinished.value } },
  { key: '?', display: '?', descKey: 'shortcuts.help', handler: () => { helpOpen.value = !helpOpen.value } },
  { key: 'Escape', display: 'Esc', descKey: 'shortcuts.escape', handler: onEscape, allowInInput: true },
]
// Translated + reactive for the help overlay; blank-descKey rows are hidden.
const helpShortcuts = computed<ShortcutDef[]>(() =>
  SHORTCUTS.filter(s => s.descKey).map(s => ({
    key: s.key, display: s.display, description: t(s.descKey), handler: s.handler, allowInInput: s.allowInInput,
  })),
)
// The listener only reads key/handler/allowInInput, so descriptions are irrelevant here.
useKeyboardShortcuts(SHORTCUTS.map(s => ({
  key: s.key, display: s.display, description: '', handler: s.handler, allowInInput: s.allowInInput,
})))

onUnmounted(() => {
  if (_debounceTimer !== null) clearTimeout(_debounceTimer)
})
</script>

<template>
  <AppShell>
    <template #title>{{ t('nav.board') }}</template>

    <!-- Initial loading state -->
    <div v-if="!boardStore.loaded && boardStore.loading" class="loading-state">
      <span class="loading-spinner" />
      <span>{{ t('board.loading') }}</span>
    </div>

    <!-- Error state on first load -->
    <div v-else-if="!boardStore.loaded && boardStore.lastError" class="error-state">
      <span class="error-icon">⚠</span>
      <span>{{ t('board.loadError', { error: boardStore.lastError }) }}</span>
      <button class="btn btn-sm btn-primary" @click="boardStore.fetchState()">{{ t('board.retry') }}</button>
    </div>

    <!-- Normal board view -->
    <template v-else>
      <GoalModal ref="goalModalRef" @planned="boardStore.fetchState()" />
      <div class="board-toolbar">
        <div class="search-wrapper">
          <input
            ref="searchEl"
            v-model="searchInput"
            type="text"
            class="search-input"
            :placeholder="t('board.searchPlaceholder')"
          />
          <button
            v-if="searchInput.length > 0"
            class="search-clear"
            :aria-label="t('board.clearSearch')"
            @click="clearSearch"
          >✕</button>
        </div>
        <div class="board-stats">
          <button
            v-for="s in statusStats"
            :key="s.key"
            class="stat"
            :class="{ 'stat-active': activeStatusFilter === s.status }"
            @click="toggleStatusFilter(s.status)"
          >
            {{ s.key }}: <strong>{{ s.value }}</strong>
          </button>
          <span v-if="!boardStore.isConnected" class="stat stat-error">{{ t('board.noConnection') }}</span>
        </div>
        <button
          v-if="boardStore.summary.failed_total > 0"
          class="stat"
          data-test="requeue-failed"
          @click="onRequeueFailed"
        >{{ t('board.requeueFailed') }}</button>
        <div class="view-mode" data-test="board-view-mode">
          <button
            class="stat"
            :class="{ 'stat-active': viewMode === 'columns' }"
            @click="viewMode = 'columns'"
          >{{ t('board.columns') }}</button>
          <button
            class="stat"
            :class="{ 'stat-active': viewMode === 'graph' }"
            @click="viewMode = 'graph'"
          >{{ t('board.graph') }}</button>
        </div>
        <button
          class="stat history-toggle"
          :class="{ 'stat-active': hideFinished }"
          data-test="board-history-filter"
          @click="hideFinished = !hideFinished"
        >
          {{ hideFinished ? t('board.showFinished') : t('board.hideFinished') }}
        </button>
        <button
          class="stat shortcuts-btn"
          :title="t('board.shortcutsTitle')"
          :aria-label="t('board.shortcutsAria')"
          data-test="shortcuts-btn"
          @click="helpOpen = true"
        >⌨</button>
      </div>
      <div class="board-layout">
        <div class="board-main">
          <DepGraph
            v-if="viewMode === 'graph'"
            :items="displayedItems"
            @task-click="onTaskClick"
          />
          <KanbanBoard
            v-else
            :items="displayedItems"
            :selected-id="selectedId"
            @task-click="onTaskClick"
            @reorder="onReorder"
            @move-top="onMoveTop"
            @run="onRun"
            @unqueue="onUnqueue"
            @move="onMove"
          />
        </div>
        <aside class="board-sidebar">
          <CostCard />
          <RunHistoryCard />
        </aside>
      </div>
    </template>

    <TaskDrawer :item="activeItem" @close="taskStore.closeDrawer()" />
    <ShortcutsHelp :open="helpOpen" :shortcuts="helpShortcuts" @close="helpOpen = false" />
  </AppShell>
</template>

<style scoped>
.board-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
}

.search-wrapper {
  position: relative;
  width: 280px;
}

.search-input {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 7px 30px 7px 12px;
  color: var(--text);
  font-family: var(--mono);
  font-size: 12px;
  outline: none;
  width: 100%;
}
.search-input::placeholder { color: var(--muted-soft); }
.search-input:focus { border-color: var(--primary); }

.search-clear {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: var(--muted);
  font-size: 12px;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 3px;
  line-height: 1;
}
.search-clear:hover { color: var(--text); background: var(--panel-3); }

.board-stats {
  display: flex;
  gap: 8px;
  font-size: 11px;
  color: var(--muted);
  font-family: var(--mono);
}
.board-stats strong { color: var(--text); }

.stat {
  background: none;
  border: 1px solid transparent;
  border-radius: 4px;
  padding: 2px 8px;
  cursor: pointer;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
  transition: background 0.12s, border-color 0.12s, color 0.12s;
}
.stat:hover {
  background: var(--panel-2);
}
.stat-active {
  background: var(--panel-2);
  border-color: var(--primary);
  color: var(--primary);
}
.stat-active strong { color: var(--primary); }

.stat-error {
  color: var(--rose);
}

.view-mode {
  display: flex;
  gap: 4px;
  margin-left: auto;
}
.view-mode .stat {
  border: 1px solid var(--border);
}

.history-toggle {
  border: 1px solid var(--border);
}

.shortcuts-btn {
  border: 1px solid var(--border);
  font-size: 13px;
  line-height: 1;
}

.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 60px 0;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 14px;
}

.loading-spinner {
  display: inline-block;
  width: 18px;
  height: 18px;
  border: 2px solid var(--border);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.error-state {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--rose);
  font-family: var(--mono);
  font-size: 12px;
}

.error-icon {
  font-size: 16px;
}

.btn {
  font-family: var(--mono);
  font-size: 12px;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 5px 12px;
  cursor: pointer;
  background: var(--panel-2);
  color: var(--text);
  transition: background 0.12s;
}
.btn:hover { background: var(--panel-3); }
.btn-sm { font-size: 11px; padding: 4px 10px; }
.btn-primary { border-color: var(--primary); color: var(--primary); }

.board-layout {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}
.board-main {
  flex: 1;
  min-width: 0;
}
.board-sidebar {
  width: 260px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
</style>
