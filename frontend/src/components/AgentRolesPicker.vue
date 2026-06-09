<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Connection, RoleConnections } from '@/types/api'

const props = defineProps<{
  connections: Connection[]
  modelValue: RoleConnections
  warnings?: string[]
}>()
const emit = defineEmits<{ 'update:modelValue': [RoleConnections] }>()
const { t } = useI18n()

const VALIDATOR_COUNT = 5
const ARBITER_COUNT = 2
const SINGLE_ROLES = [
  { key: 'primary', label: 'primary' },
  { key: 'fallback', label: 'fallback' },
  { key: 'planner', label: 'planner' },
  { key: 'final', label: 'final' },
  { key: 'merge', label: 'merge' },
] as const
type SingleRole = (typeof SINGLE_ROLES)[number]['key']

// Apply-all source selection.
const applyAllSource = ref('')

function disabledHint(c: Connection): string {
  if (c.status === 'failed') return t('agents.roles.errorHint')
  if (c.status === 'untested') return t('agents.roles.untestedHint')
  return ''
}

function optionLabel(c: Connection): string {
  return `${c.label} — ${c.provider}/${c.model}${disabledHint(c)}`
}

function cloneValue(): RoleConnections {
  const v = props.modelValue
  return {
    primary: v.primary ?? null,
    fallback: v.fallback ?? null,
    planner: v.planner ?? null,
    final: v.final ?? null,
    merge: v.merge ?? null,
    validators: [...(v.validators ?? [])],
    arbiters: [...(v.arbiters ?? [])],
  }
}

function single(role: SingleRole): string {
  return (props.modelValue[role] as string | null | undefined) ?? ''
}

function setSingle(role: SingleRole, value: string) {
  const next = cloneValue()
  next[role] = value || null
  emit('update:modelValue', next)
}

function listVal(which: 'validators' | 'arbiters', i: number): string {
  return (props.modelValue[which] ?? [])[i] ?? ''
}

function setList(which: 'validators' | 'arbiters', i: number, value: string, count: number) {
  const next = cloneValue()
  const arr = [...(next[which] ?? [])]
  while (arr.length < count) arr.push('')
  arr[i] = value
  next[which] = arr
  emit('update:modelValue', next)
}

function applyAll() {
  const id = applyAllSource.value
  if (!id) return
  emit('update:modelValue', {
    primary: id, fallback: id, planner: id, final: id, merge: id,
    validators: Array(VALIDATOR_COUNT).fill(id),
    arbiters: Array(ARBITER_COUNT).fill(id),
  })
}

// only connected connections are selectable; others are rendered disabled.
function isDisabled(c: Connection): boolean {
  return c.status !== 'connected'
}
const connectedConnections = computed(() => props.connections.filter(c => c.status === 'connected'))
</script>

<template>
  <section class="card">
    <h3>{{ t('agents.roles.title') }}</h3>
    <p class="muted small">
      {{ t('agents.roles.hint') }}
    </p>

    <div v-if="warnings && warnings.length" class="warning" data-test="role-warning">
      {{ t('agents.roles.notFound', { warnings: warnings.join(', ') }) }}
    </div>

    <!-- apply to all -->
    <div class="apply-all">
      <select class="input mini" v-model="applyAllSource" data-test="roles-apply-all-select">
        <option value="">{{ t('agents.roles.selectConnection') }}</option>
        <option v-for="c in connectedConnections" :key="c.id" :value="c.id">{{ optionLabel(c) }}</option>
      </select>
      <button class="btn mini" data-test="roles-apply-all" :disabled="!applyAllSource" @click="applyAll">
        {{ t('agents.roles.applyAll') }}
      </button>
    </div>

    <!-- single roles -->
    <div class="role-grid">
      <label v-for="r in SINGLE_ROLES" :key="r.key" class="role">
        <span class="role-name">{{ r.label }}</span>
        <select class="input mini" :value="single(r.key)" :data-test="`role-${r.key}`"
                @change="setSingle(r.key, ($event.target as HTMLSelectElement).value)">
          <option value="">{{ t('agents.roles.defaultOption') }}</option>
          <option v-for="c in connections" :key="c.id" :value="c.id" :disabled="isDisabled(c)">
            {{ optionLabel(c) }}
          </option>
        </select>
      </label>
    </div>

    <!-- validators -->
    <div class="role-block">
      <span class="role-name">validators</span>
      <div class="list-grid">
        <select v-for="i in VALIDATOR_COUNT" :key="`v${i}`" class="input mini"
                :value="listVal('validators', i - 1)" :data-test="`role-validators-${i - 1}`"
                @change="setList('validators', i - 1, ($event.target as HTMLSelectElement).value, VALIDATOR_COUNT)">
          <option value="">{{ t('agents.roles.defaultOption') }}</option>
          <option v-for="c in connections" :key="c.id" :value="c.id" :disabled="isDisabled(c)">
            {{ optionLabel(c) }}
          </option>
        </select>
      </div>
    </div>

    <!-- arbiters -->
    <div class="role-block">
      <span class="role-name">arbiters</span>
      <div class="list-grid">
        <select v-for="i in ARBITER_COUNT" :key="`a${i}`" class="input mini"
                :value="listVal('arbiters', i - 1)" :data-test="`role-arbiters-${i - 1}`"
                @change="setList('arbiters', i - 1, ($event.target as HTMLSelectElement).value, ARBITER_COUNT)">
          <option value="">{{ t('agents.roles.defaultOption') }}</option>
          <option v-for="c in connections" :key="c.id" :value="c.id" :disabled="isDisabled(c)">
            {{ optionLabel(c) }}
          </option>
        </select>
      </div>
    </div>
  </section>
</template>

<style scoped>
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.card h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin: 0 0 8px; }
.muted { color: var(--muted); }
.small { font-size: 11px; }
.warning { background: rgba(229, 57, 53, 0.08); border: 1px solid var(--rose, #e53935); color: var(--rose, #e53935); border-radius: 6px; padding: 8px 10px; font-size: 12px; margin: 8px 0; }
.apply-all { display: flex; align-items: center; gap: 8px; margin: 12px 0; }
.role-grid { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
.role { display: flex; align-items: center; gap: 10px; }
.role-name { font-family: var(--mono); font-size: 12px; color: var(--text); min-width: 92px; }
.role-block { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
.list-grid { display: flex; flex-wrap: wrap; gap: 6px; }
.input { background: var(--panel-2); border: 1px solid var(--border); border-radius: 4px; color: var(--text); font-size: 12px; padding: 6px 10px; outline: none; }
.input:focus { border-color: var(--primary); }
.input.mini { font-size: 11px; padding: 4px 8px; }
.btn { background: var(--panel-2); border: 1px solid var(--border); border-radius: 4px; color: var(--text); font-size: 12px; padding: 6px 12px; cursor: pointer; }
.btn:hover { border-color: var(--primary); }
.btn.mini { font-size: 11px; padding: 4px 8px; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
