<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Item } from '@/types/api'
import StatusBadge from './StatusBadge.vue'
import OrderBadge from './OrderBadge.vue'
import { useBoardStore } from '@/stores/board'
import { byId, unfinishedDeps, unfinishedAncestors } from '@/composables/deps'

const props = defineProps<{ item: Item; selected?: boolean }>()
const { t } = useI18n()

// Need all items to resolve cross-column dep statuses (deps may live in other columns).
const boardStore = useBoardStore()
const depMap = computed(() => byId(boardStore.items))

// §6 «ждёт» badge — the unfinished DIRECT deps of a queued task.
const waitingFor = computed(() =>
  props.item.status === 'queued' ? unfinishedDeps(props.item, depMap.value) : [],
)
// §6 «+N предпосылок» run tooltip — transitive unfinished-ancestor count.
const ancestorCount = computed(() => unfinishedAncestors(props.item.id, depMap.value).length)
const runTitle = computed(() =>
  ancestorCount.value > 0 ? t('taskCard.prereqs', ancestorCount.value) : undefined,
)

const emit = defineEmits<{
  click: []
  'move-top': [id: string]
  run: [id: string]
  unqueue: [id: string]
}>()

const severityInfo = computed(() => {
  const s = props.item.severity
  if (!s) return null
  const map: Record<string, { label: string; color: string }> = {
    bug:      { label: 'bug',      color: 'var(--rose)' },
    security: { label: 'security', color: '#fb923c' },
    perf:     { label: 'perf',     color: 'var(--blue)' },
    quality:  { label: 'quality',  color: 'var(--cyan)' },
    test:     { label: 'test',     color: 'var(--violet)' },
    docs:     { label: 'docs',     color: 'var(--muted)' },
  }
  return map[s] ?? { label: s, color: 'var(--muted)' }
})

const borderClass = computed(() => {
  const s = props.item.status
  if (s === 'in_progress') return 'border-in-progress'
  if (s === 'done') return 'border-done'
  if (s === 'merged') return 'border-merged'
  if (s.startsWith('failed')) return 'border-failed'
  if (s === 'needs_revision') return 'border-needs-revision'
  if (s === 'queued') return 'border-queued'
  if (s === 'pending') return 'border-pending'
  return 'border-default'
})

const isRunning = computed(() => props.item.status === 'in_progress')
const isPending = computed(() => props.item.status === 'pending')
const canRun = computed(() => props.item.status === 'pending' || props.item.status === 'needs_revision')
const isQueued = computed(() => props.item.status === 'queued')

const depsCount = computed(() => (props.item.dependsOn ?? []).length)
const blocksCount = computed(() => (props.item.blocks ?? []).length)
const depsTitle = computed(() => t('taskCard.requires', { ids: (props.item.dependsOn ?? []).join(', ') || '—' }))
const blocksTitle = computed(() => t('taskCard.blocks', { ids: (props.item.blocks ?? []).join(', ') || '—' }))

function onMoveTop(e: MouseEvent) {
  e.stopPropagation()
  emit('move-top', props.item.id)
}

function onRun(e: MouseEvent) {
  e.stopPropagation()
  emit('run', props.item.id)
}

function onUnqueue(e: MouseEvent) {
  e.stopPropagation()
  emit('unqueue', props.item.id)
}
</script>

