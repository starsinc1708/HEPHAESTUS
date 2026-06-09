import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import GoalModal from '@/components/GoalModal.vue'
import { api } from '@/api/client'

vi.mock('@/api/client', () => ({
  api: {
    decomposeGoal: vi.fn(),
    getAgentJob: vi.fn(),
    goalTemplates: vi.fn(),
  },
}))

vi.mock('@/stores/toast', () => ({ useToastStore: () => ({ add: vi.fn() }) }))

type Fn = ReturnType<typeof vi.fn>

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  ;(api.decomposeGoal as Fn).mockResolvedValue({ ok: true, jobId: 'ajob-1', kind: 'decompose' })
  ;(api.getAgentJob as Fn).mockResolvedValue({
    ok: true, id: 'ajob-1', kind: 'decompose', status: 'done',
    result: { goalId: 'goal-1', taskIds: ['t1', 't2', 't3'] }, error: null, outputDir: 'ajob-1',
  })
  ;(api.goalTemplates as Fn).mockResolvedValue({
    ok: true,
    templates: [{ id: 'api-endpoint', title: 'Add endpoint', description: 'Create a GET endpoint + test' }],
  })
})

describe('GoalModal', () => {
  it('opens the modal from the «Новая цель» button', async () => {
    const w = mount(GoalModal)
    expect(w.find('[data-test="goal-modal"]').exists()).toBe(false)
    await w.find('[data-test="new-goal"]').trigger('click')
    expect(w.find('[data-test="goal-modal"]').exists()).toBe(true)
  })

  it('disables «Спланировать» until a title is entered', async () => {
    const w = mount(GoalModal)
    await w.find('[data-test="new-goal"]').trigger('click')
    expect(w.find('[data-test="plan-goal"]').attributes('disabled')).toBeDefined()
    await w.find('input[type="text"]').setValue('My goal')
    expect(w.find('[data-test="plan-goal"]').attributes('disabled')).toBeUndefined()
  })

  it('starts the async job, polls it, emits planned, and closes on done', async () => {
    const w = mount(GoalModal)
    await w.find('[data-test="new-goal"]').trigger('click')
    await w.find('input[type="text"]').setValue('Add retries')
    await w.find('[data-test="plan-goal"]').trigger('click')
    await flushPromises()

    expect(api.decomposeGoal).toHaveBeenCalledWith('Add retries', '', undefined)
    expect(api.getAgentJob).toHaveBeenCalledWith('ajob-1')
    expect(w.emitted('planned')).toHaveLength(1)
    // Modal closes after success.
    expect(w.find('[data-test="goal-modal"]').exists()).toBe(false)
  })

  it('forwards the optional max-tasks cap to decomposeGoal', async () => {
    const w = mount(GoalModal)
    await w.find('[data-test="new-goal"]').trigger('click')
    await w.find('input[type="text"]').setValue('Capped goal')
    await w.find('[data-test="goal-max"]').setValue(2)
    await w.find('[data-test="plan-goal"]').trigger('click')
    await flushPromises()

    expect(api.decomposeGoal).toHaveBeenCalledWith('Capped goal', '', 2)
  })

  it('fills title + description when a goal template is selected (FEAT-003)', async () => {
    const w = mount(GoalModal)
    await w.find('[data-test="new-goal"]').trigger('click')
    await flushPromises() // templates load
    const select = w.find('[data-test="goal-template"]')
    expect(select.exists()).toBe(true)
    await select.setValue('api-endpoint')
    expect((w.find('input[type="text"]').element as HTMLInputElement).value).toBe('Add endpoint')
    expect((w.find('textarea').element as HTMLTextAreaElement).value).toContain('GET')
  })

  it('does not call decomposeGoal when title is empty', async () => {
    const w = mount(GoalModal)
    await w.find('[data-test="new-goal"]').trigger('click')
    await w.find('[data-test="plan-goal"]').trigger('click')
    await flushPromises()
    expect(api.decomposeGoal).not.toHaveBeenCalled()
    expect(w.emitted('planned')).toBeUndefined()
  })
})
