import { ref, computed, onUnmounted } from 'vue'
import type { AgentJobStatus } from '@/types/api'
import { api } from '@/api/client'

const POLL_INTERVAL_MS = 1500

export function useAgentJob() {
  const jobId = ref<string | null>(null)
  const status = ref<AgentJobStatus | 'idle'>('idle')
  const result = ref<any>(null)
  const error = ref<string | null>(null)

  const streamUrl = computed(() =>
    jobId.value ? `/api/v1/agent-jobs/${jobId.value}/stream` : undefined,
  )

  let timer: ReturnType<typeof setInterval> | null = null
  let unmounted = false

  function clearTimer() {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  onUnmounted(() => {
    unmounted = true
    clearTimer()
  })

  async function run(start: () => Promise<{ jobId: string }>): Promise<void> {
    // Reset state
    jobId.value = null
    status.value = 'idle'
    result.value = null
    error.value = null
    clearTimer()

    let startResult: { jobId: string }
    try {
      startResult = await start()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
      status.value = 'failed'
      return
    }

    if (unmounted) return

    jobId.value = startResult.jobId
    status.value = 'running'

    await new Promise<void>((resolve) => {
      async function poll() {
        if (unmounted) {
          clearTimer()
          resolve()
          return
        }
        try {
          const job = await api.getAgentJob(startResult.jobId)
          if (unmounted) { clearTimer(); resolve(); return }
          status.value = job.status
          if (job.status === 'done') {
            result.value = job.result ?? null
            error.value = null
            clearTimer()
            resolve()
          } else if (job.status === 'failed') {
            error.value = job.error ?? 'Job failed'
            result.value = null
            clearTimer()
            resolve()
          }
          // else 'running' — continue polling
        } catch (e: unknown) {
          if (!unmounted) {
            error.value = e instanceof Error ? e.message : String(e)
            status.value = 'failed'
            clearTimer()
            resolve()
          }
        }
      }

      // Poll immediately, then on interval
      void poll()
      timer = setInterval(() => { void poll() }, POLL_INTERVAL_MS)
    })
  }

  return { jobId, status, result, error, streamUrl, run }
}
