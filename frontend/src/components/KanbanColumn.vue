<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Item, ItemStatus } from '@/types/api'
import TaskCard from './TaskCard.vue'
import Sortable from 'sortablejs'

const props = defineProps<{
  status: ItemStatus | 'failed'
  label: string
  color: string
  items: Item[]
  collapsed?: boolean
  draggable?: boolean
  group?: string
  selectedId?: string | null
}>()

const emit = defineEmits<{
  'task-click': [id: string]
  'toggle-collapse': []
  'reorder': [items: string[]]
  'move-top': [id: string]
  'run': [id: string]
  'unqueue': [id: string]
  'move': [payload: { id: string; from: string; to: string }]
}>()

const { t } = useI18n()
const bodyRef = ref<HTMLElement | null>(null)
let sortable: Sortable | null = null

const columnIcon = computed(() => {
  const map: Record<string, string> = {
    pending: '◉',
    queued: '➤',
    in_progress: '◎',
    needs_revision: '✎',
    done: '✓',
    merged: '⤓',
    failed: '✗',
  }
  return map[props.status] ?? '·'
})

const emptyMessage = computed(() => {
  const keys: Record<string, string> = {
    pending: 'kanban.empty.pending',
    queued: 'kanban.empty.queued',
    in_progress: 'kanban.empty.in_progress',
    needs_revision: 'kanban.empty.needs_revision',
    done: 'kanban.empty.done',
    merged: 'kanban.empty.merged',
    failed: 'kanban.empty.failed',
  }
  return t(keys[props.status] ?? 'kanban.empty.default')
})

onMounted(async () => {
  if (!props.draggable) return
  await nextTick()
  if (!bodyRef.value) return
  sortable = Sortable.create(bodyRef.value, {
    animation: 200,
    handle: '.task-card',
    direction: 'vertical',
    group: props.group ? { name: props.group } : undefined,
    // No meaningful intra-column order for the queued column, but it can still
    // send/receive across the group (drag in/out of «К запуску»).
    sort: props.status !== 'queued',
    // Stage 2: pending-column order → reorder; cross-column → move (send-to-run / un-send).
    onEnd: (evt) => {
      const fromS = (evt.from as HTMLElement | undefined)?.dataset.status
      const toS = (evt.to as HTMLElement | undefined)?.dataset.status
      const id = (evt.item as HTMLElement | undefined)?.dataset.id
      if (!id) return
      if (fromS === toS) {
        // Same-column reorder — only pending has meaningful order. SortableJS's DOM
        // move matches the data here (no ghost), so we keep it and just sync order.
        if (fromS === 'pending') {
          const ids = sortable?.toArray() ?? []
          if (ids.length > 0) emit('reorder', ids)
        }
        return
      }
      // Cross-column drag → send-to-run / un-send. Revert SortableJS's DOM mutation
      // (it physically moved the card into the destination column) BEFORE emitting:
      // let the store's optimistic status change + Vue's reactive re-render move the
      // card, so Vue stays the single source of truth. This kills the ghost/duplicate
      // card and leaves nothing stranded on a failed-API rollback.
      const from = evt.from as HTMLElement | undefined
      if (from && evt.item) {
        const ref = from.children[evt.oldIndex ?? 0] ?? null
        from.insertBefore(evt.item, ref)
      }
      if (fromS && toS) {
        emit('move', { id, from: fromS, to: toS })
      }
    },
  })
})

onBeforeUnmount(() => {
  sortable?.destroy()
})
</script>

<template>
  <div class="kanban-col" :style="{ '--col-color': color }">
    <div
      class="col-header"
      :aria-label="t('kanban.colAria', { label, count: items.length })"
    >
      <span class="col-icon">{{ columnIcon }}</span>
      <span class="col-label">{{ label }}</span>
      <span class="col-count">{{ items.length }}</span>
      <button
        role="button"
        :aria-label="collapsed ? t('kanban.expand', { label }) : t('kanban.collapse', { label })"
        class="collapse-btn"
        @click="emit('toggle-collapse')"
      >{{ collapsed ? '▸' : '▾' }}</button>
    </div>
    <div v-if="!collapsed" ref="bodyRef" class="col-body" :data-status="status">
      <TaskCard
        v-for="item in items"
        :key="item.id"
        :item="item"
        :selected="item.id === selectedId"
        :data-id="item.id"
        class="task-card"
        @click="emit('task-click', item.id)"
        @move-top="emit('move-top', $event)"
        @run="emit('run', $event)"
        @unqueue="emit('unqueue', $event)"
      />
      <div v-if="items.length === 0" class="col-empty">{{ emptyMessage }}</div>
    </div>
  </div>
</template>

<style scoped>
.kanban-col {
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}

.col-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  cursor: default;
  user-select: none;
  transition: background 0.12s;
}
.col-header:hover {
  background: var(--panel-2);
}

.col-icon {
  color: var(--col-color);
  font-size: 14px;
}

.col-label {
  color: var(--text);
  flex: 1;
}

.col-count {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
  background: var(--panel-2);
  border-radius: 4px;
  padding: 1px 6px;
}

.collapse-btn {
  font-size: 10px;
  color: var(--muted);
  cursor: pointer;
  background: none;
  border: none;
  padding: 2px 4px;
  border-radius: 3px;
  transition: background 0.12s, color 0.12s;
}
.collapse-btn:hover {
  background: var(--panel-2);
  color: var(--text);
}

.col-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  overflow-y: auto;
  max-height: calc(100vh - 180px);
  min-height: 40px;
}

.col-empty {
  text-align: center;
  padding: 20px 0;
  color: var(--muted-soft);
  font-size: 13px;
}
</style>
