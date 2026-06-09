<script setup lang="ts">
import { computed, watch, ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import type { Item, IterDetails, Verdict, IterReviewsResponse, ValidationResult, VerifyOutcome } from '@/types/api'
import { useTaskStore } from '@/stores/task'
import { useBoardStore } from '@/stores/board'
import { useToastStore } from '@/stores/toast'
import { api } from '@/api/client'
import { byId, unfinishedAncestors } from '@/composables/deps'
import StatusBadge from './StatusBadge.vue'
import IterChip from './IterChip.vue'
import DrawerReviewPanel from './DrawerReviewPanel.vue'
import DrawerChecksPanel from './DrawerChecksPanel.vue'
import DrawerActions from './DrawerActions.vue'
import DialogPane from './DialogPane.vue'

const props = defineProps<{
  item: Item | null
}>()

const emit = defineEmits<{ close: [] }>()

const router = useRouter()
const { t } = useI18n()
const taskStore = useTaskStore()
const boardStore = useBoardStore()
const toastStore = useToastStore()

function openConversation() {
  if (props.item) router.push({ name: 'board-task-conversation', params: { id: props.item.id } })
}
const tab = computed(() => taskStore.activeTab)
const details = ref<IterDetails | null>(null)
const diffText = ref<string | null>(null)
const reviewsData = ref<IterReviewsResponse | null>(null)
const validationData = ref<ValidationResult | null>(null)
const verifyOutcome = ref<VerifyOutcome | null>(null)
const scopeExtra = ref<string[]>([])
const checksError = ref(false)
const tabLoading = ref(false)

// Action button states
const actionLoading = ref<string | null>(null)

// Tag editor state
const tagInput = ref('')
const tagSaving = ref(false)

// ESC key handler
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
})

const TABS = computed(() => [
  t('drawer.tabs.description'),
  t('drawer.tabs.iterations'),
  t('drawer.tabs.dialog'),
  t('drawer.tabs.diff'),
  t('drawer.tabs.review'),
  t('drawer.tabs.checks'),
])
const DIALOG_TAB = 2
const REVIEW_TAB = 4

const isOpen = computed(() => props.item !== null)

const canMoveTop = computed(() => props.item?.status === 'pending')
const canRequeue = computed(() => {
  if (!props.item) return false
  const s = props.item.status
  return s === 'pending' || s.startsWith('failed') || s === 'needs_revision'
})
const canRun = computed(() => {
  const s = props.item?.status
  return s === 'pending' || s === 'needs_revision'
})
const canUnqueue = computed(() => props.item?.status === 'queued')

async function onMoveTop() {
  if (!props.item || actionLoading.value) return
  actionLoading.value = 'moveTop'
  try {
    await boardStore.moveTop(props.item.id)
    toastStore.add('success', t('drawer.movedTop', { id: props.item.id }))
    emit('close')
  } finally {
    actionLoading.value = null
  }
}

async function onRequeue() {
  if (!props.item || actionLoading.value) return
  actionLoading.value = 'requeue'
  try {
    await boardStore.requeueItem(props.item.id)
    toastStore.add('success', t('drawer.requeued', { id: props.item.id }))
    emit('close')
  } finally {
    actionLoading.value = null
  }
}

async function onRun() {
  if (!props.item || actionLoading.value) return
  actionLoading.value = 'run'
  try {
    await boardStore.runTask(props.item.id)
    emit('close')
  } finally {
    actionLoading.value = null
  }
}

async function onUnqueue() {
  if (!props.item || actionLoading.value) return
  actionLoading.value = 'unqueue'
  try {
    await boardStore.unqueueTask(props.item.id)
    emit('close')
  } finally {
    actionLoading.value = null
  }
}

// ── Tag editor ──
async function addTag() {
  if (!props.item || !tagInput.value.trim() || tagSaving.value) return
  const current = props.item.tags ?? []
  const tag = tagInput.value.trim()
  if (current.includes(tag)) { tagInput.value = ''; return }
  tagSaving.value = true
  try {
    await api.setTaskTags(props.item.id, [...current, tag])
    tagInput.value = ''
    await boardStore.fetchState()
  } finally {
    tagSaving.value = false
  }
}

