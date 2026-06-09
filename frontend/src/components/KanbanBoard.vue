<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Item } from '@/types/api'
import KanbanColumn from './KanbanColumn.vue'

const props = defineProps<{
  items: Item[]
  selectedId?: string | null
}>()

const emit = defineEmits<{
  'task-click': [id: string]
  'reorder': [status: string, ids: string[]]
  'move-top': [id: string]
  'run': [id: string]
  'unqueue': [id: string]
  'move': [payload: { id: string; from: string; to: string }]
}>()

const { t } = useI18n()

const collapsedMap = reactive<Record<string, boolean>>({
  failed: true,
})

// Tag filter
const activeTag = ref<string | null>(null)

const allTags = computed(() => {
  const tags = new Set<string>()
  for (const item of props.items) {
    for (const tag of item.tags ?? []) {
      tags.add(tag)
    }
  }
  return [...tags].sort()
})

function toggleTag(tag: string) {
  activeTag.value = activeTag.value === tag ? null : tag
}

const columns = computed(() => [
  { status: 'pending' as const,        label: t('status.pending'),        color: 'var(--blue)' },
  { status: 'queued' as const,         label: t('status.queued'),         color: 'var(--cyan)' },
  { status: 'in_progress' as const,    label: t('status.in_progress'),    color: 'var(--amber)' },
  { status: 'in_review' as const,      label: t('status.in_review'),      color: 'var(--blue)' },
  { status: 'needs_revision' as const, label: t('status.needs_revision'), color: 'var(--primary)' },
  // «Готово» holds both done and merged — a finished task shows its «Готово»/«Слито» status
  // badge on the card, so they stay distinguishable without a separate column.
  { status: 'done' as const,           label: t('status.done'),           color: 'var(--green)' },
  { status: 'failed' as const,         label: t('status.failed'),         color: 'var(--rose)' },
])

const allCollapsed = computed(() =>
  columns.value.every(col => collapsedMap[col.status] === true)
)

function toggleColumn(status: string) {
  collapsedMap[status] = !collapsedMap[status]
}

function toggleAll() {
  const newState = !allCollapsed.value
  for (const col of columns.value) {
    collapsedMap[col.status] = newState
  }
}

function getItems(status: string): Item[] {
  let result: Item[]
  if (status === 'failed') {
    result = props.items.filter(it => it.status.startsWith('failed'))
  } else if (status === 'done') {
    // The «Готово» column aggregates finished work: done (verified) + merged.
    result = props.items.filter(it => it.status === 'done' || it.status === 'merged')
  } else {
    result = props.items.filter(it => it.status === status)
  }
  if (activeTag.value) {
    result = result.filter(it => (it.tags ?? []).includes(activeTag.value!))
  }
  return result
}

function onReorder(ids: string[]) {
  emit('reorder', 'pending', ids)
}
</script>

<template>
  <div class="kanban-board-wrapper">
    <div v-if="allTags.length" class="tag-filter-bar" data-test="tag-filter-bar">
      <button
        v-for="tag in allTags"
        :key="tag"
        class="tag-filter-btn"
        :class="{ active: activeTag === tag }"
        data-test="tag-filter-btn"
        @click="toggleTag(tag)"
      >{{ tag }}</button>
    </div>
    <div class="kanban-board">
      <KanbanColumn
        v-for="col in columns"
        :key="col.status"
        :status="col.status"
        :label="col.label"
        :color="col.color"
        :items="getItems(col.status)"
        :selected-id="selectedId"
        :collapsed="!!collapsedMap[col.status]"
        :draggable="col.status === 'pending' || col.status === 'queued'"
        :group="(col.status === 'pending' || col.status === 'queued') ? 'runnable' : undefined"
        @task-click="emit('task-click', $event)"
        @toggle-collapse="toggleColumn(col.status)"
        @reorder="onReorder"
        @move-top="emit('move-top', $event)"
        @run="emit('run', $event)"
        @unqueue="emit('unqueue', $event)"
        @move="emit('move', $event)"
      />
    </div>
  </div>
</template>

<style scoped>
.kanban-board-wrapper {
  height: calc(100vh - 130px);
  display: flex;
  flex-direction: column;
}

.tag-filter-bar {
  display: flex;
  gap: 6px;
  padding: 6px 0;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.tag-filter-btn {
  font-family: var(--mono);
  font-size: 11px;
  padding: 2px 10px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--panel-2);
  color: var(--muted);
  cursor: pointer;
  transition: all 0.12s;
}
.tag-filter-btn:hover { color: var(--text); border-color: var(--primary); }
.tag-filter-btn.active { background: var(--primary); color: #fff; border-color: var(--primary); }

.kanban-board {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 8px;
  flex: 1;
  min-height: 0;
}

@media (max-width: 1400px) {
  .kanban-board {
    grid-template-columns: repeat(4, 1fr);
  }
}

@media (max-width: 800px) {
  .kanban-board {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 600px) {
  .kanban-board-wrapper {
    height: auto;
  }
  .kanban-board {
    grid-template-columns: 1fr;
  }
}
</style>
