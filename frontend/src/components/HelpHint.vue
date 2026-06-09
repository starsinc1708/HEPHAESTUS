<script setup lang="ts">
defineProps<{ text: string }>()
</script>

<template>
  <span class="help-hint" tabindex="0" data-test="help-hint">
    <span class="help-icon" aria-hidden="true">ⓘ</span>
    <span class="help-tip" role="tooltip">{{ text }}</span>
  </span>
</template>

<style scoped>
.help-hint { position: relative; display: inline-flex; cursor: help; margin-left: 6px; vertical-align: middle; }
.help-icon { color: var(--muted); font-size: 12px; line-height: 1; }
.help-hint:hover .help-icon, .help-hint:focus .help-icon { color: var(--primary); }
.help-tip {
  position: absolute; left: 0; bottom: 150%;
  background: var(--panel-3, #202020); color: var(--text); border: 1px solid var(--border-2, #2f2f2f);
  border-radius: 6px; padding: 8px 10px; width: max-content; max-width: 320px; font-size: 12px;
  line-height: 1.45; z-index: 60; opacity: 0; pointer-events: none; transition: opacity 0.12s;
  white-space: normal; box-shadow: 0 6px 24px rgba(0, 0, 0, 0.4);
}
.help-hint:hover .help-tip, .help-hint:focus .help-tip { opacity: 1; }
</style>