async function removeTag(tag: string) {
  if (!props.item || tagSaving.value) return
  const current = props.item.tags ?? []
  tagSaving.value = true
  try {
    await api.setTaskTags(props.item.id, current.filter(x => x !== tag))
    await boardStore.fetchState()
  } finally {
    tagSaving.value = false
  }
}

// ── §4 Dependency editor ──
const depError = ref<string | null>(null)
const depAddSelect = ref<string>('')
// In-flight guard: PATCH /deps dedupes by METHOD+path (no body), and each edit reads the
// current dependsOn off props. Serialize edits so a second click before the first refetch
// can't read a stale array or collide with the in-flight request and silently drop a write.
const depBusy = ref(false)

// Candidate deps: every other task not already a dep of this one.
const depCandidates = computed(() => {
  if (!props.item) return []
  const cur = props.item.dependsOn ?? []
  return boardStore.items.filter(t => t.id !== props.item!.id && !cur.includes(t.id))
})

async function applyDeps(next: string[]) {
  if (!props.item || depBusy.value) return
  depBusy.value = true
  try {
    const r = await boardStore.patchDeps(props.item.id, next)
    depError.value = r.ok ? null : (r.error ?? t('drawer.depUpdateError'))
  } finally {
    depBusy.value = false
  }
}

async function onAddDep() {
  if (!props.item || !depAddSelect.value || depBusy.value) return
  const next = [...(props.item.dependsOn ?? []), depAddSelect.value]
  depAddSelect.value = ''
  await applyDeps(next)
}

async function onRemoveDep(id: string) {
  if (!props.item || depBusy.value) return
  const next = (props.item.dependsOn ?? []).filter(d => d !== id)
  await applyDeps(next)
}

// Clear the inline error when switching tasks.
watch(() => props.item?.id, () => { depError.value = null; depAddSelect.value = '' })

// §6 «+N предпосылок»: transitive unfinished-ancestor count for the «Запустить» tooltip.
const runAncestorCount = computed(() =>
  props.item ? unfinishedAncestors(props.item.id, byId(boardStore.items)).length : 0,
)
const runTitle = computed(() =>
  runAncestorCount.value > 0 ? t('taskCard.prereqs', runAncestorCount.value) : undefined,
)

async function onDelete() {
  if (!props.item || actionLoading.value) return
  if (!confirm(t('drawer.confirmDelete', { id: props.item.id }))) return
  actionLoading.value = 'delete'
  try {
    await boardStore.deleteItem(props.item.id)
    toastStore.add('success', t('drawer.deleted', { id: props.item.id }))
    emit('close')
  } finally {
    actionLoading.value = null
  }
}

watch(() => props.item?.id, async (newId) => {
  if (!newId || !props.item?.lastIter) {
    details.value = null
    diffText.value = null
    reviewsData.value = null
    validationData.value = null
    verifyOutcome.value = null
    scopeExtra.value = []
    checksError.value = false
    return
  }
  // Open to the most relevant tab: running -> live stream; review/revision -> the review
  // result (so "why it went back" is immediately visible); otherwise the current tab.
  const st = props.item?.status
  if (st === 'in_progress') {
    taskStore.activeTab = DIALOG_TAB
    await loadTab(DIALOG_TAB)
  } else if (st === 'in_review' || st === 'needs_revision') {
    taskStore.activeTab = REVIEW_TAB
    await loadTab(REVIEW_TAB)
  } else {
    await loadTab(taskStore.activeTab)
  }
}, { immediate: true })

watch(() => taskStore.activeTab, async (newTab) => {
  if (isOpen.value) await loadTab(newTab)
})

