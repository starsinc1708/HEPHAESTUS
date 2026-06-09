<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Connection, CliInfo } from '@/types/api'
import { api } from '@/api/client'
import { useWorkspaceStore } from '@/stores/workspace'
import { useToastStore } from '@/stores/toast'
import ConnectionsManager from '@/components/ConnectionsManager.vue'

const props = defineProps<{ connections: Connection[] }>()
const emit = defineEmits<{ 'connections-changed': [Connection[]]; skip: [] }>()

const { t } = useI18n()
const ws = useWorkspaceStore()
const toast = useToastStore()

const current = ref<1 | 2 | 3>(1)

// Local copy of connections, seeded from the prop and updated by ConnectionsManager.
const localConnections = ref<Connection[]>([...props.connections])
watch(() => props.connections, (v) => { localConnections.value = [...v] })

const hasConnected = computed(() => localConnections.value.some(c => c.status === 'connected'))

function onConnChanged(list: Connection[]) {
  localConnections.value = list
  emit('connections-changed', list)
}

// ── Step 2: CLI detection (informational) ──
const ENGINE_ORDER = ['claude', 'opencode', 'codex'] as const
const clis = ref<Record<string, CliInfo>>({})
const clisLoaded = ref(false)
const cliRows = computed(() =>
  ENGINE_ORDER.map(name => ({
    name,
    info: clis.value[name] ?? { installed: false, version: null, auth: {} },
  })),
)

const cliError = ref(false)

async function loadClis() {
  cliError.value = false
  try {
    clis.value = (await api.getClis()).clis
  } catch (e) {
    cliError.value = true
    console.warn('CLI detection failed:', e)
  }
  clisLoaded.value = true
}

function retryClis() {
  void loadClis()
}

// ── Navigation ──
function next1() { current.value = 2; if (!clisLoaded.value) void loadClis() }
function next2() { current.value = 3 }

// ── Step 3: repo onboarding ──
const repoPath = ref('')
const busy = ref(false)

async function addRepo() {
  const path = repoPath.value.trim()
  if (!path) return
  busy.value = true
  try {
    const w = await ws.onboard(path)
    await ws.activate(w.id)
    repoPath.value = ''
    toast.add('success', t('wizard.repoAdded', { name: w.name }))
  } catch (e: unknown) {
    toast.add('error', e instanceof Error ? e.message : String(e))
  } finally { busy.value = false }
}

const canFinish = computed(() => ws.activeId != null)
function finish() {
  // Once a workspace is active AND connections exist, AppShell's needsOnboarding
  // flips false and the overlay unmounts reactively. This is mostly a confirm.
  emit('connections-changed', localConnections.value)
}

function onSkip() { emit('skip') }
</script>

