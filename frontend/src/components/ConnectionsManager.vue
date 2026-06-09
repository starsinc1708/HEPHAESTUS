<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Connection, ProviderCatalogEntry, Combo, CliInfo } from '@/types/api'
import { api } from '@/api/client'
import { useToastStore } from '@/stores/toast'

const { t } = useI18n()
const toast = useToastStore()
const emit = defineEmits<{ changed: [Connection[]] }>()

const ENGINE_ORDER = ['claude', 'opencode', 'codex'] as const
const ENGINE_LABEL: Record<string, string> = { claude: 'claude', opencode: 'opencode', codex: 'codex' }

const catalog = ref<ProviderCatalogEntry[]>([])
const clis = ref<Record<string, CliInfo>>({})
const connections = ref<Connection[]>([])
const busy = ref(false)
const testingId = ref<string | null>(null)

// add-form state
const provider = ref('')
const engine = ref('')
const authMethod = ref<'subscription' | 'api_key'>('api_key')
const model = ref('')
const key = ref('')
const label = ref('')

// ── Engines panel: a stable row per known engine ──
const engineRows = computed(() =>
  ENGINE_ORDER.map(name => ({
    name,
    info: clis.value[name] ?? { installed: false, version: null, auth: {} },
  })),
)
function isInstalled(engineName: string): boolean {
  return clis.value[engineName]?.installed === true
}

// ── Cascading add-form computeds ──
const activeEntry = computed(() => catalog.value.find(e => e.provider === provider.value) ?? null)

// engines available for the chosen provider, gated to installed CLIs
const engineOptions = computed(() => {
  const combos = activeEntry.value?.combos ?? []
  const seen = new Set<string>()
  const out: string[] = []
  for (const c of combos) {
    if (!seen.has(c.engine) && isInstalled(c.engine)) {
      seen.add(c.engine)
      out.push(c.engine)
    }
  }
  return out
})

// auth methods available for the chosen provider+engine
const authOptions = computed<('subscription' | 'api_key')[]>(() => {
  const combos = activeEntry.value?.combos ?? []
  const out: ('subscription' | 'api_key')[] = []
  for (const c of combos) {
    if (c.engine === engine.value && !out.includes(c.authMethod)) out.push(c.authMethod)
  }
  return out
})

const activeCombo = computed<Combo | null>(() =>
  (activeEntry.value?.combos ?? []).find(
    c => c.engine === engine.value && c.authMethod === authMethod.value,
  ) ?? null,
)
const modelOptions = computed(() => activeCombo.value?.models ?? [])
const loginCmd = computed(() => activeCombo.value?.loginCmd ?? null)

const isOllama = computed(() => provider.value === 'ollama')
const ollamaBaseUrl = ref('http://localhost:11434/v1')

const needsKey = computed(() => authMethod.value === 'api_key')
const canAdd = computed(() =>
  !busy.value && !!provider.value && !!engine.value && !!authMethod.value && !!model.value &&
  (!needsKey.value || key.value.trim().length > 0))

// ── Cascade resets (computed-driven, applied via watchers) ──
function resetModel() {
  model.value = modelOptions.value[0] ?? ''
}
function resetAuth() {
  authMethod.value = authOptions.value[0] ?? 'api_key'
  resetModel()
}
function resetEngine() {
  engine.value = engineOptions.value[0] ?? ''
  resetAuth()
}
function onProviderChange() {
  resetEngine()
}
watch(engine, () => resetAuth())
watch(authMethod, () => resetModel())

function maskedKey(c: Connection): string {
  for (const [k, v] of Object.entries(c.env ?? {})) {
    if (/KEY|TOKEN|SECRET|PASSWORD/i.test(k)) return v
  }
  return '—'
}

async function load() {
  try {
    const [cl, pr, cn] = await Promise.all([
      api.getClis(), api.getConnectionPresets(), api.getConnections(),
    ])
    clis.value = cl.clis
    catalog.value = pr.catalog
    connections.value = cn.connections
    if (!provider.value && catalog.value.length) {
      provider.value = catalog.value[0].provider
      onProviderChange()
    }
  } catch (e: unknown) {
    toast.add('error', e instanceof Error ? e.message : String(e))
  }
}

async function refreshConnections() {
  try {
    connections.value = (await api.getConnections()).connections
    emit('changed', connections.value)
  } catch { /* keep previous list */ }
}

