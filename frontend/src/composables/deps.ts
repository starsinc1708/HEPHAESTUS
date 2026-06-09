/**
 * Pure dependency-graph helpers over board items (#4).
 *
 * Plain exported functions — NO reactivity — fully unit-testable. Mirrors the backend
 * `app/core/deps.py`: total functions that never throw on missing keys and tolerate
 * dangling/cyclic data (every walk is guarded by a visited set).
 *
 * `byId(items)` builds the `{ id: item }` map every other helper consumes.
 */
import type { Item } from '@/types/api'

const DONE_STATUSES: ReadonlySet<string> = new Set(['done', 'merged'])

/** True when the item is in a terminal-success status (done/merged). */
export function isDone(it: Item): boolean {
  return DONE_STATUSES.has(it.status)
}

/** Build the `{ id: item }` lookup map over the full item list. */
export function byId(items: Item[]): Record<string, Item> {
  const map: Record<string, Item> = {}
  for (const it of items) map[it.id] = it
  return map
}

/**
 * True when every dependency of `it` is satisfied. A dep id MISSING from the map
 * (a deleted prerequisite) counts as satisfied so a removed task never deadlocks its
 * dependents. Empty/absent `dependsOn` → true.
 */
export function depsSatisfied(it: Item, map: Record<string, Item>): boolean {
  for (const depId of it.dependsOn ?? []) {
    const dep = map[depId]
    if (dep !== undefined && !isDone(dep)) return false
  }
  return true
}

/** DIRECT deps that are present in the map AND not done (the unfinished blockers). */
export function unfinishedDeps(it: Item, map: Record<string, Item>): string[] {
  const out: string[] = []
  for (const depId of it.dependsOn ?? []) {
    const dep = map[depId]
    if (dep !== undefined && !isDone(dep)) out.push(depId)
  }
  return out
}

/**
 * Transitive set of `dependsOn` ancestor ids of `id` that are NOT done.
 * Done ancestors are pruned (not collected, not recursed through). Missing ids are
 * skipped. Cyclic data terminates via a visited set. `id` itself is never included.
 */
export function unfinishedAncestors(id: string, map: Record<string, Item>): string[] {
  const result = new Set<string>()
  const visited = new Set<string>([id])
  const start = map[id]
  const stack: string[] = start ? [...(start.dependsOn ?? [])] : []
  while (stack.length) {
    const depId = stack.pop() as string
    if (visited.has(depId)) continue
    visited.add(depId)
    const dep = map[depId]
    if (dep === undefined) continue // missing prereq — do not recurse, do not collect
    if (isDone(dep)) continue // done ancestor — prune it and its parents
    result.add(depId)
    stack.push(...(dep.dependsOn ?? []))
  }
  return [...result]
}

// ── Layered DAG layout ──

export interface DepNode {
  id: string
  item: Item
  level: number
  x: number
  y: number
}

export interface DepEdge {
  from: string
  to: string
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface DepLayout {
  nodes: DepNode[]
  edges: DepEdge[]
  width: number
  height: number
}

export interface LayoutOpts {
  colWidth?: number
  rowHeight?: number
  nodeW?: number
  nodeH?: number
}

const PAD = 24

/**
 * Longest-path layered layout of the dependency DAG.
 *
 * level(id) = 1 + max(level of each present dep), 0 if no present deps. Computed via a
 * memoized DFS over `dependsOn`; only edges whose dep exists in the rendered set count.
 * A back-edge inside an active path (a cycle) contributes 0 so the walk terminates and
 * never hangs. Nodes are grouped by level (x = level*colWidth), ordered within a level by
 * `orderIndex` then id for determinism (y = indexInLevel*rowHeight). Edge endpoints use
 * node centers: x1 = source right-center, x2 = target left-center.
 */
export function computeLayout(items: Item[], opts: LayoutOpts = {}): DepLayout {
  const colWidth = opts.colWidth ?? 180
  const rowHeight = opts.rowHeight ?? 72
  const nodeW = opts.nodeW ?? 140
  const nodeH = opts.nodeH ?? 48

  const map = byId(items)
  const present = new Set(items.map(it => it.id))

  // Memoized longest-path level with cycle guard (active path = the DFS stack).
  const levelCache = new Map<string, number>()
  const active = new Set<string>()

  function level(id: string): number {
    const cached = levelCache.get(id)
    if (cached !== undefined) return cached
    if (active.has(id)) return 0 // back-edge in an active path → contributes 0
    active.add(id)
    const it = map[id]
    let max = -1
    for (const depId of it?.dependsOn ?? []) {
      if (!present.has(depId)) continue
      const dl = level(depId)
      if (dl > max) max = dl
    }
    active.delete(id)
    const lvl = max + 1
    levelCache.set(id, lvl)
    return lvl
  }

  // Group node ids by level.
  const byLevel = new Map<number, Item[]>()
  let maxLevel = 0
  for (const it of items) {
    const lvl = level(it.id)
    if (lvl > maxLevel) maxLevel = lvl
    const bucket = byLevel.get(lvl)
    if (bucket) bucket.push(it)
    else byLevel.set(lvl, [it])
  }

  // Deterministic order within each level: orderIndex then id.
  const nodes: DepNode[] = []
  const center = new Map<string, { cx: number; cy: number }>()
  let maxRows = 0
  for (let lvl = 0; lvl <= maxLevel; lvl++) {
    const bucket = byLevel.get(lvl)
    if (!bucket) continue
    bucket.sort((a, b) => {
      const oa = a.orderIndex ?? 0
      const ob = b.orderIndex ?? 0
      if (oa !== ob) return oa - ob
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0
    })
    bucket.forEach((it, i) => {
      const x = PAD + lvl * colWidth
      const y = PAD + i * rowHeight
      nodes.push({ id: it.id, item: it, level: lvl, x, y })
      center.set(it.id, { cx: x + nodeW / 2, cy: y + nodeH / 2 })
    })
    if (bucket.length > maxRows) maxRows = bucket.length
  }

  // Edges: prerequisite (lower level, left) → dependent (higher level, right).
  const edges: DepEdge[] = []
  for (const it of items) {
    for (const depId of it.dependsOn ?? []) {
      if (!present.has(depId)) continue
      const src = center.get(depId) // prerequisite
      const dst = center.get(it.id) // dependent
      if (!src || !dst) continue
      edges.push({
        from: depId,
        to: it.id,
        x1: src.cx + nodeW / 2, // source right-center
        y1: src.cy,
        x2: dst.cx - nodeW / 2, // target left-center
        y2: dst.cy,
      })
    }
  }

  const width = PAD * 2 + (maxLevel + 1) * colWidth - (colWidth - nodeW)
  const height = PAD * 2 + Math.max(maxRows, 1) * rowHeight - (rowHeight - nodeH)

  return { nodes, edges, width, height }
}
