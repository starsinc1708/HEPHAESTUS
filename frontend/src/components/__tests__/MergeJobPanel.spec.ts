import { mount, flushPromises } from '@vue/test-utils'
import { vi, describe, it, expect } from 'vitest'
import MergeJobPanel from '../MergeJobPanel.vue'

vi.mock('@/api/client', () => ({ api: {
  getMergeJob: vi.fn().mockResolvedValue({ ok: true, id: 'merge-0001', branch: 'auto/x',
    baseBranch: 'main', status: 'resolved', decision: 'ai_merged', conflicts: ['f.txt'],
    resolvedFiles: ['f.txt'], diff: 'diff --git a/f b/f', verifyOk: true }),
  acceptMerge: vi.fn().mockResolvedValue({ ok: true }),
  rejectMerge: vi.fn().mockResolvedValue({ ok: true }),
}}))

// The panel renders inside a <Teleport to="body">; stub it so VTU keeps the
// content inside the wrapper (findable + in w.text()).
const mountPanel = () =>
  mount(MergeJobPanel, { props: { jobId: 'merge-0001' }, global: { stubs: { teleport: true } } })

describe('MergeJobPanel', () => {
  it('shows resolved diff and Accept/Reject', async () => {
    const w = mountPanel()
    await flushPromises()
    expect(w.text()).toContain('diff --git')
    expect(w.find('[data-test="accept-merge"]').exists()).toBe(true)
    expect(w.find('[data-test="reject-merge"]').exists()).toBe(true)
  })
  it('calls acceptMerge on Accept click', async () => {
    const { api } = await import('@/api/client')
    const w = mountPanel()
    await flushPromises()
    await w.find('[data-test="accept-merge"]').trigger('click')
    expect(api.acceptMerge).toHaveBeenCalledWith('merge-0001', false)
  })
})
