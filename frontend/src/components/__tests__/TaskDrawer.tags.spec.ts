import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import TaskDrawer from '@/components/TaskDrawer.vue'
import { api } from '@/api/client'

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return {
    ...actual,
    api: {
      getState: vi.fn().mockResolvedValue({ items: [], summary: {} }),
      setTaskTags: vi.fn().mockResolvedValue({ ok: true }),
      patchDeps: vi.fn().mockResolvedValue({ ok: true }),
      iterDetails: vi.fn().mockResolvedValue(null),
      iterDiff: vi.fn().mockResolvedValue(null),
      iterReviews: vi.fn().mockResolvedValue(null),
      iterEvents: vi.fn().mockResolvedValue([]),
      getTaskChecks: vi.fn().mockResolvedValue({ ok: true, verifyOutcome: null }),
    },
  }
})

vi.mock('@/stores/toast', () => ({ useToastStore: () => ({ add: vi.fn() }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

const base = {
  id: 'task-1', title: 'Task A', status: 'pending' as const, attempts: 0,
  proposal: 'p', why: 'w', acceptance: 'a', touches: [], branch: null,
  lastIter: null, previousBranches: [], commit: null,
  planFile: '', planSection: '', wave: '', severity: null, category: null,
  sourceScan: null, selfReportedFailure: false, requeuedAt: null, review: null,
  mergeCommit: null, mergedAt: null,
  tags: ['bug', 'urgent'], dependsOn: [], blocks: [], orderIndex: 0,
}

describe('TaskDrawer tag editor', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('renders tags as chips with remove button', async () => {
    const w = mount(TaskDrawer, { props: { item: base as never }, attachTo: document.body })
    expect(document.body.textContent).toContain('Теги')
    expect(document.body.textContent).toContain('bug')
    expect(document.body.textContent).toContain('urgent')
    const chips = document.body.querySelectorAll('[data-test="task-tag-chip"]')
    expect(chips.length).toBe(2)
    const removes = document.body.querySelectorAll('[data-test="task-tag-remove"]')
    expect(removes.length).toBe(2)
    w.unmount()
  })

  it('adding a tag calls api.setTaskTags with the expanded array', async () => {
    const w = mount(TaskDrawer, { props: { item: base as never }, attachTo: document.body })
    const input = document.body.querySelector('[data-test="task-tag-add"]') as HTMLInputElement
    expect(input).not.toBeNull()
    input.value = 'frontend'
    input.dispatchEvent(new Event('input'))
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await flushPromises()

    expect(api.setTaskTags).toHaveBeenCalledWith('task-1', ['bug', 'urgent', 'frontend'])
    w.unmount()
  })

  it('removing a tag calls api.setTaskTags without that tag', async () => {
    const w = mount(TaskDrawer, { props: { item: base as never }, attachTo: document.body })
    const removeBtns = document.body.querySelectorAll('[data-test="task-tag-remove"]')
    expect(removeBtns.length).toBe(2)
    ;(removeBtns[0] as HTMLButtonElement).click()
    await flushPromises()

    expect(api.setTaskTags).toHaveBeenCalledWith('task-1', ['urgent'])
    w.unmount()
  })
})