async function loadTab(idx: number, force = false) {
  if (!props.item?.lastIter) return
  const dir = props.item.lastIter
  if (!force) tabLoading.value = true
  try {
    switch (idx) {
      case 0: // Описание
        details.value = (await taskStore.fetchDetails(dir, force)) ?? null
        break
      case 1: // Итерации
        details.value = (await taskStore.fetchDetails(dir, force)) ?? null
        break
      case 2: // Диалог — DialogPane self-fetches + live-tails; nothing to load here
        break
      case 3: // Дифф
        diffText.value = await taskStore.fetchDiff(dir, force) ?? null
        break
      case 4: // Ревью
        reviewsData.value = await taskStore.fetchReviews(dir, force) ?? null
        validationData.value = await taskStore.fetchValidation(dir, force) ?? null
        break
      case 5: // Проверки
        if (props.item?.id) {
          const checks = await taskStore.fetchChecks(props.item.id, force)
          checksError.value = checks === null
          verifyOutcome.value = checks?.verifyOutcome ?? null
          scopeExtra.value = checks?.scopeExtra ?? []
        }
        break
    }
  } finally {
    if (!force) tabLoading.value = false
  }
}

// While the task is running, re-poll the active tab so Diff/Activity update ~live
// (no WebSocket; force-bypasses the cache). Stops as soon as it leaves in_progress.
let _pollTimer: ReturnType<typeof setInterval> | null = null
function stopPoll() {
  if (_pollTimer !== null) { clearInterval(_pollTimer); _pollTimer = null }
}
watch(() => [props.item?.id, props.item?.status, taskStore.activeTab], () => {
  stopPoll()
  if (props.item?.status === 'in_progress' && props.item?.lastIter) {
    _pollTimer = setInterval(() => { void loadTab(taskStore.activeTab, true) }, 3000)
  }
}, { immediate: true })
onUnmounted(stopPoll)

function setTab(idx: number) {
  taskStore.activeTab = idx
}

function isVerdictArray(val: unknown): val is Verdict[] {
  if (!Array.isArray(val)) return false
  return val.every(v => v && typeof v === 'object' && 'reviewer' in v && 'verdict' in v)
}

const verdicts = computed<Verdict[]>(() => {
  if (!reviewsData.value) return []
  const v = reviewsData.value.verdicts
  if (isVerdictArray(v)) return v
  return []
})

const costUsd = computed(() => {
  if (!details.value) return '—'
  return `$${details.value.cost.cost_usd.toFixed(4)}`
})

const tokenTotal = computed(() => {
  if (!details.value) return '—'
  return details.value.cost.total.toLocaleString()
})

