import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { withSetup } from '../testUtils'

// Mock the api module before importing the composable
vi.mock('@/api/client', () => ({
  api: {
    getAgentJob: vi.fn(),
  },
}))

import { useAgentJob } from '@/composables/useAgentJob'
import { api } from '@/api/client'

describe('useAgentJob', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('starts idle', () => {
    const { result: composable } = withSetup(() => useAgentJob())
    expect(composable.status.value).toBe('idle')
    expect(composable.jobId.value).toBeNull()
    expect(composable.result.value).toBeNull()
    expect(composable.error.value).toBeNull()
    expect(composable.streamUrl.value).toBeUndefined()
  })

  it('run() with getAgentJob returning done immediately resolves status=done + result', async () => {
    // First call: running; second call: done with result
    ;(api.getAgentJob as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ ok: true, id: 'ajob-1', kind: 'ideas', status: 'running', result: null, error: null, outputDir: 'ajob-1' })
      .mockResolvedValueOnce({ ok: true, id: 'ajob-1', kind: 'ideas', status: 'done', result: { ideas: [{ id: 'i1', title: 'Test idea' }] }, error: null, outputDir: 'ajob-1' })

    const { result: composable } = withSetup(() => useAgentJob())

    const runPromise = composable.run(() => Promise.resolve({ jobId: 'ajob-1' }))

    // Flush the initial poll (returns 'running')
    await vi.runAllTimersAsync()

    // Advance timer to trigger the next interval poll (returns 'done')
    await vi.runAllTimersAsync()

    await runPromise

    expect(composable.status.value).toBe('done')
    expect(composable.result.value).toEqual({ ideas: [{ id: 'i1', title: 'Test idea' }] })
    expect(composable.error.value).toBeNull()
    expect(composable.jobId.value).toBe('ajob-1')
  })

  it('streamUrl is set while jobId is populated', async () => {
    ;(api.getAgentJob as ReturnType<typeof vi.fn>)
      .mockResolvedValue({ ok: true, id: 'ajob-1', kind: 'map', status: 'done', result: { count: 5 }, error: null, outputDir: 'ajob-1' })

    const { result: composable } = withSetup(() => useAgentJob())

    const runPromise = composable.run(() => Promise.resolve({ jobId: 'ajob-1' }))
    await vi.runAllTimersAsync()
    await runPromise

    expect(composable.streamUrl.value).toBe('/api/v1/agent-jobs/ajob-1/stream')
  })

  it('surfaces error when getAgentJob returns failed status', async () => {
    ;(api.getAgentJob as ReturnType<typeof vi.fn>)
      .mockResolvedValue({ ok: true, id: 'ajob-1', kind: 'map', status: 'failed', result: null, error: 'agent crashed', outputDir: 'ajob-1' })

    const { result: composable } = withSetup(() => useAgentJob())

    const runPromise = composable.run(() => Promise.resolve({ jobId: 'ajob-1' }))
    await vi.runAllTimersAsync()
    await runPromise

    expect(composable.status.value).toBe('failed')
    expect(composable.error.value).toBe('agent crashed')
  })

  it('surfaces error when start() rejects', async () => {
    const { result: composable } = withSetup(() => useAgentJob())

    await composable.run(() => Promise.reject(new Error('network error')))

    expect(composable.status.value).toBe('failed')
    expect(composable.error.value).toBe('network error')
  })
})
