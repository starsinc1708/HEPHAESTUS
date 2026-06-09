<script setup lang="ts">
// Action-buttons footer extracted from TaskDrawer (maintainability — TaskDrawer was >1000
// lines). Presentational: all business logic stays in the parent; this emits intent events.
import { useI18n } from 'vue-i18n'
import type { Item } from '@/types/api'
import MergeButton from './MergeButton.vue'

const { t } = useI18n()

defineProps<{
  item: Item | null
  actionLoading: string | null
  canRun: boolean
  canUnqueue: boolean
  canMoveTop: boolean
  canRequeue: boolean
  runTitle?: string
}>()

defineEmits<{
  run: []
  unqueue: []
  'move-top': []
  requeue: []
  delete: []
  'open-conversation': []
  merged: []
}>()
</script>

<template>
  <div class="drawer-actions">
    <MergeButton
      v-if="item?.branch && (item.status === 'done' || item.status === 'in_review')"
      :branch="item.branch"
      @merged="$emit('merged')"
    />
    <button
      v-if="item?.id"
      class="action-btn action-conversation"
      data-test="drawer-conversation"
      :title="t('drawerActions.conversationsTitle')"
      @click="$emit('open-conversation')"
    >
      {{ t('drawerActions.conversations') }}
    </button>
    <button
      v-if="canRun"
      class="action-btn action-run"
      data-test="drawer-run"
      :title="runTitle"
      :disabled="!!actionLoading"
      @click="$emit('run')"
    >
      <span v-if="actionLoading === 'run'" class="action-spinner" />
      {{ t('drawerActions.run') }}
    </button>
    <button
      v-if="canUnqueue"
      class="action-btn action-unqueue"
      data-test="drawer-unqueue"
      :disabled="!!actionLoading"
      @click="$emit('unqueue')"
    >
      <span v-if="actionLoading === 'unqueue'" class="action-spinner" />
      {{ t('drawerActions.unqueue') }}
    </button>
    <button
      class="action-btn action-move-top"
      :disabled="!canMoveTop || !!actionLoading"
      @click="$emit('move-top')"
    >
      <span v-if="actionLoading === 'moveTop'" class="action-spinner" />
      {{ t('drawerActions.top') }}
    </button>
    <button
      class="action-btn action-requeue"
      :disabled="!canRequeue || !!actionLoading"
      @click="$emit('requeue')"
    >
      <span v-if="actionLoading === 'requeue'" class="action-spinner" />
      {{ t('drawerActions.reorder') }}
    </button>
    <button
      class="action-btn action-delete"
      :disabled="!!actionLoading"
      @click="$emit('delete')"
    >
      <span v-if="actionLoading === 'delete'" class="action-spinner" />
      {{ t('drawerActions.delete') }}
    </button>
  </div>
</template>

<style scoped>
.drawer-actions {
  display: flex;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}
.action-btn {
  font-family: var(--mono);
  font-size: 11px;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 6px 12px;
  cursor: pointer;
  background: var(--panel-2);
  color: var(--text);
  transition: background 0.12s, opacity 0.12s;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.action-btn:hover:not(:disabled) { background: var(--panel-3); }
.action-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.action-conversation { border-color: var(--violet); color: var(--violet); }
.action-run { border-color: var(--cyan); color: var(--cyan); }
.action-unqueue { border-color: var(--muted); color: var(--muted); }
.action-move-top { border-color: var(--blue); color: var(--blue); }
.action-requeue { border-color: var(--amber); color: var(--amber); }
.action-delete { border-color: var(--rose); color: var(--rose); margin-left: auto; }
.action-spinner {
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 1.5px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
