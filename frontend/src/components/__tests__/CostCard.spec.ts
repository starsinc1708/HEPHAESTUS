import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import CostCard from '../CostCard.vue'
import { api } from '@/api/client'

vi.mock('@/api/client', () => ({
  api: {
    getCostSummary: vi.fn(),
  },
}))

const mockCost = {
  ok: true,
  totalCostUsd: 1.23456,
  totalTokens: 50000,
  topTasks: [
    { id: 't1', title: 'Implement auth', costUsd: 0.5 },
    { id: 't2', title: 'Fix tests', costUsd: 0.3 },
  ],
  budgetUsd: 5.0,
}

describe('CostCard', () => {
  beforeEach(() => { vi.resetAllMocks() })

  it('renders cost summary from API', async () => {
    vi.mocked(api.getCostSummary).mockResolvedValue(mockCost)
    const w = mount(CostCard)
    await flushPromises()
    expect(w.find('[data-test="cost-total"]').text()).toContain('1.2346')
    expect(w.find('[data-test="cost-tokens"]').text()).toContain('50')
    expect(w.findAll('[data-test="cost-task"]').length).toBe(2)
  })

  it('shows budget indicator when budget is set', async () => {
    vi.mocked(api.getCostSummary).mockResolvedValue(mockCost)
    const w = mount(CostCard)
    await flushPromises()
    expect(w.find('[data-test="cost-budget"]').exists()).toBe(true)
  })

  it('hides budget when null', async () => {
    vi.mocked(api.getCostSummary).mockResolvedValue({ ...mockCost, budgetUsd: null })
    const w = mount(CostCard)
    await flushPromises()
    expect(w.find('[data-test="cost-budget"]').exists()).toBe(false)
  })

  it('shows zeros gracefully', async () => {
    vi.mocked(api.getCostSummary).mockResolvedValue({
      ok: true, totalCostUsd: 0, totalTokens: 0, topTasks: [], budgetUsd: null,
    })
    const w = mount(CostCard)
    await flushPromises()
    expect(w.find('[data-test="cost-total"]').text()).toContain('$0.0000')
  })
})
