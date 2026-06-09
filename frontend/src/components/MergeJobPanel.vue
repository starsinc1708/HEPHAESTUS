<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import type { MergeJob, MergeJobStatus } from '@/types/api'
import { api } from '@/api/client'
import LiveConsole from './LiveConsole.vue'

const { t } = useI18n()
const props = defineProps<{ jobId: string }>()
const emit = defineEmits<{ merged: []; closed: [] }>()

const job = ref<(MergeJob & { ok: boolean }) | null>(null)
const push = ref(false)
const accepting = ref(false)
const rejecting = ref(false)
const actionError = ref<string | null>(null)

const TERMINAL: MergeJobStatus[] = ['resolved', 'accepted', 'rejected', 'failed', 'conflict']
const IN_PROGRESS: MergeJobStatus[] = ['running', 'resolving', 'verifying']
// The merge runs verify (ruff/mypy/tests · vue-tsc/vitest) on the merged tree. Its log is the
// merge's real "history" — especially for an auto-merge (no resolver agent) and on a failure.
const VERIFY_VISIBLE: MergeJobStatus[] = ['verifying', 'resolved', 'failed', 'accepted']
const verifyLog = ref('')

let timer: ReturnType<typeof setInterval> | null = null

// Only show the resolver agent's console when an AI agent is actually involved: while it
// is resolving conflicts, or after it resolved them (decision=ai_merged). An auto_merged
// (no-conflict) job runs NO agent — during its `verifying` step the console would just sit
// empty ("агент работает… 0 событий"), so don't show it. The verify step's own progress is
// conveyed by the status text + the diff, not an agent stream.
const showConsole = computed(() => {
  const j = job.value
  if (!j) return false
  return j.status === 'resolving' || j.decision === 'ai_merged'
})

async function fetchJob() {
  try {
    const result = await api.getMergeJob(props.jobId)
    job.value = result
    if (VERIFY_VISIBLE.includes(result.status)) {
      try {
        const vl = await api.mergeJobVerifyLog(props.jobId)
        if (vl.ok && vl.log) verifyLog.value = vl.log
      } catch { /* best effort — keep stale log */ }
    }
    if (result.status === 'accepted') emit('merged')
    if (TERMINAL.includes(result.status) && timer !== null) {
      clearInterval(timer)
      timer = null
    }
  } catch {
    // keep stale data on transient errors
  }
}

onMounted(async () => {
  await fetchJob()
  if (job.value && !TERMINAL.includes(job.value.status)) {
    timer = setInterval(fetchJob, 1000)
  }
})

onBeforeUnmount(() => {
  if (timer !== null) { clearInterval(timer); timer = null }
})

async function acceptMerge() {
  if (!job.value) return
  accepting.value = true
  actionError.value = null
  try {
    const res = await api.acceptMerge(props.jobId, push.value)
    if (res.ok) emit('merged')
    else actionError.value = res.error ?? 'Accept failed'
  } catch (e: unknown) {
    actionError.value = e instanceof Error ? e.message : String(e)
  } finally {
    accepting.value = false
  }
}

async function rejectMerge() {
  if (!job.value) return
  rejecting.value = true
  actionError.value = null
  try {
    await api.rejectMerge(props.jobId)
    emit('closed')
  } catch (e: unknown) {
    actionError.value = e instanceof Error ? e.message : String(e)
  } finally {
    rejecting.value = false
  }
}

// Closing a still-active (resolved) job discards the candidate so it never blocks
// future merges or leaves an orphan worktree; a terminal job just closes.
function close() {
  if (job.value && job.value.status === 'resolved') {
    void rejectMerge()
  } else {
    emit('closed')
  }
}
</script>

