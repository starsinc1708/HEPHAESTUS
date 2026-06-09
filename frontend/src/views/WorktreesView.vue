<script setup lang="ts">
import { onMounted, onUnmounted, ref, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Worktree, MergeJob } from '@/types/api'
import { api } from '@/api/client'
import { useToastStore } from '@/stores/toast'
import AppShell from '@/components/AppShell.vue'
import MergeButton from '@/components/MergeButton.vue'

const { t } = useI18n()
const worktrees = ref<Worktree[]>([])
const loading = ref(false)
const actionLoading = ref<string | null>(null)
const pageError = ref<string | null>(null)

// per-branch lazy diff state
const diffOpen = reactive<Record<string, boolean>>({})
const diffCache = reactive<Record<string, string>>({})
const diffLoading = reactive<Record<string, boolean>>({})

// per-branch conflict-detail expansion
const conflictOpen = reactive<Record<string, boolean>>({})

// single-active-merge gating. Mirrors the server's MergeJobStore.active() terminal
// set (_TERMINAL = {accepted, rejected, failed, conflict}): a `resolved` job is NOT
// terminal — it still blocks a new merge (awaiting accept/reject), so it must gate
// other rows. The server's active() never surfaces failed/conflict (they're terminal),
// but list them here so the gate matches the server's blocking contract exactly.
const activeJob = ref<MergeJob | null>(null)
const TERMINAL = ['accepted', 'rejected', 'failed', 'conflict']

let _wtTimer: ReturnType<typeof setInterval> | null = null
let _jobTimer: ReturnType<typeof setInterval> | null = null

async function fetchWorktrees() {
  loading.value = true
  pageError.value = null
  try {
    const res = await api.listWorktrees()
    worktrees.value = res.worktrees ?? []
  } catch (e: unknown) {
    pageError.value = e instanceof Error ? e.message : String(e)
    // keep stale list on transient errors
  } finally {
    loading.value = false
  }
}

async function fetchActiveJob() {
  try {
    const res = await api.getActiveMergeJob()
    activeJob.value = res.job
  } catch {
    // best effort
  }
}

function otherMergeActive(branch: string): boolean {
  const j = activeJob.value
  if (!j) return false
  if (TERMINAL.includes(j.status)) return false
  return j.branch !== branch
}

async function toggleDiff(branch: string) {
  diffOpen[branch] = !diffOpen[branch]
  if (diffOpen[branch] && diffCache[branch] === undefined && !diffLoading[branch]) {
    diffLoading[branch] = true
    try {
      diffCache[branch] = await api.worktreeDiff(branch)
    } catch (e: unknown) {
      diffCache[branch] = t('worktrees.diffError', { error: e instanceof Error ? e.message : String(e) })
    } finally {
      diffLoading[branch] = false
    }
  }
}

function toggleConflict(branch: string) {
  conflictOpen[branch] = !conflictOpen[branch]
}

function conflictSummary(w: Worktree): string {
  const names = w.conflictsWith.map((c) => c.task?.title || c.branch)
  const totalFiles = w.conflictsWith.reduce((acc, c) => acc + c.files.length, 0)
  return t('worktrees.overlapWarning', { names: names.join(', '), count: totalFiles })
}

interface StatusChip {
  label: string
  tone: 'green' | 'amber' | 'muted'
}

function statusChip(w: Worktree): StatusChip {
  if (w.task && w.task.status === 'merged') return { label: 'merged', tone: 'green' }
  const p = w.preflight
  if (p.ok) return { label: t('worktrees.status.ready'), tone: 'green' }
  if (!p.cleanTree) return { label: t('worktrees.status.dirty'), tone: 'amber' }
  if (!p.verifyGreen) {
    return { label: p.verifyUnverified ? t('worktrees.status.noTests') : t('worktrees.status.verifyFail'), tone: 'amber' }
  }
  if (!p.validationPassed) return { label: t('worktrees.status.funnelFail'), tone: 'amber' }
  if (p.loopActive) return { label: t('worktrees.status.loopActive'), tone: 'muted' }
  return { label: t('worktrees.status.notReady'), tone: 'muted' }
}

async function branchAction(name: string, action: 'requeue' | 'discard') {
  const toast = useToastStore()

  if (action === 'discard') {
    if (!confirm(t('worktrees.rejectConfirm', { name }))) return
  }

  actionLoading.value = `${name}:${action}`
  try {
    const res = await api.branchAction(name, action)
    if (res.ok) {
      toast.add('success', t('worktrees.actionDone', { action, name }))
      await fetchWorktrees()
    } else {
      toast.add('error', res.error ?? t('worktrees.actionError'))
    }
  } catch (e: unknown) {
    toast.add('error', t('worktrees.error', { error: e instanceof Error ? e.message : String(e) }))
  } finally {
    actionLoading.value = null
  }
}

