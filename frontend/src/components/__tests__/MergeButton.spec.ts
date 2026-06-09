import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import MergeButton from '../MergeButton.vue'
import { api } from '@/api/client'

vi.mock('@/api/client', () => ({
  api: {
    mergePreflight: vi.fn(),
    startMerge: vi.fn(),
    getMergeJob: vi.fn(),
    getActiveMergeJob: vi.fn(),
    acceptMerge: vi.fn(),
    rejectMerge: vi.fn(),
  },
}))

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  // Default getMergeJob returns a terminal state so the panel stops polling
  ;(api.getMergeJob as ReturnType<typeof vi.fn>).mockResolvedValue({
    ok: true, id: 'merge-0001', branch: 'auto/x-1', baseBranch: 'main',
    status: 'resolved', decision: 'ai_merged', conflicts: [], resolvedFiles: [],
    diff: null, verifyOk: true,
  })
  // Default: no in-flight merge to re-attach.
  ;(api.getActiveMergeJob as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, job: null })
  ;(api.acceptMerge as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true })
  ;(api.rejectMerge as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true })
})

describe('MergeButton', () => {
  it('disables button when preflight not ok', async () => {
    ;(api.mergePreflight as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false, cleanTree: false, verifyGreen: true, validationPassed: true,
      loopActive: false, baseBranch: 'main', conflicts: [],
    })
    const w = mount(MergeButton, { props: { branch: 'auto/x-1' } })
    await flushPromises()
    expect(w.find('[data-test="merge-btn"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="preflight-tooltip"]').text()).toContain('рабочее дерево')
  })

  it('explains an unverified gate instead of the generic verify message', async () => {
    ;(api.mergePreflight as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false, cleanTree: true, verifyGreen: false, verifyUnverified: true,
      validationPassed: true, loopActive: false, baseBranch: 'main', conflicts: [],
    })
    const w = mount(MergeButton, { props: { branch: 'auto/x-1' } })
    await flushPromises()
    const tip = w.find('[data-test="preflight-tooltip"]').text()
    expect(tip).toContain('тесты не прогонялись')
    expect(tip).not.toContain('verify не зелёный')
  })

  it('enables button when preflight ok', async () => {
    ;(api.mergePreflight as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, cleanTree: true, verifyGreen: true, validationPassed: true,
      loopActive: false, baseBranch: 'main', conflicts: [],
    })
    const w = mount(MergeButton, { props: { branch: 'auto/x-1' } })
    await flushPromises()
    expect(w.find('[data-test="merge-btn"]').attributes('disabled')).toBeUndefined()
  })

  it('stays disabled via the disabled prop even when preflight is ok', async () => {
    ;(api.mergePreflight as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, cleanTree: true, verifyGreen: true, validationPassed: true,
      loopActive: false, baseBranch: 'main', conflicts: [],
    })
    const w = mount(MergeButton, { props: { branch: 'auto/x-1', disabled: true } })
    await flushPromises()
    expect(w.find('[data-test="merge-btn"]').attributes('disabled')).toBeDefined()
  })

  it('calls startMerge when button clicked', async () => {
    ;(api.mergePreflight as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, cleanTree: true, verifyGreen: true, validationPassed: true,
      loopActive: false, baseBranch: 'main', conflicts: [],
    })
    ;(api.startMerge as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, jobId: 'merge-0001', status: 'running',
    })
    const w = mount(MergeButton, { props: { branch: 'auto/x-1' } })
    await flushPromises()
    await w.find('[data-test="merge-btn"]').trigger('click')
    await flushPromises()
    expect(api.startMerge).toHaveBeenCalledWith('auto/x-1', { push: false, aiResolve: true, autoAccept: false })
  })

  it('re-attaches an active merge job for this branch on mount', async () => {
    ;(api.mergePreflight as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false, cleanTree: true, verifyGreen: true, validationPassed: true,
      loopActive: false, baseBranch: 'main', conflicts: [],
    })
    ;(api.getActiveMergeJob as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, job: { id: 'merge-0009', branch: 'auto/x-1', baseBranch: 'main', status: 'resolved' },
    })
    const w = mount(MergeButton, { props: { branch: 'auto/x-1' }, global: { stubs: { teleport: true } } })
    await flushPromises()
    // The panel re-opened for the in-flight job (its Accept button is present).
    expect(w.find('[data-test="accept-merge"]').exists()).toBe(true)
    expect(api.getMergeJob).toHaveBeenCalledWith('merge-0009')
  })

  it('does NOT re-attach a job for a different branch', async () => {
    ;(api.mergePreflight as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, cleanTree: true, verifyGreen: true, validationPassed: true,
      loopActive: false, baseBranch: 'main', conflicts: [],
    })
    ;(api.getActiveMergeJob as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, job: { id: 'merge-0009', branch: 'auto/OTHER', baseBranch: 'main', status: 'resolved' },
    })
    const w = mount(MergeButton, { props: { branch: 'auto/x-1' }, global: { stubs: { teleport: true } } })
    await flushPromises()
    expect(w.find('[data-test="accept-merge"]').exists()).toBe(false)
  })
})