async function addConnection() {
  if (!canAdd.value) return
  busy.value = true
  try {
    await api.createConnection({
      provider: provider.value,
      engine: engine.value,
      authMethod: authMethod.value,
      model: model.value,
      ...(needsKey.value ? { key: key.value.trim() } : {}),
      label: label.value.trim() || undefined,
    })
    key.value = ''
    label.value = ''
    await refreshConnections()
    toast.add('success', t('connections.added'))
  } catch (e: unknown) {
    toast.add('error', e instanceof Error ? e.message : String(e))
  } finally { busy.value = false }
}

async function testConn(c: Connection) {
  testingId.value = c.id
  try {
    const res = await api.testConnection(c.id)
    c.status = res.status
    c.lastError = res.error
    emit('changed', connections.value)
    if (res.status === 'connected') toast.add('success', t('connections.connectedToast', { label: c.label }))
    else toast.add('error', t('connections.errorToast', { label: c.label, error: res.error ?? t('connections.error') }))
  } catch (e: unknown) {
    c.status = 'failed'
    emit('changed', connections.value)
    toast.add('error', e instanceof Error ? e.message : String(e))
  } finally { testingId.value = null }
}

async function delConn(c: Connection) {
  busy.value = true
  try {
    await api.deleteConnection(c.id)
    await refreshConnections()
    toast.add('success', t('connections.deleted'))
  } catch (e: unknown) {
    toast.add('error', e instanceof Error ? e.message : String(e))
  } finally { busy.value = false }
}

onMounted(load)
</script>

<template>
  <section class="card">
    <h3>{{ t('connections.title') }}</h3>
    <p class="muted small">{{ t('connections.intro') }}</p>

    <!-- engines panel: which CLIs are installed -->
    <div class="engines" data-test="engines-panel">
      <div
        v-for="row in engineRows"
        :key="row.name"
        class="engine-row"
        :class="{ off: !row.info.installed }"
        :data-test="`engine-${row.name}`"
      >
        <span class="engine-mark">{{ row.info.installed ? '✓' : '✗' }}</span>
        <b class="mono">{{ ENGINE_LABEL[row.name] }}</b>
        <span v-if="row.info.installed" class="mono muted small">{{ row.info.version ?? '' }}</span>
        <span v-else class="muted small">{{ t('connections.install') }} <code class="mono">{{ row.name }}</code></span>
      </div>
    </div>

    <!-- existing connections -->
    <div class="conn-list">
      <div v-for="c in connections" :key="c.id" class="conn-row" data-test="conn-row">
        <div class="conn-meta">
          <b>{{ c.label }}</b>
          <span class="mono muted small">{{ c.provider }} · {{ c.engine }} · {{ c.model }}</span>
          <span class="mono muted small">
            <template v-if="c.authMethod === 'subscription'">{{ t('connections.subscription') }}</template>
            <template v-else>{{ t('connections.keyLabel', { key: maskedKey(c) }) }}</template>
          </span>
        </div>
        <span
          class="badge badge-auth"
          :class="c.authMethod === 'subscription' ? 'badge-auth-sub' : 'badge-auth-key'"
          data-test="conn-auth-badge"
        >{{ c.authMethod === 'subscription' ? t('connections.subscription') : t('connections.badgeKey') }}</span>
        <span class="badge" :class="`badge-${c.status}`" data-test="conn-status">{{ c.status }}</span>
        <button class="btn mini" data-test="conn-test" :disabled="testingId === c.id" @click="testConn(c)">
          {{ testingId === c.id ? t('connections.testing') : t('connections.test') }}
        </button>
        <button class="btn mini al-remove" data-test="conn-del" :disabled="busy" :title="t('connections.delete')" @click="delConn(c)">✕</button>
      </div>
      <div v-if="!connections.length" class="muted small">{{ t('connections.none') }}</div>
    </div>

    <!-- add form -->
    <div class="add-form">
      <label class="field"><span>{{ t('connections.provider') }}</span>
        <select class="input mini" v-model="provider" data-test="conn-provider" @change="onProviderChange">
          <option v-for="p in catalog" :key="p.provider" :value="p.provider">{{ p.label }}</option>
        </select>
      </label>
      <label class="field"><span>{{ t('connections.engine') }}</span>
        <select class="input mini" v-model="engine" data-test="conn-engine">
          <option v-for="e in engineOptions" :key="e" :value="e">{{ e }}</option>
        </select>
      </label>
      <label class="field"><span>{{ t('connections.authMethod') }}</span>
        <select class="input mini" v-model="authMethod" data-test="conn-auth">
          <option v-for="a in authOptions" :key="a" :value="a">
            {{ a === 'subscription' ? t('connections.authSub') : t('connections.authKey') }}
          </option>
        </select>
      </label>
      <label class="field"><span>{{ t('connections.model') }}</span>
        <select class="input mini" v-model="model" data-test="conn-model">
          <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
        </select>
      </label>
      <label v-if="isOllama" class="field grow"><span>Base URL</span>
        <input class="input mini mono" v-model="ollamaBaseUrl" data-test="ollama-base-url"
               placeholder="http://localhost:11434/v1" />
      </label>
      <label v-if="needsKey" class="field grow"><span>{{ t('connections.keyField') }}</span>
        <input class="input mini mono" type="password" v-model="key" data-test="conn-key" placeholder="sk-… / zk-…" />
      </label>
      <div v-else class="field grow login-hint">
        <span>{{ t('connections.loginField') }}</span>
        <code class="mono" data-test="conn-login-cmd">{{ loginCmd ?? t('connections.loginFallback') }}</code>
      </div>
      <label class="field"><span>{{ t('connections.labelField') }}</span>
        <input class="input mini" v-model="label" :placeholder="t('connections.labelPlaceholder')" />
      </label>
      <button class="btn btn-primary mini" data-test="conn-add" :disabled="!canAdd" @click="addConnection">{{ t('connections.add') }}</button>
    </div>

    <p v-if="activeEntry" class="muted small blurb" data-test="conn-blurb">{{ activeEntry.blurb }}</p>
  </section>
