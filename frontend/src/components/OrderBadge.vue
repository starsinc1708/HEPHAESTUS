<script setup lang="ts">
import { useI18n } from 'vue-i18n'
defineProps<{ orderIndex: number; conflictGroup: string | null }>()
const { t } = useI18n()
</script>

<template>
  <span class="order-badge">
    <span class="order-num">#{{ orderIndex + 1 }}</span>
    <span
      v-if="conflictGroup"
      class="conflict-dot"
      :title="t('taskCard.conflict')"
    />
  </span>
</template>

<style scoped>
.order-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
}
.order-num {
  background: var(--panel-2);
  border-radius: 3px;
  padding: 1px 5px;
}
.conflict-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--amber);
}
</style>
