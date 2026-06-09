import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import { routes } from '@/router'
import TaskDrawer from '@/components/TaskDrawer.vue'
import type { Item } from '@/types/api'

vi.mock('@/api/client', () => ({
  api: {
    iterDetails: vi.fn().mockResolvedValue(null),
    iterDiff: vi.fn().mockResolvedValue(null),
    iterReviews: vi.fn().mockResolvedValue(null),
    iterEvents: vi.fn().mockResolvedValue([]),
    getTaskChecks: vi.fn().mockResolvedValue({ ok: true, verifyOutcome: null }),
  },
}))

vi.mock('@/stores/toast', () => ({ useToastStore: () => ({ add: vi.fn() }) }))

const base = {
  id: 'task-1', title: 'Test Task', status: 'pending', attempts: 0, proposal: 'p', why: 'w',
  acceptance: 'a', touches: [], branch: null, lastIter: null, previousBranches: [], commit: null,
  planFile: '', planSection: '', wave: '', severity: null, category: null, sourceScan: null,
  selfReportedFailure: false, requeuedAt: null, review: null, mergeCommit: null, mergedAt: null,
  dependsOn: [], blocks: [], orderIndex: 0,
} as unknown as Item

function makeRouter() {
  return createRouter({ history: createWebHistory(), routes })
}

async function mountDrawer(item: Item | null) {
  const router = makeRouter()
  setActivePinia(createPinia())
  router.push('/board/task/task-1')
  await router.isReady()
  const w = mount(TaskDrawer, {
    props: { item },
    global: { plugins: [router] },
    attachTo: document.body,
  })
  await flushPromises()
  return { w, router }
}

describe('TaskDrawer Переписки entry', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('renders the Переписки button when an item is present', async () => {
    const { w } = await mountDrawer(base)
    const btn = document.body.querySelector('[data-test="drawer-conversation"]')
    expect(btn).not.toBeNull()
    expect(btn!.textContent).toContain('Переписки')
    w.unmount()
  })

  it('does not render the button without an item', async () => {
    const { w } = await mountDrawer(null)
    expect(document.body.querySelector('[data-test="drawer-conversation"]')).toBeNull()
    w.unmount()
  })

  it('clicking it navigates to the conversation route for this task', async () => {
    const { w, router } = await mountDrawer(base)
    const spy = vi.spyOn(router, 'push')
    const btn = document.body.querySelector('[data-test="drawer-conversation"]') as HTMLButtonElement
    btn.click()
    await flushPromises()
    expect(spy).toHaveBeenCalledWith({ name: 'board-task-conversation', params: { id: 'task-1' } })
    w.unmount()
  })
})