</template>

<style scoped>
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.card h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin: 0 0 8px; }
.muted { color: var(--muted); }
.small { font-size: 11px; }
.mono { font-family: var(--mono); }
.engines { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 4px; }
.engine-row { display: flex; align-items: center; gap: 6px; padding: 4px 10px; border: 1px solid var(--border); border-radius: 14px; font-size: 12px; }
.engine-row .engine-mark { font-weight: 700; color: var(--emerald, #2e7d32); }
.engine-row.off { opacity: 0.55; }
.engine-row.off .engine-mark { color: var(--rose, #e53935); }
.engine-row code { background: var(--panel-2); padding: 1px 4px; border-radius: 3px; }
.conn-list { display: flex; flex-direction: column; gap: 6px; margin: 12px 0; }
.conn-row { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; }
.conn-meta { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.conn-meta .mono { overflow: hidden; text-overflow: ellipsis; }
.badge { font-size: 11px; text-transform: uppercase; padding: 2px 8px; border-radius: 10px; border: 1px solid var(--border); }
.badge-auth { text-transform: none; }
.badge-auth-sub { color: var(--primary); border-color: var(--primary); }
.badge-auth-key { color: var(--muted); }
.badge-connected { color: var(--emerald, #2e7d32); border-color: var(--emerald, #2e7d32); }
.badge-failed { color: var(--rose, #e53935); border-color: var(--rose, #e53935); }
.badge-untested { color: var(--muted); }
.add-form { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 10px; }
.field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
.field > span { color: var(--muted); }
.field.grow { flex: 1; min-width: 180px; }
.field.grow .input { width: 100%; }
.login-hint code { background: var(--panel-2); border: 1px solid var(--border); border-radius: 4px; padding: 5px 8px; font-size: 11px; display: inline-block; }
.blurb { margin: 8px 0 0; }
.input { background: var(--panel-2); border: 1px solid var(--border); border-radius: 4px; color: var(--text); font-size: 12px; padding: 6px 10px; outline: none; }
.input:focus { border-color: var(--primary); }
.input.mini { font-size: 11px; padding: 4px 8px; }
.input.mono { font-family: var(--mono); }
.btn { background: var(--panel-2); border: 1px solid var(--border); border-radius: 4px; color: var(--text); font-size: 12px; padding: 6px 12px; cursor: pointer; }
.btn:hover { border-color: var(--primary); }
.btn.mini { font-size: 11px; padding: 4px 8px; }
.btn-primary { background: var(--primary); color: var(--on-primary); border-color: var(--primary); font-weight: 600; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.al-remove { color: var(--rose, #e53935); }
</style>
