import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import TaskDrawer from '@/components/TaskDrawer.vue'
import { api } from '@/api/client'
import { useTaskStore } from '@/stores/task'

vi.mock('@/api/client', () => ({
  api: {
    patchItem: vi.fn().mockResolvedValue({ ok: true }),
    iterDetails: vi.fn().mockResolvedValue(null),
    iterDiff: vi.fn().mockResolvedValue(null),
    iterReviews: vi.fn().mockResolvedValue(null),
    iterEvents: vi.fn().mockResolvedValue([]),
    agentActivity: vi.fn().mockResolvedValue({ agents: [], edges: [], timeline: [] }),
    getTaskChecks: vi.fn().mockResolvedValue({ ok: true, verifyOutcome: null }),
  },
}))

// TaskDrawer calls useRouter() at setup (for the «Переписки» entry); this router-less
// unit mount stubs it so vue-router doesn't warn about a missing injection.
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

const base = {
  id: 'task-1', title: 'Test Task', status: 'pending', attempts: 0, proposal: 'p', why: 'w',
  acceptance: 'a', touches: [], branch: null, lastIter: 'iter-0001', previousBranches: [], commit: null,
  planFile: '', planSection: '', wave: '', severity: null, category: null, sourceScan: null,
  selfReportedFailure: false, requeuedAt: null, review: null, mergeCommit: null, mergedAt: null,
  dependsOn: [], blocks: [], orderIndex: 0, epicId: null, parent: null,
  conflictGroup: null, resultSummary: '', diffRef: null,
  modelOverride: null, complexity: null,
}

describe('TaskDrawer checks tab', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('renders checks outcome when verifyOutcome exists', async () => {
    const mockOutcome = {
      passed: true,
      checks_ran: 5,
      unverified: false,
      detail: 'all checks passed successfully',
    }
    ;(api.getTaskChecks as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      verifyOutcome: mockOutcome,
    })

    const taskStore = useTaskStore()
    taskStore.activeTab = 5

    const w = mount(TaskDrawer, { props: { item: base as never }, attachTo: document.body })
    await flushPromises()

    const checksPanel = document.body.querySelector('[data-test="checks-panel"]')
    expect(checksPanel).not.toBeNull()
    expect(document.body.textContent).toContain('Пройдено')
    expect(document.body.textContent).toContain('Результаты проверок')
    expect(document.body.textContent).toContain('Запущено проверок:')
    expect(document.body.textContent).toContain('5')
    expect(document.body.textContent).toContain('all checks passed successfully')
    
    w.unmount()
  })

  it('renders empty message when verifyOutcome is null', async () => {
    ;(api.getTaskChecks as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      verifyOutcome: null,
    })

    const taskStore = useTaskStore()
    taskStore.activeTab = 5

    const w = mount(TaskDrawer, { props: { item: base as never }, attachTo: document.body })
    await flushPromises()

    expect(document.body.textContent).toContain('Нет данных о проверках для этой задачи')

    w.unmount()
  })

  it('shows a distinct error state when the checks request fails', async () => {
    ;(api.getTaskChecks as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('boom'))

    const taskStore = useTaskStore()
    taskStore.activeTab = 5

    const w = mount(TaskDrawer, { props: { item: base as never }, attachTo: document.body })
    await flushPromises()

    expect(document.body.querySelector('[data-test="checks-error"]')).not.toBeNull()
    expect(document.body.textContent).toContain('Не удалось загрузить проверки')
    expect(document.body.textContent).not.toContain('Нет данных о проверках')

    w.unmount()
  })

  it('surfaces scope-guard out-of-scope files', async () => {
    ;(api.getTaskChecks as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      verifyOutcome: { passed: true, checks_ran: 2, unverified: false, detail: '' },
      scopeExtra: ['rogue.txt', 'extra/thing.js'],
    })

    const taskStore = useTaskStore()
    taskStore.activeTab = 5

    const w = mount(TaskDrawer, { props: { item: base as never }, attachTo: document.body })
    await flushPromises()

    expect(document.body.querySelector('[data-test="scope-warning"]')).not.toBeNull()
    expect(document.body.textContent).toContain('rogue.txt')
    expect(document.body.textContent).toContain('extra/thing.js')

    w.unmount()
  })
})
