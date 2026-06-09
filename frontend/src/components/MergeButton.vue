<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { MergePreflightResponse } from '@/types/api'
import { api } from '@/api/client'
import MergeJobPanel from './MergeJobPanel.vue'

const { t } = useI18n()
const props = defineProps<{ branch: string; disabled?: boolean }>()
const emit = defineEmits<{ merged: [] }>()

const preflight = ref<MergePreflightResponse | null>(null)
const pushAfter = ref(false)
const merging = ref(false)
const jobId = ref<string | null>(null)
const errorMsg = ref<string | null>(null)

const unmet = computed<string[]>(() => {
  const p = preflight.value
  if (!p) return [t('merge.loadingPreflight')]
  const u: string[] = []
  if (!p.cleanTree) u.push(t('merge.dirtyTree'))
  if (!p.verifyGreen) u.push(p.verifyUnverified ? t('merge.verifyUnverified') : t('merge.verifyNotGreen'))
  if (!p.validationPassed) u.push(t('merge.funnelFailed'))
  if (p.loopActive) u.push(t('merge.loopActive'))
  return u
})

const canMerge = computed(() => preflight.value?.ok === true && !merging.value && !jobId.value && !props.disabled)

async function loadPreflight() {
  try {
    preflight.value = await api.mergePreflight(props.branch)
  } catch {
    preflight.value = null
  }
}

async function doMerge() {
  if (!canMerge.value) return
  merging.value = true
  errorMsg.value = null
  try {
    const res = await api.startMerge(props.branch, { push: pushAfter.value, aiResolve: true, autoAccept: false })
    if (res.ok) {
      jobId.value = res.jobId
    } else {
      errorMsg.value = 'Merge job failed to start'
    }
  } catch (e: unknown) {
    errorMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    merging.value = false
  }
}

function onMerged() {
  jobId.value = null
  emit('merged')
}

function onClosed() {
  jobId.value = null
  void loadPreflight()
}

// Re-attach an in-flight merge for THIS branch after a page refresh, so the
// resolved-but-not-accepted job isn't stranded (it stays active server-side).
async function reattachActiveJob() {
  try {
    const res = await api.getActiveMergeJob()
    if (res.job && res.job.branch === props.branch
        && res.job.status !== 'accepted' && res.job.status !== 'rejected') {
      jobId.value = res.job.id
    }
  } catch { /* ignore — best effort */ }
}

onMounted(async () => {
  await loadPreflight()
  await reattachActiveJob()
})
</script>

<template>
  <div class="merge-button">
    <label class="push-toggle">
      <input type="checkbox" v-model="pushAfter" />
      {{ t('merge.pushAfter') }}
    </label>
    <button
      data-test="merge-btn"
      :disabled="!canMerge || undefined"
      @click="doMerge"
    >
      {{ merging ? t('merge.merging') : t('merge.mergeToBase') }}
    </button>
    <div v-if="unmet.length" data-test="preflight-tooltip" class="tooltip">
      {{ unmet.join(', ') }}
    </div>
    <div v-if="errorMsg" class="error">{{ errorMsg }}</div>

    <MergeJobPanel
      v-if="jobId"
      :job-id="jobId"
      @merged="onMerged"
      @closed="onClosed"
    />
  </div>
</template>

<style scoped>
.merge-button { display: flex; flex-direction: column; gap: 6px; }
button[disabled] { opacity: 0.5; cursor: not-allowed; }
.tooltip { font-size: 12px; color: var(--amber, #ffb300); }
.error { color: var(--rose, #e53935); font-size: 12px; }
</style>