<template>
  <div
    class="task-card"
    :class="[borderClass, { running: isRunning, 'kbd-selected': selected }]"
    tabindex="0"
    @click="emit('click')"
    @keydown.enter="emit('click')"
  >
    <div class="card-head">
      <span class="task-id">{{ item.id }}</span>
      <StatusBadge :status="item.status" />
    </div>
    <div class="card-title">{{ item.title }}</div>
    <div class="card-footer">
      <OrderBadge :order-index="item.orderIndex ?? 0" :conflict-group="item.conflictGroup ?? null" />
      <span v-if="depsCount" class="dep-chip dep-in" :title="depsTitle">dep {{ depsCount }}</span>
      <span v-if="blocksCount" class="dep-chip dep-out" :title="blocksTitle">blk {{ blocksCount }}</span>
      <span v-if="item.complexity" class="complexity-badge" :class="'complexity-' + item.complexity" data-test="complexity-badge">
        {{ item.complexity }}
      </span>
      <span v-if="severityInfo" class="severity-chip" :style="{ color: severityInfo.color, borderColor: severityInfo.color }">
        {{ severityInfo.label }}
      </span>
      <span v-if="isRunning" class="agent-name">
        <span class="pulse-dot" />
        {{ item.agent_override ?? '—' }}
      </span>
      <span v-if="item.attempts > 1" class="attempts">×{{ item.attempts }}</span>
    </div>
    <div
      v-if="waitingFor.length"
      class="waiting-badge"
      data-test="waiting-badge"
      :title="t('taskCard.waitingTitle', { ids: waitingFor.join(', ') })"
    >
      {{ t('taskCard.waiting', { ids: waitingFor.join(', ') }) }}
    </div>
    <div v-if="canRun || isQueued" class="card-actions">
      <button
        v-if="canRun"
        class="card-action card-action-run"
        data-test="card-run"
        :title="runTitle"
        @click="onRun"
      >{{ t('taskCard.run') }}</button>
      <button
        v-if="isQueued"
        class="card-action card-action-unqueue"
        data-test="card-unqueue"
        @click="onUnqueue"
      >{{ t('taskCard.unqueue') }}</button>
    </div>
    <button
      v-if="isPending"
      class="quick-promote"
      :title="t('taskCard.moveTop')"
      @click="onMoveTop"
    >⬆</button>
  </div>
</template>

<style scoped>
.task-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-left: 3px solid var(--border);
  border-radius: 6px;
  padding: 10px 12px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, transform 0.1s;
  position: relative;
}
.task-card:hover {
  border-color: var(--border-2);
  box-shadow: 0 2px 8px rgba(0,0,0,0.3);
}
.task-card:active {
  transform: scale(0.98);
}
.task-card:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}
/* UI-006: keyboard-selected card (j/k navigation) */
.task-card.kbd-selected {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px var(--primary);
}

.border-pending       { border-left-color: var(--blue); }
.border-queued        { border-left-color: var(--cyan); }
.border-in-progress   { border-left-color: var(--amber); }
.border-needs-revision{ border-left-color: var(--primary); }
.border-done          { border-left-color: var(--green); }
.border-merged        { border-left-color: var(--green); }
.border-failed        { border-left-color: var(--rose); }
.border-default       { border-left-color: var(--border-2); }

.running {
  box-shadow: 0 0 12px rgba(251,191,36,0.08);
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin-bottom: 6px;
}

.task-id {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-title {
  font-size: 13px;
  line-height: 1.4;
  color: var(--text);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin-bottom: 8px;
}

.card-footer {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.severity-chip {
  font-family: var(--mono);
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 1px 5px;
  border: 1px solid;
  border-radius: 3px;
}

.complexity-badge {
  font-family: var(--mono);
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 1px 5px;
  border: 1px solid;
  border-radius: 3px;
}
.complexity-simple  { color: var(--green);  border-color: var(--green); }
.complexity-medium  { color: var(--amber);  border-color: var(--amber); }
.complexity-complex { color: var(--rose);   border-color: var(--rose); }

.dep-chip {
  font-family: var(--mono);
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--panel-2);
}
.dep-in { color: var(--blue); }
.dep-out { color: var(--rose); }

.agent-name {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--mono);
  font-size: 10px;
  color: var(--amber);
}

.pulse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--amber);
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.4; transform: scale(0.7); }
}

.attempts {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
  margin-left: auto;
}

.waiting-badge {
  margin-top: 6px;
  font-family: var(--mono);
  font-size: 9px;
  color: var(--amber);
  background: rgba(251, 191, 36, 0.12);
  border: 1px solid rgba(251, 191, 36, 0.3);
  border-radius: 3px;
  padding: 2px 6px;
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-actions {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}
.card-action {
  font-family: var(--mono);
  font-size: 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 3px 8px;
  cursor: pointer;
  background: var(--panel-2);
  transition: background 0.12s, border-color 0.12s;
}
.card-action:hover { background: var(--panel-3); }
.card-action-run { border-color: var(--cyan); color: var(--cyan); }
.card-action-unqueue { border-color: var(--muted); color: var(--muted); }

.quick-promote {
  position: absolute;
  top: 6px;
  right: 6px;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--blue);
  font-size: 11px;
  cursor: pointer;
  padding: 2px 5px;
  opacity: 0;
  transition: opacity 0.15s, background 0.12s;
  line-height: 1;
}
.task-card:hover .quick-promote {
  opacity: 1;
}
.quick-promote:hover {
  background: var(--panel-3);
}
</style>