async function copyToClipboard(text: string, label: string) {
  try {
    await navigator.clipboard.writeText(text)
    toastStore.add('success', t('drawer.copied', { label }))
  } catch {
    toastStore.add('error', t('drawer.copyError', { label }))
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="drawer">
      <div v-if="isOpen && item" class="drawer-overlay" @click.self="emit('close')">
        <aside class="drawer-panel">
          <div class="drawer-header">
            <div class="drawer-title-row">
              <span class="drawer-id">{{ item.id }}</span>
              <StatusBadge :status="item.status" />
              <button class="drawer-close" @click="emit('close')" :title="t('drawer.close')">✕</button>
            </div>
            <div class="drawer-subtitle">{{ item.title }}</div>
          </div>

          <div class="drawer-tabs">
            <button
              v-for="(label, i) in TABS"
              :key="i"
              class="tab-btn"
              :class="{ active: tab === i }"
              @click="setTab(i)"
            >
              {{ label }}
            </button>
          </div>

          <div class="drawer-body">
            <div v-if="tabLoading" class="tab-loading">{{ t('drawer.loading') }}</div>

            <!-- Описание -->
            <template v-else-if="tab === 0">
              <section class="desc-section">
                <h4>{{ t('drawer.proposal') }}</h4>
                <p class="desc-text">{{ item.proposal || '—' }}</p>
              </section>
              <section class="desc-section">
                <h4>{{ t('drawer.rationale') }}</h4>
                <p class="desc-text">{{ item.why || '—' }}</p>
              </section>
              <section class="desc-section">
                <h4>{{ t('drawer.acceptance') }}</h4>
                <p class="desc-text">{{ item.acceptance || '—' }}</p>
              </section>
              <section class="desc-section">
                <h4>{{ t('drawer.touches') }}</h4>
                <div class="touches-list">
                  <code v-for="f in item.touches" :key="f">{{ f }}</code>
                  <span v-if="!item.touches.length">—</span>
                </div>
              </section>
              <!-- §4 Dependency editor -->
              <section class="desc-section">
                <h4>{{ t('drawer.deps') }}</h4>
                <div class="dep-row">
                  <span class="dep-label">{{ t('drawer.requires') }}</span>
                  <span
                    v-for="d in (item.dependsOn ?? [])"
                    :key="'dep-' + d"
                    class="dep-chip-edit"
                    data-test="dep-chip"
                  >
                    {{ d }}
                    <button
                      class="dep-remove"
                      data-test="dep-remove"
                      :title="t('drawer.removeDep')"
                      :disabled="depBusy"
                      @click="onRemoveDep(d)"
                    >✕</button>
                  </span>
                  <span v-if="!(item.dependsOn?.length)" class="dep-none">—</span>
                </div>
                <div class="dep-add-row">
                  <select
                    v-model="depAddSelect"
                    class="dep-add-select"
                    data-test="dep-add-select"
                    :disabled="depBusy"
                    @change="onAddDep"
                  >
                    <option value="" disabled>{{ t('drawer.addDep') }}</option>
                    <option v-for="c in depCandidates" :key="c.id" :value="c.id">
                      {{ c.id }} — {{ c.title }}
                    </option>
                  </select>
                </div>
                <div v-if="depError" class="dep-error" data-test="dep-error">{{ depError }}</div>
                <div v-if="item.blocks?.length" class="dep-row">
                  <span class="dep-label">{{ t('drawer.blocks') }}</span>
                  <code v-for="b in item.blocks" :key="'blk-' + b" class="dep-id">{{ b }}</code>
                </div>
              </section>
              <!-- tag editor -->
              <section class="desc-section">
                <h4>{{ t('drawer.tags') }}</h4>
                <div class="tags-row">
                  <span
                    v-for="tg in (item.tags ?? [])"
                    :key="'tag-' + tg"
                    class="tag-chip"
                    data-test="task-tag-chip"
                  >
                    {{ tg }}
                    <button
                      class="tag-remove"
                      data-test="task-tag-remove"
                      :title="t('drawer.removeTag')"
                      :disabled="tagSaving"
                      @click="removeTag(tg)"
                    >✕</button>
                  </span>
                  <span v-if="!(item.tags?.length)" class="tag-none">—</span>
                </div>
                <div class="tag-add-row">
                  <input
                    v-model="tagInput"
                    type="text"
                    class="tag-add-input"
                    data-test="task-tag-add"
                    :placeholder="t('drawer.addTag')"
                    :disabled="tagSaving"
                    @keydown.enter.prevent="addTag"
                  />
                </div>
              </section>
              <!-- Epic 2: complexity + model override -->
              <section class="desc-section">
                <h4>{{ t('drawer.complexity') }}</h4>
                <p class="desc-text">{{ item.complexity ?? '—' }}</p>
              </section>
              <section v-if="details" class="desc-section">
                <div class="section-header-row">
                  <h4>{{ t('drawer.commitMsg') }}</h4>
                  <button
                    v-if="details.commit_msg"
                    class="copy-btn"
                    @click="copyToClipboard(details.commit_msg, t('drawer.commitMsg'))"
                  >
                    {{ t('drawer.copy') }}
                  </button>
                </div>
                <pre class="commit-msg">{{ details.commit_msg || '—' }}</pre>
              </section>
            </template>

            <!-- Итерации -->
            <template v-else-if="tab === 1">
              <div class="iter-info">
                <div class="cost-row">
                  <span>{{ t('drawer.tokens') }}</span>
                  <span class="mono">{{ tokenTotal }}</span>
                </div>
                <div class="cost-row">
                  <span>{{ t('drawer.cost') }}</span>
                  <span class="mono">{{ costUsd }}</span>
                </div>
                <div v-if="item.lastIter" class="iter-chips">
                  <IterChip :iter="item.lastIter" active />
                  <IterChip v-for="br in item.previousBranches" :key="br" :iter="br" />
                </div>
                <div v-if="item.attempts > 0" class="cost-row">
                  <span>{{ t('drawer.attempts') }}</span>
                  <span class="mono">{{ item.attempts }}</span>
                </div>
              </div>
            </template>

            <!-- Диалог — one readable, live agent conversation (was Активность/Инструменты/Таймлайн/Live) -->
            <template v-else-if="tab === 2">
              <DialogPane
                :iter-dir="item?.lastIter ?? null"
                :running="item?.status === 'in_progress'"
              />
            </template>

            <!-- Дифф -->
            <template v-else-if="tab === 3">
              <div v-if="diffText" class="diff-section">
                <div class="diff-header-row">
                  <span class="diff-label">diff</span>
                  <button
                    class="copy-btn"
                    @click="copyToClipboard(diffText, t('drawer.diffLabel'))"
                  >
                    {{ t('drawer.copy') }}
                  </button>
                </div>
                <pre class="diff-viewer">{{ diffText }}</pre>
              </div>
              <div v-else class="tab-empty">{{ t('drawer.noChanges') }}</div>
            </template>

            <!-- Ревью -->
            <template v-else-if="tab === 4">
              <DrawerReviewPanel :validation="validationData" :verdicts="verdicts" :reviews="reviewsData" />
            </template>

            <!-- Проверки -->
            <template v-else-if="tab === 5">
              <DrawerChecksPanel :verify-outcome="verifyOutcome" :scope-extra="scopeExtra" :checks-error="checksError" />
            </template>
          </div>

          <!-- Action buttons -->
          <DrawerActions
            :item="item"
            :action-loading="actionLoading"
            :can-run="canRun"
            :can-unqueue="canUnqueue"
            :can-move-top="canMoveTop"
            :can-requeue="canRequeue"
            :run-title="runTitle"
            @run="onRun"
            @unqueue="onUnqueue"
            @move-top="onMoveTop"
            @requeue="onRequeue"
            @delete="onDelete"
            @open-conversation="openConversation"
            @merged="boardStore.fetchState()"
          />
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.drawer-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.5);
  z-index: 100;
  display: flex;
  justify-content: flex-end;
}

