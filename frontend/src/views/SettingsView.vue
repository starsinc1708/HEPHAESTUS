<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RepoProfile } from '@/types/api'
import { useWorkspaceStore } from '@/stores/workspace'
import { useConfigStore } from '@/stores/config'
import { useToastStore } from '@/stores/toast'
import HelpHint from '@/components/HelpHint.vue'
import RepoPicker from '@/components/RepoPicker.vue'
import ConnectionsManager from '@/components/ConnectionsManager.vue'
import IntegrationsPanel from '@/components/IntegrationsPanel.vue'
import AppShell from '@/components/AppShell.vue'

const { t } = useI18n()
const ws = useWorkspaceStore()
const cfg = useConfigStore()
const toast = useToastStore()

const STRICTNESS = ['strict', 'standard', 'permissive', 'disabled']
// label/help resolved reactively via i18n so the grid re-renders on locale switch.
const BASE_KEYS = computed<{ key: string; label: string; help: string }[]>(() => [
  { key: 'HEPHAESTUS_MAX_ITER', label: t('settings.base.maxIter'), help: t('settings.base.maxIterHelp') },
  { key: 'HEPHAESTUS_MAX_PARALLEL', label: t('settings.base.maxParallel'), help: t('settings.base.maxParallelHelp') },
  { key: 'HEPHAESTUS_ITER_TIMEOUT_SEC', label: t('settings.base.iterTimeout'), help: t('settings.base.iterTimeoutHelp') },
  { key: 'HEPHAESTUS_MAX_CONSEC_FAIL', label: t('settings.base.maxConsecFail'), help: t('settings.base.maxConsecFailHelp') },
  { key: 'HEPHAESTUS_TIER1_APPROVE_THRESHOLD', label: t('settings.base.tier1'), help: t('settings.base.tier1Help') },
  { key: 'HEPHAESTUS_TIER2_APPROVE_THRESHOLD', label: t('settings.base.tier2'), help: t('settings.base.tier2Help') },
])

const draft = ref<RepoProfile | null>(null)
const newRepoPath = ref('')
const busy = ref(false)
const baseBuf = ref<Record<string, string>>({})
const pageLoading = ref(true)
const pageError = ref<string | null>(null)

function setVerifyCmds(e: Event) {
  if (draft.value) {
    draft.value.verifyCommandsOverride =
      (e.target as HTMLTextAreaElement).value.split('\n').map(s => s.trim()).filter(Boolean)
  }
}

function clone(p: RepoProfile): RepoProfile {
  const d = JSON.parse(JSON.stringify(p)) as RepoProfile
  d.agents.validators = d.agents.validators ?? []
  d.agents.arbiters = d.agents.arbiters ?? []
  if (!d.agents.final) d.agents.final = { ...d.agents.primary }
  if (!d.agents.planner) d.agents.planner = { ...d.agents.primary }
  d.review = d.review ?? { enabled: true, tier1Threshold: 5, tier2Threshold: 2, maxRevisions: 2 }
  d.verifyCommandsOverride = d.verifyCommandsOverride ?? []
  d.roleConnections = d.roleConnections ?? {}
  return d
}

watch(() => ws.active, (a) => { draft.value = a ? clone(a) : null }, { immediate: true })

function refreshBaseBuf() {
  baseBuf.value = Object.fromEntries(BASE_KEYS.value.map(b => [b.key, String(cfg.effective[b.key] ?? '')]))
}

async function loadSettings() {
  pageLoading.value = true
  pageError.value = null
  try {
    await ws.fetchWorkspaces()
    await cfg.fetchConfig()
    refreshBaseBuf()
  } catch (e: unknown) {
    pageError.value = e instanceof Error ? e.message : String(e)
  } finally {
    pageLoading.value = false
  }
}

onMounted(() => loadSettings())

const verifyCmdsText = computed({
  get: () => (draft.value?.verifyCommandsOverride ?? []).join('\n'),
  set: (v: string) => { if (draft.value) draft.value.verifyCommandsOverride = v.split('\n').map(s => s.trim()).filter(Boolean) },
})

async function saveProfile(patch: Partial<RepoProfile>, msg: string) {
  if (!draft.value) return
  busy.value = true
  try {
    await ws.updateProfile(draft.value.id, patch)
    toast.add('success', msg)
  } catch (e: unknown) {
    toast.add('error', e instanceof Error ? e.message : String(e))
  } finally { busy.value = false }
}

const saveVerify = () => draft.value && saveProfile({
  verifySource: draft.value.verifySource,
  verifyCommandsOverride: draft.value.verifyCommandsOverride,
  verifyTimeoutSec: draft.value.verifyTimeoutSec,
}, t('settings.verify.saved'))
const saveGit = () => draft.value && saveProfile({
  baseBranch: draft.value.baseBranch,
  remote: draft.value.remote,
  branchPrefix: draft.value.branchPrefix,
  autopush: draft.value.autopush,
}, t('settings.git.saved'))
const saveRevisions = () => draft.value && saveProfile({ review: draft.value.review }, t('settings.validation.saved'))