async function createPr(name: string) {
  const toast = useToastStore()
  actionLoading.value = `${name}:create-pr`
  try {
    const res = await api.createPr(name)
    if (res.ok) {
      toast.add('success', t('worktrees.prCreated', { url: res.url }))
    } else {
      toast.add('error', t('worktrees.prError'))
    }
  } catch (e: unknown) {
    toast.add('error', t('worktrees.error', { error: e instanceof Error ? e.message : String(e) }))
  } finally {
    actionLoading.value = null
  }
}

function isActionLoading(name: string, action: string): boolean {
  return actionLoading.value === `${name}:${action}`
}

async function onMerged() {
  await Promise.all([fetchWorktrees(), fetchActiveJob()])
}

function refresh() {
  void fetchWorktrees()
  void fetchActiveJob()
}

onMounted(() => {
  void fetchWorktrees()
  void fetchActiveJob()
  // list is heavier — throttled 15s; active-merge job poll is light — 3s
  _wtTimer = setInterval(() => void fetchWorktrees(), 15_000)
  _jobTimer = setInterval(() => void fetchActiveJob(), 3_000)
})

onUnmounted(() => {
  if (_wtTimer !== null) {
    clearInterval(_wtTimer)
    _wtTimer = null
  }
  if (_jobTimer !== null) {
    clearInterval(_jobTimer)
    _jobTimer = null
  }
})
</script>

<template>
  <AppShell>
    <template #title>Worktrees</template>

    <div class="toolbar">
      <button class="action-btn refresh" data-test="wt-refresh" :title="t('worktrees.refresh')" @click="refresh">
        ↻ {{ t('worktrees.refresh').toLowerCase() }}
      </button>
    </div>

    <div v-if="loading && worktrees.length === 0" class="loading">{{ t('worktrees.loading') }}</div>

    <!-- Error state -->
    <div v-else-if="pageError && worktrees.length === 0" class="error-state" data-test="worktrees-error">
      <span class="error-icon">⚠</span>
      <span>{{ t('worktrees.loadError', { error: pageError }) }}</span>
      <button class="btn btn-sm btn-primary" @click="fetchWorktrees()">{{ t('worktrees.retry') }}</button>
    </div>

    <div v-else class="wt-list" data-test="worktrees-list">
      <div
        v-for="w in worktrees"
        :key="w.branch"
        class="wt-row"
        :class="{ overlapping: w.conflictsWith.length > 0 }"
      >
        <div class="wt-main">
          <!-- Task -->
          <div class="wt-task">
            <template v-if="w.task">
              <span class="task-id mono">{{ w.task.id }}</span>
              <span class="task-title">{{ w.task.title }}</span>
              <span class="chip" :class="'chip-' + w.task.status">{{ w.task.status }}</span>
            </template>
            <span v-else class="muted">{{ t('worktrees.noTask') }}</span>
          </div>

          <!-- Branch -->
          <div class="wt-branch mono">{{ w.branch }}</div>

          <!-- Changed files (toggle) -->
          <div class="wt-files">
            <button
              class="link-toggle"
              data-test="wt-diff-toggle"
              @click="toggleDiff(w.branch)"
            >
              {{ diffOpen[w.branch] ? '▾' : '▸' }} {{ t('worktrees.files', { count: w.changedCount }) }}
            </button>
          </div>

          <!-- Merge -->
          <div class="wt-merge">
            <MergeButton
              :branch="w.branch"
              :disabled="otherMergeActive(w.branch)"
              @merged="onMerged"
            />
          </div>

          <!-- Status -->
          <div class="wt-status">
            <span class="chip" :class="'tone-' + statusChip(w).tone">{{ statusChip(w).label }}</span>
          </div>

          <!-- Actions -->
          <div class="actions">
            <button
              class="action-btn requeue"
              :disabled="isActionLoading(w.branch, 'requeue')"
              :title="t('worktrees.restart')"
              @click="branchAction(w.branch, 'requeue')"
            >
              {{ isActionLoading(w.branch, 'requeue') ? '…' : '↻' }}
            </button>
            <button
              class="action-btn discard"
              :disabled="isActionLoading(w.branch, 'discard')"
              :title="t('worktrees.reject')"
              @click="branchAction(w.branch, 'discard')"
            >
              {{ isActionLoading(w.branch, 'discard') ? '…' : '✗' }}
            </button>
            <button
              class="action-btn create-pr"
              :disabled="isActionLoading(w.branch, 'create-pr')"
              data-test="create-pr"
              :title="t('worktrees.createPr')"
              @click="createPr(w.branch)"
            >
              {{ isActionLoading(w.branch, 'create-pr') ? '…' : 'PR' }}
            </button>
          </div>
        </div>

        <!-- Overlap badge -->
        <div v-if="w.conflictsWith.length > 0" class="wt-conflict-wrap">
          <button class="conflict-badge" data-test="wt-conflict" @click="toggleConflict(w.branch)">
            {{ conflictSummary(w) }}
          </button>
          <div v-if="conflictOpen[w.branch]" class="conflict-detail">
            <div v-for="c in w.conflictsWith" :key="c.branch" class="conflict-group">
              <div class="conflict-group-head mono">{{ c.task?.title || c.branch }}</div>
              <ul class="conflict-files">
                <li v-for="f in c.files" :key="f" class="mono">{{ f }}</li>
              </ul>
            </div>
          </div>
        </div>

        <!-- Diff expansion -->
        <div v-if="diffOpen[w.branch]" class="wt-diff-wrap">
          <div v-if="diffLoading[w.branch]" class="muted">{{ t('worktrees.loading') }}</div>
          <pre v-else class="diff-block">{{ diffCache[w.branch] }}</pre>
        </div>
      </div>

      <div v-if="worktrees.length === 0" class="empty-row">{{ t('worktrees.noActive') }}</div>
    </div>
  </AppShell>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 10px;
}

