import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import KanbanBoard from '@/components/KanbanBoard.vue'
import KanbanColumn from '@/components/KanbanColumn.vue'
import type { Item, ItemStatus } from '@/types/api'

// SortableJS touches real DOM/drag internals — stub it so the columns mount cleanly in jsdom.
vi.mock('sortablejs', () => ({
  default: { create: vi.fn(() => ({ toArray: () => [], destroy: vi.fn() })) },
}))

function makeItem(id: string, status: ItemStatus): Item {
  return {
    id, title: id, status, attempts: 0, proposal: '', why: '', acceptance: '',
    touches: [], branch: null, lastIter: null, previousBranches: [], commit: null,
    planFile: '', planSection: '', wave: '', severity: null, category: null,
    sourceScan: null, selfReportedFailure: false, requeuedAt: null, review: null,
    mergeCommit: null, mergedAt: null,
  }
}

describe('KanbanBoard «К запуску» column', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('renders a «К запуску» column between «Ожидает» and «В работе»', () => {
    const w = mount(KanbanBoard, { props: { items: [] } })
    const labels = w.findAllComponents(KanbanColumn).map(c => c.props('status'))
    const pendingIdx = labels.indexOf('pending')
    const queuedIdx = labels.indexOf('queued')
    const inProgressIdx = labels.indexOf('in_progress')
    expect(queuedIdx).toBeGreaterThan(-1)
    expect(queuedIdx).toBe(pendingIdx + 1)
    expect(inProgressIdx).toBe(queuedIdx + 1)
    // The column carries the Russian label.
    const queuedCol = w.findAllComponents(KanbanColumn).find(c => c.props('status') === 'queued')!
    expect(queuedCol.props('label')).toBe('К запуску')
    // pending + queued form a shared drag group.
    expect(queuedCol.props('group')).toBe('runnable')
    const pendingCol = w.findAllComponents(KanbanColumn).find(c => c.props('status') === 'pending')!
    expect(pendingCol.props('group')).toBe('runnable')
  })

  it('routes queued items into the queued column', () => {
    const items = [
      makeItem('p1', 'pending'),
      makeItem('q1', 'queued'),
      makeItem('q2', 'queued'),
    ]
    const w = mount(KanbanBoard, { props: { items } })
    const queuedCol = w.findAllComponents(KanbanColumn).find(c => c.props('status') === 'queued')!
    const queuedItems = queuedCol.props('items') as Item[]
    expect(queuedItems.map(i => i.id)).toEqual(['q1', 'q2'])
  })
})

describe('KanbanBoard «Готово» column (done + merged)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('aggregates done and merged into one «Готово» column and drops the separate «Слито»', () => {
    const items = [
      makeItem('d1', 'done'),
      makeItem('m1', 'merged'),
      makeItem('p1', 'pending'),
    ]
    const w = mount(KanbanBoard, { props: { items } })
    const cols = w.findAllComponents(KanbanColumn)
    // No separate merged/«Слито» column anymore.
    expect(cols.map(c => c.props('status'))).not.toContain('merged')
    const doneCol = cols.find(c => c.props('status') === 'done')!
    expect(doneCol.props('label')).toBe('Готово')
    const doneItems = doneCol.props('items') as Item[]
    expect(doneItems.map(i => i.id).sort()).toEqual(['d1', 'm1'])
  })
})
