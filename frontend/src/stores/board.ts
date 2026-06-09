import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Item, Summary, StateSnapshot, ItemStatus } from '@/types/api'
import { api, ApiError } from '@/api/client'
import { useToastStore } from './toast'
import { useWebSocket } from '@/composables/useWebSocket'
import { i18n } from '@/i18n'
const t = i18n.global.t

export const useBoardStore = defineStore('board', () => {
  const items = ref<Item[]>([])
  const summary = ref<Summary>({
    pending: 0, queued: 0, in_progress: 0, done: 0, merged: 0,
    needs_revision: 0, discarded: 0, failed_total: 0,
    failed_breakdown: {}, total: 0, percent_done: 0,
  })
  const filter = ref<string>('')
  const loading = ref(false)
  const loaded = ref(false)
  const lastError = ref<string | null>(null)
  const lastUpdated = ref<number>(0)
  const isConnected = ref(true)
  let _timer: ReturnType<typeof setInterval> | null = null
  let _consecutiveFailures = 0
  let _ws: ReturnType<typeof useWebSocket> | null = null

  const filteredItems = computed(() => {
    const q = filter.value.trim().toLowerCase()
    if (!q) return items.value
    return items.value.filter(it =>
      it.id.toLowerCase().includes(q) ||
      it.title.toLowerCase().includes(q) ||
      it.status.toLowerCase().includes(q) ||
      (it.severity ?? '').toLowerCase().includes(q)
    )
  })

  function itemsByStatus(status: ItemStatus | 'failed'): Item[] {
    if (status === 'failed') {
      return filteredItems.value.filter(it => it.status.startsWith('failed'))
    }
    return filteredItems.value.filter(it => it.status === status)
  }

  async function fetchState() {
    try {
      loading.value = true
      const state: StateSnapshot = await api.getState()

      // Cross-store invalidation: if taskStore has an open drawer for an item that changed status, clear its cache
      const prevItems = items.value
      if (prevItems.length > 0) {
        const changedIds = state.items.filter((newItem, i) => {
          const old = prevItems[i]
          return old && old.id === newItem.id && old.status !== newItem.status
        }).map(it => it.id)

        if (changedIds.length > 0) {
          // Lazy import to avoid circular dependency
          import('./task').then(({ useTaskStore }) => {
            const taskStore = useTaskStore()
            if (taskStore.activeDrawerTaskId && changedIds.includes(taskStore.activeDrawerTaskId)) {
              taskStore.clearCache()
            }
          })
        }
      }

      items.value = state.items
      summary.value = state.summary
      lastError.value = null
      lastUpdated.value = Date.now()
      loaded.value = true
      _consecutiveFailures = 0
      isConnected.value = true
    } catch (e: unknown) {
      lastError.value = e instanceof Error ? e.message : String(e)
      _consecutiveFailures++
      if (_consecutiveFailures >= 3) {
        isConnected.value = false
      }
    } finally {
      loading.value = false
    }
  }

  function _applyWsState(state: StateSnapshot) {
    // Cross-store invalidation (same as fetchState)
    const prevItems = items.value
    if (prevItems.length > 0) {
      const changedIds = state.items.filter((newItem, i) => {
        const old = prevItems[i]
        return old && old.id === newItem.id && old.status !== newItem.status
      }).map(it => it.id)
      if (changedIds.length > 0) {
        import('./task').then(({ useTaskStore }) => {
          const taskStore = useTaskStore()
          if (taskStore.activeDrawerTaskId && changedIds.includes(taskStore.activeDrawerTaskId)) {
            taskStore.clearCache()
          }
        })
      }
    }
    items.value = state.items
    summary.value = state.summary
    lastError.value = null
    lastUpdated.value = Date.now()
    loaded.value = true
    _consecutiveFailures = 0
    isConnected.value = true
  }

  function startPolling(interval = 3000) {
    stopPolling()
    // Subscribe to WebSocket push for real-time updates
    _ws = useWebSocket()
    _ws.connect('board', _applyWsState)
    void fetchState()
    // Fallback HTTP polling at a slower interval (WS is primary)
    _timer = setInterval(() => void fetchState(), Math.max(interval, 10000))
  }

  function stopPolling() {
    if (_timer !== null) {
      clearInterval(_timer)
      _timer = null
    }
    if (_ws) {
      _ws.disconnect()
      _ws = null
    }
  }

  async function requeueItem(id: string) {
    const toast = useToastStore()
    const snapshot = [...items.value]
    // Optimistic: set item status to pending
    const idx = items.value.findIndex(it => it.id === id)
    if (idx !== -1) {
      items.value[idx] = { ...items.value[idx], status: 'pending' }
    }
    try {
      await api.requeueItem(id)
      toast.add('success', t('drawer.requeued', { id }))
      await fetchState()
    } catch (e: unknown) {
      // Rollback
      items.value = snapshot
      toast.add('error', t('drawer.requeueError', { error: e instanceof Error ? e.message : String(e) }))
    }
  }

  async function deleteItem(id: string) {
    const toast = useToastStore()
    const snapshot = [...items.value]
    // Optimistic: remove item
    items.value = items.value.filter(it => it.id !== id)
    try {
      await api.deleteItem(id)
      toast.add('success', t('drawer.deleted', { id }))
      await fetchState()
    } catch (e: unknown) {
      // Rollback
      items.value = snapshot
      toast.add('error', t('drawer.deleteError', { error: e instanceof Error ? e.message : String(e) }))
    }
  }

  async function moveTop(id: string) {
    const toast = useToastStore()
    const snapshot = [...items.value]
    // Optimistic: move item to index 0
    const idx = items.value.findIndex(it => it.id === id)
    if (idx !== -1) {
      const [item] = items.value.splice(idx, 1)
      items.value.unshift(item)
    }
    try {
      await api.moveTop(id)
      toast.add('success', t('drawer.movedTop', { id }))
      await fetchState()
    } catch (e: unknown) {
      // Rollback
      items.value = snapshot
      toast.add('error', t('drawer.moveTopError', { error: e instanceof Error ? e.message : String(e) }))
    }
  }

  async function runTask(id: string) {
    const toast = useToastStore()
    const snapshot = [...items.value]
    // Optimistic: flip to queued (send-to-run).
    const idx = items.value.findIndex(it => it.id === id)
    if (idx !== -1) {
      items.value[idx] = { ...items.value[idx], status: 'queued' }
    }
    try {
      await api.runTask(id)
      toast.add('success', t('drawer.sentToRun', { id }))
      await fetchState()
    } catch (e: unknown) {
      items.value = snapshot
      toast.add('error', t('drawer.sendError', { error: e instanceof Error ? e.message : String(e) }))
    }
  }

  async function unqueueTask(id: string) {
    const toast = useToastStore()
    const snapshot = [...items.value]
    // Optimistic: flip back to pending (un-send).
    const idx = items.value.findIndex(it => it.id === id)
    if (idx !== -1) {
      items.value[idx] = { ...items.value[idx], status: 'pending' }
    }
    try {
      await api.unqueueTask(id)
      toast.add('success', t('drawer.unqueued', { id }))
      await fetchState()
    } catch (e: unknown) {
      items.value = snapshot
      toast.add('error', t('drawer.unqueueError', { error: e instanceof Error ? e.message : String(e) }))
    }
  }

  /**
   * Replace a task's full `dependsOn` array (#4). Server validates (self/cycle/unknown
   * → HTTP 400). Deps edits are rare and need server validation, so there's no optimistic
   * mutation — just refetch on success. The drawer shows the 400 error inline (no toast).
   */
  async function patchDeps(id: string, dependsOn: string[]): Promise<{ ok: boolean; error?: string }> {
    const toast = useToastStore()
    try {
      await api.patchDeps(id, dependsOn)
      await fetchState()
      toast.add('success', t('drawer.depsUpdated', { id }))
      return { ok: true }
    } catch (e: unknown) {
      if (e instanceof ApiError) {
        let error = e.message
        try {
          const parsed = JSON.parse(e.body) as { error?: string }
          if (parsed.error) error = parsed.error
        } catch {
          // body not JSON — keep e.message
        }
        return { ok: false, error }
      }
      return { ok: false, error: e instanceof Error ? e.message : String(e) }
    }
  }

  async function reorderItems(newOrder: string[]) {
    const toast = useToastStore()
    const snapshot = [...items.value]
    // Optimistic: reorder local items to match newOrder
    const byId = new Map(items.value.map(it => [it.id, it]))
    const reordered = newOrder.map(id => byId.get(id)).filter((x): x is Item => !!x)
    const rest = items.value.filter(it => !newOrder.includes(it.id))
    items.value = [...reordered, ...rest]
    try {
      const res = await api.reorderTask(newOrder)
      if (!res.ok) {
        items.value = snapshot
        toast.add('error', res.error ?? t('drawer.reorderRejected'))
        return
      }
      await fetchState()
    } catch (e: unknown) {
      items.value = snapshot
      toast.add('error', t('drawer.reorderError', { error: e instanceof Error ? e.message : String(e) }))
    }
  }

  return {
    items, summary, filter, loading, loaded, lastError, lastUpdated, isConnected,
    filteredItems, itemsByStatus,
    fetchState, startPolling, stopPolling,
    requeueItem, deleteItem, moveTop, reorderItems,
    runTask, unqueueTask, patchDeps,
  }
})