.loading {
  text-align: center;
  padding: 40px;
  color: var(--muted);
  font-family: var(--mono);
}

.wt-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.wt-row {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--panel-2);
}

.wt-row.overlapping {
  border-left: 3px solid var(--amber);
  background: color-mix(in srgb, var(--amber) 6%, var(--panel-2));
}

.wt-main {
  display: grid;
  grid-template-columns: minmax(180px, 1.4fr) minmax(140px, 1fr) auto minmax(160px, auto) auto auto;
  gap: 12px;
  align-items: center;
}

.wt-task {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.task-id {
  font-size: 11px;
  color: var(--muted);
}
.task-title {
  font-size: 13px;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wt-branch {
  font-size: 11px;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mono {
  font-family: var(--mono);
}

.muted {
  color: var(--muted);
  font-size: 13px;
}

.chip {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  background: var(--panel);
  border: 1px solid var(--border);
  color: var(--muted);
  white-space: nowrap;
}
.tone-green { color: var(--green); border-color: var(--green); }
.tone-amber { color: var(--amber); border-color: var(--amber); }
.tone-muted { color: var(--muted); }
.chip-merged { color: var(--green); border-color: var(--green); }
.chip-done { color: var(--green); }

.link-toggle {
  background: none;
  border: none;
  color: var(--primary);
  cursor: pointer;
  font-size: 12px;
  padding: 0;
  font-family: var(--mono);
}
.link-toggle:hover { text-decoration: underline; }

.actions {
  display: flex;
  gap: 4px;
}

.action-btn {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--muted);
  font-size: 13px;
  padding: 3px 8px;
  cursor: pointer;
  transition: color 0.12s, border-color 0.12s;
}
.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.action-btn:hover:not(:disabled) { color: var(--text); border-color: var(--border-2); }
.action-btn.requeue:hover:not(:disabled)   { color: var(--amber); border-color: var(--amber); }
.action-btn.discard:hover:not(:disabled)   { color: var(--rose);  border-color: var(--rose); }
.action-btn.create-pr:hover:not(:disabled) { color: var(--primary); border-color: var(--primary); }
.action-btn.refresh:hover:not(:disabled)   { color: var(--primary); border-color: var(--primary); }

.wt-conflict-wrap {
  margin-top: 8px;
}
.conflict-badge {
  background: color-mix(in srgb, var(--amber) 12%, transparent);
  border: 1px solid var(--amber);
  border-radius: 6px;
  color: var(--amber);
  font-size: 12px;
  padding: 4px 10px;
  cursor: pointer;
}
.conflict-detail {
  margin-top: 6px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--panel);
}
.conflict-group + .conflict-group { margin-top: 8px; }
.conflict-group-head {
  font-size: 11px;
  color: var(--amber);
  margin-bottom: 4px;
}
.conflict-files {
  margin: 0;
  padding-left: 16px;
}
.conflict-files li {
  font-size: 11px;
  color: var(--text);
}

.wt-diff-wrap {
  margin-top: 8px;
}
.diff-block {
  background: #0b0d10;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px;
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.5;
  overflow: auto;
  max-height: 48vh;
  white-space: pre;
  margin: 0;
}

.empty-row {
  text-align: center;
  color: var(--muted-soft);
  padding: 30px;
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

.btn {
  font-family: var(--mono);
  font-size: 12px;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 5px 12px;
  cursor: pointer;
  background: var(--panel-2);
  color: var(--text);
  transition: background 0.12s;
}
.btn:hover { background: var(--panel-3); }
.btn-sm { font-size: 11px; padding: 4px 10px; }
.btn-primary { border-color: var(--primary); color: var(--primary); }
</style>
