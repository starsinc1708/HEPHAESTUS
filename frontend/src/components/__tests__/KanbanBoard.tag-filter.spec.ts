import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import KanbanBoard from '@/components/KanbanBoard.vue'
import KanbanColumn from '@/components/KanbanColumn.vue'
import type { Item, ItemStatus } from '@/types/api'

vi.mock('sortablejs', () => ({
  default: { create: vi.fn(() => ({ toArray: () => [], destroy: vi.fn() })) },
}))

function makeItem(id: string, status: ItemStatus, tags?: string[]): Item {
  return {
    id, title: id, status, attempts: 0, proposal: '', why: '', acceptance: '',
    touches: [], branch: null, lastIter: null, previousBranches: [], commit: null,
    planFile: '', planSection: '', wave: '', severity: null, category: null,
    sourceScan: null, selfReportedFailure: false, requeuedAt: null, review: null,
    mergeCommit: null, mergedAt: null, tags,
  } as Item
}

describe('KanbanBoard tag filter', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('renders a button per unique tag across items', () => {
    const items = [
      makeItem('p1', 'pending', ['frontend']),
      makeItem('p2', 'pending', ['backend']),
      makeItem('p3', 'pending', ['frontend', 'urgent']),
    ]
    const w = mount(KanbanBoard, { props: { items } })
    const buttons = w.findAll('[data-test="tag-filter-btn"]')
    expect(buttons.length).toBe(3)
    expect(buttons.map(b => b.text()).sort()).toEqual(['backend', 'frontend', 'urgent'])
  })

  it('selecting a tag shows only items containing that tag', async () => {
    const items = [
      makeItem('p1', 'pending', ['frontend']),
      makeItem('p2', 'pending', ['backend']),
      makeItem('p3', 'pending', ['frontend', 'urgent']),
    ]
    const w = mount(KanbanBoard, { props: { items } })
    const frontendBtn = w.findAll('[data-test="tag-filter-btn"]').find(b => b.text() === 'frontend')!
    await frontendBtn.trigger('click')

    const pendingCol = w.findAllComponents(KanbanColumn).find(c => c.props('status') === 'pending')!
    const pendingItems = pendingCol.props('items') as Item[]
    expect(pendingItems.map(i => i.id).sort()).toEqual(['p1', 'p3'])
  })

  it('deselecting a tag restores the full item list', async () => {
    const items = [
      makeItem('p1', 'pending', ['frontend']),
      makeItem('p2', 'pending', ['backend']),
    ]
    const w = mount(KanbanBoard, { props: { items } })
    const frontendBtn = w.findAll('[data-test="tag-filter-btn"]').find(b => b.text() === 'frontend')!

    // Filter
    await frontendBtn.trigger('click')
    const pendingCol1 = w.findAllComponents(KanbanColumn).find(c => c.props('status') === 'pending')!
    expect((pendingCol1.props('items') as Item[]).length).toBe(1)

    // Deselect
    await frontendBtn.trigger('click')
    const pendingCol2 = w.findAllComponents(KanbanColumn).find(c => c.props('status') === 'pending')!
    expect((pendingCol2.props('items') as Item[]).length).toBe(2)
  })

  it('shows no tag filter bar when no items have tags', () => {
    const items = [
      makeItem('p1', 'pending'),
      makeItem('p2', 'pending'),
    ]
    const w = mount(KanbanBoard, { props: { items } })
    expect(w.find('[data-test="tag-filter-bar"]').exists()).toBe(false)
  })
})
