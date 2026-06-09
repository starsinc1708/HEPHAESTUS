import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { h } from 'vue'
import BoardView from '../BoardView.vue'
import { useBoardStore } from '@/stores/board'
import type { Item, ItemStatus } from '@/types/api'

// Stub the api client so the board store's startPolling/fetchState never hits the network.
vi.mock('@/api/client', () => ({
  api: {
    getState: vi.fn().mockResolvedValue({ items: [], summary: {} }),
    runTask: vi.fn().mockResolvedValue({ ok: true, status: 'queued' }),
    unqueueTask: vi.fn().mockResolvedValue({ ok: true, status: 'pending' }),
  },
}))

vi.mock('@/stores/toast', () => ({ useToastStore: () => ({ add: vi.fn() }) }))

// BoardView calls useRoute() to open a drawer from the :id param; no router in test.
vi.mock('vue-router', () => ({ useRoute: () => ({ params: {} }) }))

// Capture the :items / :selected-id props passed into KanbanBoard.
let capturedItems: Item[] = []
let capturedSelectedId: string | null = null
const KanbanBoardStub = {
  name: 'KanbanBoard',
  props: ['items', 'selectedId'],
  // The board re-emits these to BoardView; tests fire them via findComponent().vm.$emit
  // (real SortableJS DnD does not run in jsdom — we test the handler logic, not the drag).
  emits: ['task-click', 'reorder', 'move-top', 'run', 'unqueue', 'move'],
  // Re-capture on every render so we see the latest items the board renders with.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  setup(props: any) {
    return () => {
      capturedItems = props.items
      capturedSelectedId = props.selectedId ?? null
      // Marker so tests can assert the kanban view is mounted (vs. the graph).
      return h('div', { 'data-test': 'kanban' })
    }
  },
}

// Real DepGraph would need full items; a stub with the data-test marker is enough to
// assert the kanban↔graph swap.
const DepGraphStub = {
  name: 'DepGraph',
  props: ['items'],
  template: '<div data-test="dep-graph" />',
}

const STUBS = {
  AppShell: { template: '<div><slot name="title" /><slot /></div>' },
  GoalModal: { template: '<div />' },
  TaskDrawer: { template: '<div />' },
  KanbanBoard: KanbanBoardStub,
  DepGraph: DepGraphStub,
}

function makeItem(id: string, status: ItemStatus): Item {
  return {
    id, title: id, status, attempts: 0, proposal: '', why: '', acceptance: '',
    touches: [], branch: null, lastIter: null, previousBranches: [], commit: null,
    planFile: '', planSection: '', wave: '', severity: null, category: null,
    sourceScan: null, selfReportedFailure: false, requeuedAt: null, review: null,
    mergeCommit: null, mergedAt: null,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  capturedItems = []
  capturedSelectedId = null
})

function press(key: string) {
  window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }))
}