<template>
  <div class="wiz-overlay" data-test="onboard-wizard-inner">
    <div class="wiz-backdrop" />
    <div class="wiz-modal" role="dialog" aria-modal="true" aria-labelledby="wiz-title">
      <header class="wiz-head">
        <div class="wiz-steps">
          <span class="wiz-pip" :class="{ on: current >= 1, done: current > 1 }">1</span>
          <span class="wiz-bar" :class="{ on: current > 1 }" />
          <span class="wiz-pip" :class="{ on: current >= 2, done: current > 2 }">2</span>
          <span class="wiz-bar" :class="{ on: current > 2 }" />
          <span class="wiz-pip" :class="{ on: current >= 3 }">3</span>
        </div>
        <button class="wiz-skip" data-test="wiz-skip" @click="onSkip">{{ t('wizard.skip') }}</button>
      </header>

      <!-- Step 1 -->
      <section v-if="current === 1" data-test="wiz-step-1" class="wiz-body">
        <h2 id="wiz-title" class="wiz-title">{{ t('wizard.step1.title') }}</h2>
        <p class="wiz-lead">{{ t('wizard.step1.lead') }}</p>
        <ConnectionsManager @changed="onConnChanged" />
        <footer class="wiz-foot">
          <button
            class="btn btn-primary"
            data-test="wiz-next-1"
            :disabled="!hasConnected"
            @click="next1"
          >{{ t('wizard.next') }}</button>
        </footer>
      </section>

      <!-- Step 2 -->
      <section v-else-if="current === 2" data-test="wiz-step-2" class="wiz-body">
        <h2 id="wiz-title" class="wiz-title">{{ t('wizard.step2.title') }}</h2>
        <p class="wiz-lead">{{ t('wizard.step2.lead') }}</p>
        <div class="cli-list">
          <div
            v-for="row in cliRows"
            :key="row.name"
            class="cli-row"
            :class="{ off: !row.info.installed }"
            :data-test="`wiz-cli-${row.name}`"
          >
            <span class="cli-mark">{{ row.info.installed ? '✓' : '✗' }}</span>
            <b class="mono">{{ row.name }}</b>
            <span v-if="row.info.installed" class="mono muted small">{{ row.info.version ?? '' }}</span>
            <span v-else class="muted small">{{ t('wizard.step2.notInstalled') }}</span>
          </div>
        </div>
        <div v-if="cliError" class="cli-error" data-test="wiz-cli-error">
          <span>{{ t('wizard.step2.error') }}</span>
          <button class="btn" data-test="wiz-cli-retry" @click="retryClis">{{ t('wizard.step2.retry') }}</button>
        </div>
        <footer class="wiz-foot">
          <button class="btn" @click="current = 1">{{ t('wizard.back') }}</button>
          <button class="btn btn-primary" data-test="wiz-next-2" @click="next2">{{ t('wizard.next') }}</button>
        </footer>
      </section>

      <!-- Step 3 -->
      <section v-else data-test="wiz-step-3" class="wiz-body">
        <h2 id="wiz-title" class="wiz-title">{{ t('wizard.step3.title') }}</h2>
        <p class="wiz-lead">{{ t('wizard.step3.lead') }}</p>
        <div class="repo-form">
          <input
            v-model="repoPath"
            class="input"
            data-test="wiz-repo-path"
            :placeholder="t('wizard.step3.placeholder')"
            :disabled="busy"
            @keyup.enter="addRepo"
          />
          <button
            class="btn btn-primary"
            data-test="wiz-add-repo"
            :disabled="busy || !repoPath.trim()"
            @click="addRepo"
          >{{ t('wizard.step3.add') }}</button>
        </div>
        <footer class="wiz-foot">
          <button class="btn" @click="current = 2">{{ t('wizard.back') }}</button>
          <button
            class="btn btn-primary"
            data-test="wiz-done"
            :disabled="!canFinish"
            @click="finish"
          >{{ t('wizard.done') }}</button>
        </footer>
      </section>
    </div>
  </div>
</template>

<style scoped>
.wiz-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.wiz-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(2px);
}
.wiz-modal {
  position: relative;
  width: min(720px, 100%);
  max-height: calc(100vh - 48px);
  overflow: auto;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.45);
  padding: 20px 24px;
}
.wiz-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.wiz-steps { display: flex; align-items: center; gap: 6px; }
.wiz-pip {
  width: 24px; height: 24px;
  display: inline-flex; align-items: center; justify-content: center;
  border-radius: 50%;
  border: 1px solid var(--border);
  font-family: var(--mono); font-size: 12px;
  color: var(--muted);
}
.wiz-pip.on { border-color: var(--primary); color: var(--primary); }
.wiz-pip.done { background: var(--primary); color: var(--on-primary); }
.wiz-bar { width: 28px; height: 2px; background: var(--border); }
.wiz-bar.on { background: var(--primary); }
.wiz-skip {
  background: transparent;
  border: none;
  color: var(--muted);
  font-size: 12px;
  cursor: pointer;
  text-decoration: underline;
}
.wiz-skip:hover { color: var(--text); }
.wiz-title { font-size: 18px; margin: 0 0 6px; }
.wiz-lead { color: var(--muted); font-size: 13px; margin: 0 0 14px; }
.wiz-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
.cli-list { display: flex; flex-direction: column; gap: 8px; }
.cli-row {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
}
.cli-row .cli-mark { font-weight: 700; color: var(--emerald, #2e7d32); }
.cli-row.off { opacity: 0.6; }
.cli-row.off .cli-mark { color: var(--rose, #e53935); }
.repo-form { display: flex; gap: 8px; }
.repo-form .input { flex: 1; }
.muted { color: var(--muted); }
.small { font-size: 11px; }
.mono { font-family: var(--mono); }
.input {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-size: 12px;
  padding: 6px 10px;
  outline: none;
}
.input:focus { border-color: var(--primary); }
.btn {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-size: 12px;
  padding: 6px 12px;
  cursor: pointer;
}
.btn:hover { border-color: var(--primary); }
.btn-primary { background: var(--primary); color: var(--on-primary); border-color: var(--primary); font-weight: 600; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.cli-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border: 1px solid var(--rose, #e53935);
  border-radius: 6px;
  color: var(--rose, #e53935);
  font-size: 13px;
  margin-top: 8px;
}
.cli-error .btn {
  font-size: 11px;
  padding: 4px 8px;
}
</style>