async function onStrictness(name: string) {
  if (!draft.value) return
  draft.value.strictness = name
  busy.value = true
  try {
    await cfg.applyPreset(name)
    await ws.updateProfile(draft.value.id, { strictness: name })
    await cfg.fetchConfig()
    refreshBaseBuf()
    toast.add('success', t('settings.strictnessResult', { name }))
  } catch (e: unknown) {
    toast.add('error', e instanceof Error ? e.message : String(e))
  } finally { busy.value = false }
}

async function saveBase() {
  busy.value = true
  try {
    await cfg.saveConfig({ ...cfg.overrides, ...baseBuf.value })
  } finally { busy.value = false }
}

async function addRepo() {
  const path = newRepoPath.value.trim()
  if (!path) return
  busy.value = true
  try {
    const w = await ws.onboard(path)
    await ws.activate(w.id)
    newRepoPath.value = ''
    toast.add('success', t('settings.repo.added', { name: w.name }))
  } catch (e: unknown) {
    toast.add('error', e instanceof Error ? e.message : String(e))
  } finally { busy.value = false }
}
</script>

<template>
  <AppShell>
    <template #title>{{ t('settings.title') }}</template>
    <div class="settings">

    <!-- Loading state -->
    <div v-if="pageLoading" class="loading-state" data-test="settings-loading">
      <span class="loading-spinner" />
      <span>{{ t('settings.loading') }}</span>
    </div>

    <!-- Error state -->
    <div v-else-if="pageError" class="error-state" data-test="settings-error">
      <span class="error-icon">⚠</span>
      <span>{{ t('settings.loadError', { error: pageError }) }}</span>
      <button class="btn btn-sm btn-primary" @click="loadSettings()">{{ t('settings.retry') }}</button>
    </div>

    <template v-else>
    <!-- 1. Репозиторий -->
    <section class="card">
      <h3>{{ t('settings.repo.title') }} <HelpHint :text="t('settings.repo.help')" /></h3>
      <div class="ws-list">
        <div v-for="w in ws.workspaces" :key="w.id" class="ws-item" :class="{ active: w.id === ws.activeId }">
          <div class="ws-meta"><b>{{ w.name }}</b><span class="mono muted">{{ w.repoPath }}</span></div>
          <button v-if="w.id !== ws.activeId" class="btn" :disabled="busy" @click="ws.activate(w.id)">{{ t('settings.repo.makeActive') }}</button>
          <span v-else class="badge-active">{{ t('settings.repo.active') }}</span>
        </div>
        <div v-if="!ws.workspaces.length" class="muted">{{ t('settings.repo.none') }}</div>
      </div>
      <RepoPicker v-model="newRepoPath" :busy="busy" />
      <p class="repo-or">{{ t('settings.repo.orManual') }}</p>
      <div class="add-repo">
        <input v-model="newRepoPath" class="input" :placeholder="t('settings.repo.addPlaceholder')" :disabled="busy" @keyup.enter="addRepo" />
        <button class="btn btn-primary" :disabled="busy || !newRepoPath" @click="addRepo">{{ t('settings.repo.add') }}</button>
        <HelpHint :text="t('settings.repo.addHelp')" />
      </div>
    </section>

    <!-- 2. Подключения моделей (глобально) -->
    <ConnectionsManager />

    <!-- 2b. Интеграции (GitHub/GitLab) -->
    <section class="card">
      <IntegrationsPanel />
    </section>

    <template v-if="draft">
      <!-- 3. Git / ветки -->
      <section class="card">
        <h3>{{ t('settings.git.title') }} <HelpHint :text="t('settings.git.help')" /></h3>
        <div class="row">
          <label class="field"><span>{{ t('settings.git.baseBranch') }} <HelpHint :text="t('settings.git.baseBranchHelp')" /></span>
            <input class="input mono" v-model="draft.baseBranch" data-test="base-branch" placeholder="main" />
          </label>
          <label class="field"><span>{{ t('settings.git.remote') }} <HelpHint :text="t('settings.git.remoteHelp')" /></span>
            <input class="input mono" v-model="draft.remote" data-test="remote" placeholder="origin" />
          </label>
          <label class="field"><span>{{ t('settings.git.prefix') }} <HelpHint :text="t('settings.git.prefixHelp')" /></span>
            <input class="input mono" v-model="draft.branchPrefix" data-test="branch-prefix" placeholder="auto" />
          </label>
        </div>
        <label class="field check"><input type="checkbox" v-model="draft.autopush" data-test="autopush" /><span>{{ t('settings.git.autopush') }} <HelpHint :text="t('settings.git.autopushHelp')" /></span></label>
        <button class="btn btn-primary" :disabled="busy" data-test="save-git" @click="saveGit">{{ t('settings.git.save') }}</button>
      </section>

      <!-- 4. Валидация -->
      <section class="card">
        <h3>{{ t('settings.validation.title') }} <HelpHint :text="t('settings.validation.help')" /></h3>
        <div class="row">
          <label class="field"><span>{{ t('settings.validation.strictness') }} <HelpHint :text="t('settings.validation.strictnessHelp')" /></span>
            <select class="input" :value="draft.strictness" data-test="strictness" @change="onStrictness(($event.target as HTMLSelectElement).value)">
              <option v-for="s in STRICTNESS" :key="s" :value="s">{{ s }}</option>
            </select>
          </label>
          <label class="field"><span>{{ t('settings.validation.maxRevisions') }} <HelpHint :text="t('settings.validation.maxRevisionsHelp')" /></span>
            <input class="input" type="number" min="0" max="10" v-model.number="draft.review!.maxRevisions" @change="saveRevisions" />
          </label>
        </div>
      </section>

      <!-- 6. Verify -->
      <section class="card">
        <h3>{{ t('settings.verify.title') }} <HelpHint :text="t('settings.verify.help')" /></h3>
        <div class="row">
          <label class="field"><span>{{ t('settings.verify.source') }} <HelpHint :text="t('settings.verify.sourceHelp')" /></span>
            <select class="input" v-model="draft.verifySource">
              <option value="agent">{{ t('settings.verify.agentOpt') }}</option>
              <option value="manual">{{ t('settings.verify.manualOpt') }}</option>
            </select>
          </label>
          <label class="field"><span>{{ t('settings.verify.timeout') }} <HelpHint :text="t('settings.verify.timeoutHelp')" /></span>
            <input class="input" type="number" v-model.number="draft.verifyTimeoutSec" />
          </label>
        </div>
        <label class="field"><span>{{ t('settings.verify.commands') }} <HelpHint :text="t('settings.verify.commandsHelp')" /></span>
          <textarea class="input mono" rows="3" :value="verifyCmdsText" @change="setVerifyCmds" :disabled="draft.verifySource !== 'manual'" placeholder="uv run pytest -q"></textarea>
        </label>
        <button class="btn btn-primary" :disabled="busy" @click="saveVerify">{{ t('settings.verify.save') }}</button>
      </section>

      <!-- 7. Базовые параметры -->
      <section class="card">
        <h3>{{ t('settings.base.title') }} <HelpHint :text="t('settings.base.help')" /></h3>
        <div class="base-grid">
          <label v-for="b in BASE_KEYS" :key="b.key" class="field">
            <span>{{ b.label }} <HelpHint :text="b.help" /></span>
            <input class="input mono" v-model="baseBuf[b.key]" />
          </label>
        </div>
        <button class="btn btn-primary" :disabled="busy" @click="saveBase">{{ t('settings.base.save') }}</button>
      </section>
    </template>
    <p v-else class="muted">{{ t('settings.noActiveRepo') }}</p>
    </template>
    </div>
  </AppShell>
