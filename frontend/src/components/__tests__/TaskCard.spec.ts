import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import TaskCard from '@/components/TaskCard.vue'
import { useBoardStore } from '@/stores/board'
import type { Item, ItemStatus } from '@/types/api'

const base = {
  id: 'scan-a', title: 'Task A', status: 'pending', attempts: 0, proposal: '', why: '',
  acceptance: '', touches: [], branch: null, lastIter: null, previousBranches: [], commit: null,
  planFile: '', planSection: '', wave: '', severity: null, category: null, sourceScan: null,
  selfReportedFailure: false, requeuedAt: null, review: null, mergeCommit: null, mergedAt: null,
  dependsOn: ['scan-x', 'scan-y'], blocks: ['scan-z'], orderIndex: 2, epicId: null, parent: null,
  conflictGroup: 'cg-x', resultSummary: '', diffRef: null,
}

function makeItem(id: string, status: ItemStatus, dependsOn: string[] = []): Item {
  return {
    id, title: id, status, attempts: 0, proposal: '', why: '', acceptance: '',
    touches: [], branch: null, lastIter: null, previousBranches: [], commit: null,
    planFile: '', planSection: '', wave: '', severity: null, category: null, sourceScan: null,
    selfReportedFailure: false, requeuedAt: null, review: null, mergeCommit: null, mergedAt: null,
    dependsOn, blocks: [], orderIndex: 0,
  }
}

describe('TaskCard', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('renders order badge, dependency chips, and no sisyphus hardcode', () => {
    const w = mount(TaskCard, { props: { item: base as never } })
    expect(w.text()).toContain('#3')
    expect(w.find('.dep-in').text()).toContain('2')   // dependsOn count
    expect(w.find('.dep-out').text()).toContain('1')  // blocks count
    expect(w.text()).not.toContain('sisyphus')
  })

  it('hides dependency chips when none', () => {
    const w = mount(TaskCard, { props: { item: { ...base, dependsOn: [], blocks: [] } as never } })
    expect(w.find('.dep-in').exists()).toBe(false)
    expect(w.find('.dep-out').exists()).toBe(false)
  })

  it('shows complexity badge when complexity is set', () => {
    const w = mount(TaskCard, { props: { item: { ...base, complexity: 'complex' } as never } })
    const badge = w.find('[data-test="complexity-badge"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toBe('complex')
    expect(badge.classes()).toContain('complexity-complex')
  })

  it('hides complexity badge when complexity is null', () => {
    const w = mount(TaskCard, { props: { item: { ...base, complexity: null } as never } })
    expect(w.find('[data-test="complexity-badge"]').exists()).toBe(false)
  })

  it('hides complexity badge when complexity is not set', () => {
    const w = mount(TaskCard, { props: { item: base as never } })
    expect(w.find('[data-test="complexity-badge"]').exists()).toBe(false)
  })

  it('a pending card shows «Запустить» and emits run (not click) on click', async () => {
    const w = mount(TaskCard, { props: { item: { ...base, status: 'pending' } as never } })
    const btn = w.find('[data-test="card-run"]')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    expect(w.emitted('run')).toBeTruthy()
    expect(w.emitted('run')![0]).toEqual(['scan-a'])
    // stopPropagation: the card click (open drawer) must NOT also fire.
    expect(w.emitted('click')).toBeFalsy()
  })

  it('a needs_revision card also shows «Запустить»', () => {
    const w = mount(TaskCard, { props: { item: { ...base, status: 'needs_revision' } as never } })
    expect(w.find('[data-test="card-run"]').exists()).toBe(true)
  })

  it('a queued card shows «Снять с очереди» and emits unqueue', async () => {
    const w = mount(TaskCard, { props: { item: { ...base, status: 'queued' } as never } })
    const btn = w.find('[data-test="card-unqueue"]')
    expect(btn.exists()).toBe(true)
    // queued card must not offer run.
    expect(w.find('[data-test="card-run"]').exists()).toBe(false)
    await btn.trigger('click')
    expect(w.emitted('unqueue')).toBeTruthy()
    expect(w.emitted('unqueue')![0]).toEqual(['scan-a'])
    expect(w.emitted('click')).toBeFalsy()
  })

  it('a queued card with an unfinished dep shows the «ждёт» badge', () => {
    const board = useBoardStore()
    const dep = makeItem('dep-1', 'pending')
    const card = makeItem('q1', 'queued', ['dep-1'])
    board.items = [card, dep]
    const w = mount(TaskCard, { props: { item: card } })
    const badge = w.find('[data-test="waiting-badge"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toContain('ждёт')
    expect(badge.text()).toContain('dep-1')
  })

  it('a queued card whose deps are all done does NOT show the «ждёт» badge', () => {
    const board = useBoardStore()
    const dep = makeItem('dep-1', 'done')
    const card = makeItem('q1', 'queued', ['dep-1'])
    board.items = [card, dep]
    const w = mount(TaskCard, { props: { item: card } })
    expect(w.find('[data-test="waiting-badge"]').exists()).toBe(false)
  })

  it('a non-queued card never shows the «ждёт» badge', () => {
    const board = useBoardStore()
    const dep = makeItem('dep-1', 'pending')
    const card = makeItem('p1', 'pending', ['dep-1'])
    board.items = [card, dep]
    const w = mount(TaskCard, { props: { item: card } })
    expect(w.find('[data-test="waiting-badge"]').exists()).toBe(false)
  })
})
