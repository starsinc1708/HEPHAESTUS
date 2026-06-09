import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import TaskDrawer from '@/components/TaskDrawer.vue'
import { api, ApiError } from '@/api/client'
import { useBoardStore } from '@/stores/board'
import type { Item } from '@/types/api'

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return {
    ...actual,
    api: {
      getState: vi.fn().mockResolvedValue({ items: [], summary: {} }),
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
// TaskDrawer calls useRouter() at setup (for the «Переписки» entry); this router-less
// unit mount stubs it so vue-router doesn't warn about a missing injection.
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

const base = {
  id: 'scan-a', title: 'Task A', status: 'pending', attempts: 0, proposal: 'p', why: 'w',
  acceptance: 'a', touches: [], branch: null, lastIter: null, previousBranches: [], commit: null,
  planFile: '', planSection: '', wave: '', severity: null, category: null, sourceScan: null,
  selfReportedFailure: false, requeuedAt: null, review: null, mergeCommit: null, mergedAt: null,
  dependsOn: ['scan-x'], blocks: ['scan-z'], orderIndex: 0, epicId: null, parent: null,
  conflictGroup: null, resultSummary: '', diffRef: null,
}

function makeItem(id: string, title = id): Item {
  return {
    id, title, status: 'pending', attempts: 0, proposal: '', why: '', acceptance: '',
    touches: [], branch: null, lastIter: null, previousBranches: [], commit: null,
    planFile: '', planSection: '', wave: '', severity: null, category: null, sourceScan: null,
    selfReportedFailure: false, requeuedAt: null, review: null, mergeCommit: null, mergedAt: null,
    dependsOn: [], blocks: [], orderIndex: 0,
  }
}

describe('TaskDrawer dependencies editor', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('renders dependsOn chips and read-only blocks ids', async () => {
    const w = mount(TaskDrawer, { props: { item: base as never }, attachTo: document.body })
    expect(document.body.textContent).toContain('Зависимости')
    expect(document.body.textContent).toContain('scan-x') // dependsOn chip
    expect(document.body.textContent).toContain('scan-z') // read-only blocks id
    expect(document.body.querySelector('[data-test="dep-chip"]')).not.toBeNull()
    w.unmount()
  })

  it('adding a dep via the select calls api.patchDeps with the full new array', async () => {
    const board = useBoardStore()
    board.items = [base as Item, makeItem('scan-y', 'Y task')]

    const w = mount(TaskDrawer, { props: { item: base as never }, attachTo: document.body })
    const select = document.body.querySelector('[data-test="dep-add-select"]') as HTMLSelectElement
    expect(select).not.toBeNull()
    select.value = 'scan-y'
    select.dispatchEvent(new Event('change'))
    await flushPromises()

    expect(api.patchDeps).toHaveBeenCalledWith('scan-a', ['scan-x', 'scan-y'])
    w.unmount()
  })

  it('removing a dep calls api.patchDeps without that id', async () => {
    const board = useBoardStore()
    board.items = [base as Item]

    const w = mount(TaskDrawer, { props: { item: base as never }, attachTo: document.body })
    const removeBtn = document.body.querySelector('[data-test="dep-remove"]') as HTMLButtonElement
    expect(removeBtn).not.toBeNull()
    removeBtn.click()
    await flushPromises()

    expect(api.patchDeps).toHaveBeenCalledWith('scan-a', [])
    w.unmount()
  })

  it('a 400 (cycle) shows the inline error and does not close the drawer', async () => {
    const board = useBoardStore()
    board.items = [base as Item, makeItem('scan-y')]
    ;(api.patchDeps as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new ApiError(400, 'Bad Request', JSON.stringify({ error: 'cycle detected', offending: 'scan-y' })),
    )

    const w = mount(TaskDrawer, { props: { item: base as never }, attachTo: document.body })
    const select = document.body.querySelector('[data-test="dep-add-select"]') as HTMLSelectElement
    select.value = 'scan-y'
    select.dispatchEvent(new Event('change'))
    await flushPromises()

    const err = document.body.querySelector('[data-test="dep-error"]')
    expect(err).not.toBeNull()
    expect(err!.textContent).toContain('cycle detected')
    // Drawer stays open.
    expect(document.body.querySelector('[data-test="dep-add-select"]')).not.toBeNull()
    w.unmount()
  })
})
