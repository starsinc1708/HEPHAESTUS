import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import DepGraph from '@/components/DepGraph.vue'
import type { Item, ItemStatus } from '@/types/api'

function makeItem(id: string, status: ItemStatus, dependsOn: string[] = []): Item {
  return {
    id, title: 'Title ' + id, status, attempts: 0, proposal: '', why: '', acceptance: '',
    touches: [], branch: null, lastIter: null, previousBranches: [], commit: null,
    planFile: '', planSection: '', wave: '', severity: null, category: null, sourceScan: null,
    selfReportedFailure: false, requeuedAt: null, review: null, mergeCommit: null, mergedAt: null,
    dependsOn, blocks: [], orderIndex: 0,
  }
}

describe('DepGraph', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('renders one dep-node per item and the right number of dep-edges', () => {
    // a -> b -> c, plus a -> c => 3 edges total
    const items = [
      makeItem('a', 'pending'),
      makeItem('b', 'queued', ['a']),
      makeItem('c', 'pending', ['b', 'a']),
    ]
    const w = mount(DepGraph, { props: { items } })
    expect(w.find('[data-test="dep-graph"]').exists()).toBe(true)
    expect(w.findAll('[data-test="dep-node"]')).toHaveLength(3)
    expect(w.findAll('[data-test="dep-edge"]')).toHaveLength(3)
  })

  it('emits task-click with the id when a node is clicked', async () => {
    const items = [makeItem('a', 'pending'), makeItem('b', 'queued', ['a'])]
    const w = mount(DepGraph, { props: { items } })
    const nodes = w.findAll('[data-test="dep-node"]')
    await nodes[0].trigger('click')
    expect(w.emitted('task-click')).toBeTruthy()
    // first node by layout order is level-0 'a'
    expect(w.emitted('task-click')![0]).toEqual(['a'])
  })

  it('drops edges whose dependency is not in the rendered set', () => {
    const items = [makeItem('a', 'pending', ['ghost'])]
    const w = mount(DepGraph, { props: { items } })
    expect(w.findAll('[data-test="dep-node"]')).toHaveLength(1)
    expect(w.findAll('[data-test="dep-edge"]')).toHaveLength(0)
  })
})
