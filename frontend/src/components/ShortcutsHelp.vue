<script setup lang="ts">
// UI-006: keyboard-shortcuts cheat sheet. Rendered from the same ShortcutDef[]
// that drives the listener, so it can never list a key that isn't wired.
import { useI18n } from 'vue-i18n'
import type { ShortcutDef } from '@/composables/useKeyboardShortcuts'

defineProps<{ open: boolean; shortcuts: ShortcutDef[] }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
</script>

<template>
  <div v-if="open" class="sh-overlay" data-test="shortcuts-help" @click.self="emit('close')">
    <div class="sh-modal" role="dialog" aria-modal="true" :aria-label="t('shortcuts.title')">
      <div class="sh-header">
        <h3>{{ t('shortcuts.title') }}</h3>
        <button class="sh-close" :aria-label="t('goal.close')" @click="emit('close')">✕</button>
      </div>
      <ul class="sh-list">
        <li v-for="s in shortcuts" :key="s.display" class="sh-row">
          <kbd class="sh-key">{{ s.display }}</kbd>
          <span class="sh-desc">{{ s.description }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.sh-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 14vh;
  z-index: 60;
}
.sh-modal {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 18px;
  width: min(420px, 92vw);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.4);
}
.sh-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.sh-header h3 {
  margin: 0;
  font-size: 14px;
  color: var(--text);
}
.sh-close {
  background: none;
  border: none;
  color: var(--muted);
  font-size: 14px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
}
.sh-close:hover { color: var(--text); background: var(--panel-2); }
.sh-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sh-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.sh-key {
  flex-shrink: 0;
  min-width: 34px;
  text-align: center;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--primary);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 2px 6px;
}
.sh-desc {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--muted);
}
</style>
