<script setup lang="ts">
defineProps<{ iter: string; active?: boolean }>()
</script>

<template>
  <span class="iter-chip" :class="{ active }">
    {{ iter }}
  </span>
</template>

<style scoped>
.iter-chip {
  display: inline-flex;
  align-items: center;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1px 6px;
  white-space: nowrap;
  transition: background 0.12s, border-color 0.12s, color 0.12s;
}
.iter-chip:hover {
  background: var(--panel-3);
  border-color: var(--border-2);
  color: var(--text);
}
.iter-chip.active {
  color: var(--primary);
  border-color: var(--primary);
  background: rgba(250, 255, 105, 0.06);
}
</style>