</template>

<style scoped>
.settings { max-width: 920px; margin: 0 auto; padding: 16px; display: flex; flex-direction: column; gap: 16px; }
.page-title { font-size: 18px; margin: 0; }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.card h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin: 0 0 12px; }
.ws-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
.ws-item { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; }
.ws-item.active { border-color: var(--primary); }
.ws-meta { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.ws-meta .mono { font-size: 11px; overflow: hidden; text-overflow: ellipsis; }
.badge-active { color: var(--primary); font-size: 11px; text-transform: uppercase; }
.repo-or { color: var(--muted); font-size: 11px; margin: 0 0 6px; }
.add-repo { display: flex; align-items: center; gap: 8px; }
.input { background: var(--panel-2); border: 1px solid var(--border); border-radius: 4px; color: var(--text); font-size: 12px; padding: 6px 10px; outline: none; }
.input:focus { border-color: var(--primary); }
.input.mono, textarea.mono { font-family: var(--mono); }
.add-repo .input { flex: 1; }
.btn { background: var(--panel-2); border: 1px solid var(--border); border-radius: 4px; color: var(--text); font-size: 12px; padding: 6px 12px; cursor: pointer; }
.btn:hover { border-color: var(--primary); }
.btn-primary { background: var(--primary); color: var(--on-primary); border-color: var(--primary); font-weight: 600; margin-top: 12px; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.row { display: flex; gap: 16px; flex-wrap: wrap; align-items: flex-end; }
.field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
.field > span { color: var(--muted); }
.field.check { flex-direction: row; align-items: center; }
.base-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
textarea.input { resize: vertical; }

.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 60px 0;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 14px;
}

.loading-spinner {
  display: inline-block;
  width: 18px;
  height: 18px;
  border: 2px solid var(--border);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.error-state {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--rose);
  font-family: var(--mono);
  font-size: 12px;
}

.error-icon {
  font-size: 16px;
}
</style>
