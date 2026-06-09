import { describe, it, expect } from 'vitest'
import type { Item, ItemStatus } from '@/types/api'
import {
  isDone,
  byId,
  depsSatisfied,
  unfinishedDeps,
  unfinishedAncestors,
  computeLayout,
} from '@/composables/deps'

function makeItem(id: string, status: ItemStatus, dependsOn: string[] = [], orderIndex = 0): Item {
  return {
    id, title: id, status, attempts: 0, proposal: '', why: '', acceptance: '',
    touches: [], branch: null, lastIter: null, previousBranches: [], commit: null,
    planFile: '', planSection: '', wave: '', severity: null, category: null,
    sourceScan: null, selfReportedFailure: false, requeuedAt: null, review: null,
    mergeCommit: null, mergedAt: null, dependsOn, blocks: [], orderIndex,
  }
}

describe('deps helpers', () => {
  it('isDone is true only for done/merged', () => {
    expect(isDone(makeItem('a', 'done'))).toBe(true)
    expect(isDone(makeItem('a', 'merged'))).toBe(true)
    expect(isDone(makeItem('a', 'queued'))).toBe(false)
    expect(isDone(makeItem('a', 'pending'))).toBe(false)
  })

  it('depsSatisfied: a MISSING dep counts as satisfied', () => {
    const it = makeItem('a', 'queued', ['ghost'])
    expect(depsSatisfied(it, byId([it]))).toBe(true)
  })

  it('depsSatisfied: unfinished present dep is not satisfied; done dep is', () => {
    const dep = makeItem('d', 'queued')
    const a = makeItem('a', 'queued', ['d'])
    expect(depsSatisfied(a, byId([a, dep]))).toBe(false)
    const doneDep = makeItem('d', 'done')
    expect(depsSatisfied(a, byId([a, doneDep]))).toBe(true)
  })

  it('tolerates an item with no dependsOn field at all (undefined, not [])', () => {
    const a = makeItem('a', 'queued')
    // Simulate a legacy item that never had the field set.
    delete (a as { dependsOn?: string[] }).dependsOn
    const map = byId([a])
    expect(depsSatisfied(a, map)).toBe(true)
    expect(unfinishedDeps(a, map)).toEqual([])
    expect(unfinishedAncestors('a', map)).toEqual([])
    expect(computeLayout([a]).nodes[0].level).toBe(0)
  })

  it('unfinishedDeps returns only present-and-unfinished direct deps', () => {
    const d1 = makeItem('d1', 'done')
    const d2 = makeItem('d2', 'in_progress')
    const a = makeItem('a', 'queued', ['d1', 'd2', 'ghost'])
    expect(unfinishedDeps(a, byId([a, d1, d2]))).toEqual(['d2'])
  })

  it('unfinishedAncestors is transitive and excludes done branches and self', () => {
    // a -> b -> c, with c done. b unfinished. Also d missing.
    const c = makeItem('c', 'done')
    const b = makeItem('b', 'queued', ['c'])
    const a = makeItem('a', 'pending', ['b', 'd'])
    const got = unfinishedAncestors('a', byId([a, b, c])).sort()
    expect(got).toEqual(['b'])
  })

  it('unfinishedAncestors: diamond is counted once', () => {
    // a -> b, a -> c, b -> d, c -> d  (all unfinished)
    const d = makeItem('d', 'pending')
    const b = makeItem('b', 'pending', ['d'])
    const c = makeItem('c', 'pending', ['d'])
    const a = makeItem('a', 'pending', ['b', 'c'])
    const got = unfinishedAncestors('a', byId([a, b, c, d])).sort()
    expect(got).toEqual(['b', 'c', 'd'])
  })

  it('unfinishedAncestors terminates on a cycle', () => {
    // a -> b -> a (cycle)
    const a = makeItem('a', 'pending', ['b'])
    const b = makeItem('b', 'pending', ['a'])
    const got = unfinishedAncestors('a', byId([a, b])).sort()
    expect(got).toEqual(['b'])
  })

  it('computeLayout: a 3-chain has levels 0,1,2 and 2 edges', () => {
    // a -> b -> c  (c dependsOn b, b dependsOn a)
    const a = makeItem('a', 'pending')
    const b = makeItem('b', 'pending', ['a'])
    const c = makeItem('c', 'pending', ['b'])
    const layout = computeLayout([a, b, c])
    const lvl = (id: string) => layout.nodes.find(n => n.id === id)!.level
    expect(lvl('a')).toBe(0)
    expect(lvl('b')).toBe(1)
    expect(lvl('c')).toBe(2)
    expect(layout.nodes).toHaveLength(3)
    expect(layout.edges).toHaveLength(2)
    // edges run left→right (prereq lower x → dependent higher x)
    for (const e of layout.edges) expect(e.x2).toBeGreaterThan(e.x1)
  })

  it('computeLayout: edges to a missing dep are dropped', () => {
    const a = makeItem('a', 'pending', ['ghost'])
    const layout = computeLayout([a])
    expect(layout.edges).toHaveLength(0)
    expect(layout.nodes[0].level).toBe(0)
  })

  it('computeLayout: a cycle does not hang and produces finite levels', () => {
    const a = makeItem('a', 'pending', ['b'])
    const b = makeItem('b', 'pending', ['a'])
    const layout = computeLayout([a, b])
    expect(layout.nodes).toHaveLength(2)
    for (const n of layout.nodes) expect(Number.isFinite(n.level)).toBe(true)
  })
})