.drawer-panel {
  width: min(640px, 90vw);
  background: var(--panel);
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.drawer-enter-active { transition: transform 0.2s ease; }
.drawer-leave-active { transition: transform 0.15s ease; }
.drawer-enter-from,
.drawer-leave-to { transform: translateX(100%); }

.drawer-header {
  padding: 16px 20px 12px;
  border-bottom: 1px solid var(--border);
}

.drawer-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.drawer-id {
  font-family: var(--mono);
  font-size: 13px;
  color: var(--primary);
}

.drawer-close {
  margin-left: auto;
  background: none;
  border: none;
  color: var(--muted);
  font-size: 16px;
  cursor: pointer;
  padding: 2px 6px;
}
.drawer-close:hover { color: var(--text); }

.drawer-subtitle {
  font-size: 14px;
  color: var(--text);
  margin-top: 6px;
  line-height: 1.4;
}

.drawer-tabs {
  display: flex;
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
}

.tab-btn {
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--muted);
  font-size: 12px;
  padding: 10px 14px;
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.15s, border-color 0.15s;
}
.tab-btn:hover { color: var(--text); }
.tab-btn.active {
  color: var(--primary);
  border-bottom-color: var(--primary);
}

.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.tab-loading, .tab-empty {
  text-align: center;
  padding: 30px 0;
  color: var(--muted);
  font-size: 13px;
}

/* Model select */

