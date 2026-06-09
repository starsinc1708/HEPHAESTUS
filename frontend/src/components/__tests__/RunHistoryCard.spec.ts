import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import RunHistoryCard from '@/components/RunHistoryCard.vue'
import { api } from '@/api/client'
import type { RunSummary } from '@/types/api'

vi.mock('@/api/client', () => ({ api: { driverRuns: vi.fn() } }))
type Fn = ReturnType<typeof vi.fn>

function run(p: Partial<RunSummary>): RunSummary {
  return {
    runMode: 'queue', startedAtMs: 0, endedAtMs: 0, itemsDone: 0, itemsFailed: 0,
    consecFail: 0, costUsd: 0, stoppedReason: '', ...p,
  }
}

beforeEach(() => vi.clearAllMocks())

describe('RunHistoryCard (FEAT-005)', () => {
  it('shows the empty state when there is no history', async () => {
    ;(api.driverRuns as Fn).mockResolvedValue({ ok: true, runs: [], total: 0, offset: 0, limit: 8 })
    const w = mount(RunHistoryCard)
    await flushPromises()
    expect(w.find('[data-test="run-history-empty"]').exists()).toBe(true)
  })

  it('renders a row per run with done/failed counts and aggregates totals', async () => {
    ;(api.driverRuns as Fn).mockResolvedValue({
      ok: true,
      total: 2,
      offset: 0,
      limit: 8,
      runs: [
        run({ runMode: 'ralph', itemsDone: 3, itemsFailed: 1, costUsd: 0.5, stoppedReason: 'goal-complete (dry)' }),
        run({ runMode: 'queue', itemsDone: 2, itemsFailed: 0, costUsd: 0.25 }),
      ],
    })
    const w = mount(RunHistoryCard)
    await flushPromises()

    const rows = w.findAll('[data-test="run-history-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('ralph')
    // Totals: done 3+2=5, failed 1+0=1, cost 0.75.
    const totals = w.find('[data-test="run-history-totals"]').text()
    expect(totals).toContain('5')
    expect(totals).toContain('1')
    expect(totals).toContain('0.7500')
  })

  it('never crashes when the request fails', async () => {
    ;(api.driverRuns as Fn).mockRejectedValue(new Error('boom'))
    const w = mount(RunHistoryCard)
    await flushPromises()
    // Falls through to the empty state rather than throwing.
    expect(w.find('[data-test="run-history-empty"]').exists()).toBe(true)
  })

  it('requests only the first page (limit 8)', async () => {
    ;(api.driverRuns as Fn).mockResolvedValue({ ok: true, runs: [], total: 0, offset: 0, limit: 8 })
    mount(RunHistoryCard)
    await flushPromises()
    expect(api.driverRuns).toHaveBeenCalledWith(0, 8)
  })
})
