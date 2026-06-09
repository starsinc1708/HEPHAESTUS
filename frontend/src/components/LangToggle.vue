<script setup lang="ts">
// UI-001: language switcher (RU/EN). Persists via setLocale(); reactive to the
// current global locale so the active pill always matches.
import { useI18n } from 'vue-i18n'
import { setLocale, type Locale } from '@/i18n'

const { locale } = useI18n()
const LOCALES: { code: Locale; label: string }[] = [
  { code: 'ru', label: 'RU' },
  { code: 'en', label: 'EN' },
]
</script>

<template>
  <div class="lang-toggle" data-test="lang-toggle" role="group" aria-label="Language">
    <button
      v-for="l in LOCALES"
      :key="l.code"
      class="lang-btn"
      :class="{ active: locale === l.code }"
      :data-test="`lang-${l.code}`"
      :aria-pressed="locale === l.code"
      @click="setLocale(l.code)"
    >{{ l.label }}</button>
  </div>
</template>

<style scoped>
.lang-toggle {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: 4px;
  overflow: hidden;
}
.lang-btn {
  font-family: var(--mono);
  font-size: 11px;
  padding: 4px 8px;
  background: var(--panel-2);
  color: var(--muted);
  border: none;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.lang-btn + .lang-btn { border-left: 1px solid var(--border); }
.lang-btn:hover { color: var(--text); }
.lang-btn.active { background: var(--panel-3); color: var(--primary); }
</style>