/* Description */
.desc-section { margin-bottom: 16px; }
.desc-section h4 {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  margin: 0 0 6px;
}
.desc-section .section-header-row + .commit-msg { margin-top: 0; }
.desc-text {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text);
  margin: 0;
  white-space: pre-wrap;
}
.touches-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.touches-list code {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--cyan);
  background: var(--panel-2);
  padding: 2px 6px;
  border-radius: 3px;
}
.dep-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-bottom: 6px; }
.dep-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
}
.dep-id {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--blue);
  background: var(--panel-2);
  padding: 2px 6px;
  border-radius: 3px;
}
.dep-chip-edit {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--blue);
  background: var(--panel-2);
  border: 1px solid var(--border);
  padding: 2px 4px 2px 6px;
  border-radius: 3px;
}
.dep-remove {
  background: none;
  border: none;
  color: var(--muted);
  cursor: pointer;
  font-size: 10px;
  line-height: 1;
  padding: 0 2px;
}
.dep-remove:hover { color: var(--rose); }
.dep-none { font-size: 11px; color: var(--muted); }
.dep-add-row { margin-top: 8px; }
.dep-add-select {
  font-family: var(--mono);
  font-size: 11px;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  padding: 4px 8px;
  max-width: 100%;
  cursor: pointer;
}
.dep-add-select:focus { outline: none; border-color: var(--primary); }
.dep-error {
  margin-top: 8px;
  font-size: 11px;
  color: var(--rose);
  font-family: var(--mono);
}

/* Tag editor */
.tags-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.tag-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--cyan);
  background: var(--panel-2);
  border: 1px solid var(--border);
  padding: 2px 4px 2px 6px;
  border-radius: 3px;
}
.tag-remove {
  background: none;
  border: none;
  color: var(--muted);
  cursor: pointer;
  font-size: 10px;
  line-height: 1;
  padding: 0 2px;
}
.tag-remove:hover { color: var(--rose); }
.tag-none { font-size: 11px; color: var(--muted); }
.tag-add-row { margin-top: 8px; }
.tag-add-input {
  font-family: var(--mono);
  font-size: 11px;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  padding: 4px 8px;
  width: 180px;
  max-width: 100%;
}
.tag-add-input:focus { outline: none; border-color: var(--primary); }
.tag-add-input::placeholder { color: var(--muted); }

.commit-msg {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text);
  background: var(--panel-2);
  padding: 8px;
  border-radius: 4px;
  white-space: pre-wrap;
  margin: 0;
}

.section-header-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.section-header-row h4 { margin: 0; }

.copy-btn {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 2px 8px;
  cursor: pointer;
  transition: color 0.12s, border-color 0.12s;
}
.copy-btn:hover { color: var(--text); border-color: var(--muted); }

.diff-section { display: flex; flex-direction: column; gap: 6px; }
.diff-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.diff-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
}

/* Iterations */
.iter-info { display: flex; flex-direction: column; gap: 8px; }
.cost-row {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: var(--text);
}
.mono { font-family: var(--mono); }
.iter-chips { display: flex; flex-wrap: wrap; gap: 4px; }

/* Events */
.event-stream { display: flex; flex-direction: column; gap: 2px; }
.event-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
  padding: 4px 0;
  border-bottom: 1px solid var(--border);
}
.ev-icon { font-size: 12px; min-width: 16px; text-align: center; }
.ev-text {
  flex: 1;
  color: var(--text);
  font-family: var(--mono);
  font-size: 11px;
  line-height: 1.4;
  word-break: break-all;
}
.ev-ts {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
  white-space: nowrap;
}
.event-reasoning .ev-text { color: var(--violet); }
.event-tool_call .ev-text { color: var(--cyan); }
.event-tool_result .ev-text { color: var(--muted); }

/* Tools */
.tool-list { display: flex; flex-direction: column; gap: 4px; }
.tool-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 6px 8px;
  background: var(--panel-2);
  border-radius: 4px;
}
.tool-name {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--cyan);
  font-weight: 600;
}
.tool-args {
  flex: 1;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Diff */
.diff-viewer {
  font-family: var(--mono);
  font-size: 11px;
  line-height: 1.5;
  color: var(--text);
  background: var(--panel-2);
  padding: 12px;
  border-radius: 4px;
  overflow-x: auto;
  white-space: pre;
  margin: 0;
}

/* Reviews */
/* Ревью / Проверки CSS moved to DrawerReviewPanel.vue / DrawerChecksPanel.vue */

/* Agents */
.agents-placeholder {
  text-align: center;
  padding: 30px 0;
  color: var(--muted);
  font-size: 13px;
}
.agent-override {
  margin-top: 8px;
  font-size: 13px;
  color: var(--text);
}

/* Action buttons + Ревью/Проверки styles moved to DrawerActions/DrawerReviewPanel/DrawerChecksPanel */
</style>