describe('BoardView history filter', () => {
  it('shows done/merged items by default and hides them when toggled on', async () => {
    const w = mount(BoardView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()

    // Seed the store with a done item, a merged item, and a pending item.
    const board = useBoardStore()
    board.items = [
      makeItem('task-pending', 'pending'),
      makeItem('task-done', 'done'),
      makeItem('task-merged', 'merged'),
    ]
    board.loaded = true
    await flushPromises()

    // Default: finished work (done/merged) is visible — it must not vanish.
    let ids = capturedItems.map(i => i.id)
    expect(ids).toContain('task-pending')
    expect(ids).toContain('task-done')
    expect(ids).toContain('task-merged')

    // Toggle "hide finished" ON.
    await w.find('[data-test="board-history-filter"]').trigger('click')
    await flushPromises()

    ids = capturedItems.map(i => i.id)
    expect(ids).toContain('task-pending')
    expect(ids).not.toContain('task-done')
    expect(ids).not.toContain('task-merged')

    w.unmount()
  })

  it('keeps done items visible via the «Готово» stat filter even when "hide finished" is on', async () => {
    const w = mount(BoardView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()

    const board = useBoardStore()
    board.items = [makeItem('task-pending', 'pending'), makeItem('task-done', 'done')]
    board.loaded = true
    await flushPromises()

    // Turn "hide finished" ON → the done item drops off the board.
    await w.find('[data-test="board-history-filter"]').trigger('click')
    await flushPromises()
    expect(capturedItems.map(i => i.id)).not.toContain('task-done')

    // Explicitly filtering by the «Готово» stat must show done items, not blank the board.
    const statBtn = w.findAll('button.stat').find(b => b.text().includes('Готово:'))
    expect(statBtn).toBeTruthy()
    await statBtn!.trigger('click')
    await flushPromises()

    expect(capturedItems.map(i => i.id)).toContain('task-done')

    w.unmount()
  })
})

describe('BoardView send-to-run wiring', () => {
  it('maps a pending→queued move to boardStore.runTask', async () => {
    const w = mount(BoardView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    const board = useBoardStore()
    const runSpy = vi.spyOn(board, 'runTask')
    board.items = [makeItem('t1', 'pending')]
    board.loaded = true
    await flushPromises()

    w.findComponent(KanbanBoardStub).vm.$emit('move', { id: 't1', from: 'pending', to: 'queued' })
    await flushPromises()

    expect(runSpy).toHaveBeenCalledWith('t1')
    w.unmount()
  })

  it('maps a queued→pending move to boardStore.unqueueTask', async () => {
    const w = mount(BoardView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    const board = useBoardStore()
    const unqueueSpy = vi.spyOn(board, 'unqueueTask')
    board.items = [makeItem('t1', 'queued')]
    board.loaded = true
    await flushPromises()

    w.findComponent(KanbanBoardStub).vm.$emit('move', { id: 't1', from: 'queued', to: 'pending' })
    await flushPromises()

    expect(unqueueSpy).toHaveBeenCalledWith('t1')
    w.unmount()
  })

  it('ignores unrelated move combinations', async () => {
    const w = mount(BoardView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    const board = useBoardStore()
    const runSpy = vi.spyOn(board, 'runTask')
    const unqueueSpy = vi.spyOn(board, 'unqueueTask')
    board.items = [makeItem('t1', 'pending')]
    board.loaded = true
    await flushPromises()

    w.findComponent(KanbanBoardStub).vm.$emit('move', { id: 't1', from: 'pending', to: 'in_progress' })
    await flushPromises()

    expect(runSpy).not.toHaveBeenCalled()
    expect(unqueueSpy).not.toHaveBeenCalled()
    w.unmount()
  })

  it('bubbles card run/unqueue events to the store', async () => {
    const w = mount(BoardView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    const board = useBoardStore()
    const runSpy = vi.spyOn(board, 'runTask')
    const unqueueSpy = vi.spyOn(board, 'unqueueTask')
    board.items = [makeItem('t1', 'pending')]
    board.loaded = true
    await flushPromises()

    const kb = w.findComponent(KanbanBoardStub)
    kb.vm.$emit('run', 't1')
    kb.vm.$emit('unqueue', 't1')
    await flushPromises()

    expect(runSpy).toHaveBeenCalledWith('t1')
    expect(unqueueSpy).toHaveBeenCalledWith('t1')
    w.unmount()
  })
})

describe('BoardView view-mode toggle', () => {
  it('toggles between kanban columns and the dependency graph', async () => {
    const w = mount(BoardView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    const board = useBoardStore()
    board.items = [makeItem('t1', 'pending')]
    board.loaded = true
    await flushPromises()

    // Default: kanban shown, graph absent.
    expect(w.find('[data-test="kanban"]').exists()).toBe(true)
    expect(w.find('[data-test="dep-graph"]').exists()).toBe(false)

    // Click «Граф».
    const graphBtn = w.find('[data-test="board-view-mode"]').findAll('button')
      .find(b => b.text() === 'Граф')!
    await graphBtn.trigger('click')
    await flushPromises()

    expect(w.find('[data-test="dep-graph"]').exists()).toBe(true)
    expect(w.find('[data-test="kanban"]').exists()).toBe(false)

    // Back to «Колонки».
    const colBtn = w.find('[data-test="board-view-mode"]').findAll('button')
      .find(b => b.text() === 'Колонки')!
    await colBtn.trigger('click')
    await flushPromises()

    expect(w.find('[data-test="kanban"]').exists()).toBe(true)
    expect(w.find('[data-test="dep-graph"]').exists()).toBe(false)

    w.unmount()
  })
})

describe('BoardView keyboard shortcuts (UI-006)', () => {
  async function mountWith(items: Item[]) {
    const w = mount(BoardView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    const board = useBoardStore()
    board.items = items
    board.loaded = true
    await flushPromises()
    return { w, board }
  }

  it('j/k navigate selection in column order and r runs the selected pending task', async () => {
    // Seeded out of column order: a done item first, then two pending. Nav order is
    // column-based (pending before done), so the first `j` must land on p1, not d1.
    const { w, board } = await mountWith([
      makeItem('d1', 'done'),
      makeItem('p1', 'pending'),
      makeItem('p2', 'pending'),
    ])
    const runSpy = vi.spyOn(board, 'runTask')

    press('j')
    await flushPromises()
    expect(capturedSelectedId).toBe('p1')

    press('j')
    await flushPromises()
    expect(capturedSelectedId).toBe('p2')

    press('k')
    await flushPromises()
    expect(capturedSelectedId).toBe('p1')

    // r runs the selected pending task.
    press('r')
    await flushPromises()
    expect(runSpy).toHaveBeenCalledWith('p1')

    w.unmount()
  })

  it('does NOT run a selected non-runnable (done) task on r', async () => {
    const { w, board } = await mountWith([makeItem('d1', 'done')])
    const runSpy = vi.spyOn(board, 'runTask')

    press('j') // only nav item is the done one
    await flushPromises()
    expect(capturedSelectedId).toBe('d1')

    press('r')
    await flushPromises()
    expect(runSpy).not.toHaveBeenCalled()

    w.unmount()
  })

  it('? toggles the shortcuts help overlay and Escape closes it', async () => {
    const { w } = await mountWith([makeItem('p1', 'pending')])
    expect(w.find('[data-test="shortcuts-help"]').exists()).toBe(false)

    press('?')
    await flushPromises()
    expect(w.find('[data-test="shortcuts-help"]').exists()).toBe(true)

    press('Escape')
    await flushPromises()
    expect(w.find('[data-test="shortcuts-help"]').exists()).toBe(false)

    w.unmount()
  })

  it('/ focuses the search input', async () => {
    const { w } = await mountWith([makeItem('p1', 'pending')])
    press('/')
    await flushPromises()
    expect(document.activeElement).toBe(w.find('.search-input').element)
    w.unmount()
  })

  it('Escape clears the selection when no overlay/drawer is open', async () => {
    const { w } = await mountWith([makeItem('p1', 'pending')])
    press('j')
    await flushPromises()
    expect(capturedSelectedId).toBe('p1')

    press('Escape')
    await flushPromises()
    expect(capturedSelectedId).toBe(null)
    w.unmount()
  })
})
