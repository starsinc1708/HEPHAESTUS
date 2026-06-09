<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ItemStatus } from '@/types/api'

const props = defineProps<{ status: ItemStatus }>()
const { t, te } = useI18n()

// Colour/background per status; the label comes from the shared status.* catalog.
const STYLE_MAP: Record<string, { color: string; bg: string }> = {
  pending:        { color: 'var(--text)',  bg: 'var(--border)' },
  queued:         { color: 'var(--cyan)',  bg: 'rgba(34,211,238,0.12)' },
  in_progress:    { color: 'var(--amber)', bg: 'rgba(251,191,36,0.12)' },
  done:           { color: 'var(--green)', bg: 'rgba(52,211,153,0.12)' },
  merged:         { color: 'var(--green)', bg: 'rgba(52,211,153,0.18)' },
  needs_revision: { color: 'var(--amber)', bg: 'rgba(251,191,36,0.12)' },
  discarded:      { color: 'var(--muted)', bg: 'var(--border)' },
}

const info = computed(() => {
  if (props.status.startsWith('failed')) {
    return { label: t('status.failed'), color: 'var(--rose)', bg: 'rgba(248,113,113,0.12)' }
  }
  const style = STYLE_MAP[props.status] ?? { color: 'var(--text)', bg: 'var(--border)' }
  const key = `status.${props.status}`
  return { label: te(key) ? t(key) : props.status, ...style }
})
</script>

<template>
  <span
    class="status-badge"
    :style="{ color: info.color, background: info.bg, borderColor: info.color }"
  >
    {{ info.label }}
  </span>
</template>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  padding: 2px 7px;
  border-radius: 4px;
  border: 1px solid transparent;
  white-space: nowrap;
  animation: badge-fadein 0.2s ease;
}

@keyframes badge-fadein {
  from { opacity: 0; transform: translateY(-2px); }
  to   { opacity: 1; transform: translateY(0); }
}
</style>