<template>
  <Teleport to="body">
    <div class="mjp-overlay" @click.self="close">
      <div class="mjp-dialog" role="dialog" aria-modal="true">
        <header class="mjp-head">
          <div class="mjp-title">
            AI-merge
            <span v-if="job" class="status-pill" :class="'status-' + job.status">{{ job.status }}</span>
            <span v-if="job && job.decision" class="decision-pill">{{ job.decision }}</span>
          </div>
          <button class="mjp-x" data-test="close-merge" :aria-label="t('mergeJob.close')" @click="close">✕</button>
        </header>

        <div class="mjp-body">
          <div v-if="!job" class="loading">{{ t('mergeJob.loadingJob') }}</div>
          <template v-else>
            <p v-if="IN_PROGRESS.includes(job.status)" class="muted">
              {{ t('mergeJob.inProgress', { phase: job.status === 'verifying' ? t('mergeJob.verifying') : t('mergeJob.resolving') }) }}
            </p>
            <p v-else-if="job.decision === 'auto_merged' && job.status === 'resolved'" class="muted">
              {{ t('mergeJob.autoMerge') }}
            </p>

            <LiveConsole
              v-if="showConsole"
              :iter-dir="null"
              :active="true"
              :stream-url="'/api/v1/merge-jobs/' + jobId + '/stream'"
            />

            <div v-if="verifyLog" class="verify-log-block" data-test="merge-verify-log">
              <div class="vl-head">{{ t('mergeJob.verifyOnMerged') }}</div>
              <pre class="verify-log">{{ verifyLog }}</pre>
            </div>

            <template v-if="job.status === 'resolved'">
              <pre v-if="job.diff" data-test="merge-diff" class="diff-block">{{ job.diff }}</pre>
              <p v-else class="muted">{{ t('mergeJob.diffEmpty') }}</p>
            </template>

            <template v-else-if="job.status === 'conflict' || job.status === 'failed'">
              <div class="conflict-block">
                <p v-if="job.error" class="error-msg">{{ job.error }}</p>
                <p v-if="job.conflicts && job.conflicts.length">{{ t('mergeJob.conflicts') }}</p>
                <ul v-if="job.conflicts && job.conflicts.length">
                  <li v-for="f in job.conflicts" :key="f">{{ f }}</li>
                </ul>
              </div>
            </template>

            <div v-else-if="job.status === 'accepted'" class="success-msg">{{ t('mergeJob.accepted') }}</div>
            <div v-else-if="job.status === 'rejected'" class="muted">{{ t('mergeJob.rejected') }}</div>

            <div v-if="actionError" class="error-msg">{{ actionError }}</div>
          </template>
        </div>

        <footer v-if="job && job.status === 'resolved'" class="mjp-actions">
          <label class="push-toggle">
            <input type="checkbox" v-model="push" />
            {{ t('mergeJob.pushAfter') }}
          </label>
          <span class="spacer" />
          <button class="btn-secondary" data-test="reject-merge" :disabled="rejecting || undefined" @click="rejectMerge">
            {{ rejecting ? t('mergeJob.rejecting') : t('mergeJob.reject') }}
          </button>
          <button class="btn-primary" data-test="accept-merge" :disabled="accepting || undefined" @click="acceptMerge">
            {{ accepting ? t('mergeJob.accepting') : t('mergeJob.accept') }}
          </button>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.mjp-overlay {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(0, 0, 0, 0.6);
  display: flex; align-items: center; justify-content: center; padding: 24px;
}
.mjp-dialog {
  width: min(820px, 96vw); max-height: 88vh; display: flex; flex-direction: column;
  background: var(--surface, #15171c); border: 1px solid var(--border, #2a2d34);
  border-radius: 10px; box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5); overflow: hidden;
}
.mjp-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--border, #2a2d34); flex-shrink: 0;
}
.mjp-title { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.mjp-x {
  background: none; border: none; color: var(--muted); font-size: 16px; cursor: pointer;
  padding: 4px 8px; border-radius: 6px;
}
.mjp-x:hover { background: var(--surface2, #1e2027); color: var(--text); }
.mjp-body { padding: 14px 16px; overflow: auto; display: flex; flex-direction: column; gap: 10px; }
.mjp-actions {
  display: flex; align-items: center; gap: 10px; padding: 12px 16px;
  border-top: 1px solid var(--border, #2a2d34); flex-shrink: 0;
}
.spacer { flex: 1; }
.status-pill {
  display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: 600;
  background: var(--surface2, #1e2027);
}
.status-running, .status-resolving, .status-verifying { color: var(--amber, #ffb300); }
.status-resolved, .status-accepted { color: var(--green, #4caf50); }
.status-conflict, .status-failed { color: var(--rose, #e5484d); }
.status-rejected { color: var(--muted); }
.decision-pill { font-size: 11px; color: var(--muted); }
.diff-block {
  background: #0b0d10; border: 1px solid var(--border); border-radius: 6px; padding: 10px;
  font-family: var(--mono); font-size: 12px; line-height: 1.5; overflow: auto; max-height: 48vh;
  white-space: pre; margin: 0;
}
.verify-log-block { display: flex; flex-direction: column; gap: 4px; }
.vl-head { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
.verify-log {
  background: #0b0d10; border: 1px solid var(--border); border-radius: 6px; padding: 10px;
  font-family: var(--mono); font-size: 12px; line-height: 1.5; overflow: auto; max-height: 36vh;
  white-space: pre-wrap; word-break: break-word; margin: 0; color: #d6dee6;
}
.push-toggle { font-size: 13px; display: flex; align-items: center; gap: 4px; }
.btn-primary {
  background: var(--green, #2e7d32); color: #fff; border: none; padding: 7px 14px;
  border-radius: 6px; font-weight: 600; cursor: pointer;
}
.btn-secondary {
  background: var(--surface2, #1e2027); color: var(--text); border: 1px solid var(--border);
  padding: 7px 12px; border-radius: 6px; cursor: pointer;
}
button[disabled] { opacity: 0.5; cursor: not-allowed; }
.error-msg { color: var(--rose, #e5484d); font-size: 12px; }
.success-msg { color: var(--green, #4caf50); font-size: 13px; }
.muted { color: var(--muted); font-size: 13px; }
.conflict-block { border: 1px solid var(--rose, #e5484d); padding: 8px; border-radius: 6px; }
.loading { color: var(--muted); font-size: 13px; }
</style>
