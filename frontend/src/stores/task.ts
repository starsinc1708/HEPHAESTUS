import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Item, IterDetails, ParsedEvent, IterReviewsResponse, ValidationResult, TaskChecks } from '@/types/api'
import { api } from '@/api/client'
import { useToastStore } from './toast'
import { i18n } from '@/i18n'
const t = i18n.global.t

const CACHE_TTL = 5 * 60 * 1000

interface CachedEntry<T> {
  data: T
  timestamp: number
}

function isExpired<T>(entry: CachedEntry<T> | undefined): boolean {
  if (!entry) return true
  return Date.now() - entry.timestamp > CACHE_TTL
}

export const useTaskStore = defineStore('task', () => {
  const activeDrawerTaskId = ref<string | null>(null)
  const activeTab = ref(0)
  const itemCache = ref<Map<string, CachedEntry<Item>>>(new Map())
  const detailsCache = ref<Map<string, CachedEntry<IterDetails>>>(new Map())
  const eventsCache = ref<Map<string, CachedEntry<ParsedEvent[]>>>(new Map())
  const diffCache = ref<Map<string, CachedEntry<string>>>(new Map())
  const reviewsCache = ref<Map<string, CachedEntry<IterReviewsResponse>>>(new Map())
  const validationCache = ref<Map<string, CachedEntry<ValidationResult | null>>>(new Map())
  const checksCache = ref<Map<string, CachedEntry<TaskChecks>>>(new Map())
  const loading = ref(false)

  function openDrawer(taskId: string, tab = 0, lastIter?: string) {
    activeDrawerTaskId.value = taskId
    activeTab.value = tab
    if (lastIter) {
      prefetchAll(lastIter)
    }
  }

  function closeDrawer() {
    activeDrawerTaskId.value = null
    activeTab.value = 0
  }

  function getItem(items: Item[], id: string): Item | undefined {
    const cached = itemCache.value.get(id)
    if (cached && !isExpired(cached)) return cached.data
    return items.find(it => it.id === id)
  }

  async function fetchDetails(dir: string, force = false): Promise<IterDetails | null> {
    const cached = detailsCache.value.get(dir)
    if (!force && cached && !isExpired(cached)) return cached.data
    const toast = useToastStore()
    try {
      const d = await api.iterDetails(dir)
      detailsCache.value.set(dir, { data: d, timestamp: Date.now() })
      return d
    } catch (e: unknown) {
      toast.add('error', t('drawer.iterLoadError', { error: e instanceof Error ? e.message : String(e) }))
      return null
    }
  }

  async function fetchEvents(dir: string, stream = 'primary', force = false): Promise<ParsedEvent[]> {
    const key = `${dir}:${stream}`
    const cached = eventsCache.value.get(key)
    if (!force && cached && !isExpired(cached)) return cached.data
    const toast = useToastStore()
    try {
      loading.value = true
      const ev = await api.iterEvents(dir, stream)
      eventsCache.value.set(key, { data: ev, timestamp: Date.now() })
      return ev
    } catch (e: unknown) {
      toast.add('error', t('drawer.eventsLoadError', { error: e instanceof Error ? e.message : String(e) }))
      return []
    } finally {
      loading.value = false
    }
  }

  async function fetchDiff(dir: string, force = false): Promise<string | null> {
    const cached = diffCache.value.get(dir)
    if (!force && cached && !isExpired(cached)) return cached.data
    try {
      const d = await api.iterDiff(dir)
      diffCache.value.set(dir, { data: d, timestamp: Date.now() })
      return d
    } catch {
      return null
    }
  }

  async function fetchReviews(dir: string, force = false): Promise<IterReviewsResponse | null> {
    const cached = reviewsCache.value.get(dir)
    if (!force && cached && !isExpired(cached)) return cached.data
    try {
      const r = await api.iterReviews(dir)
      reviewsCache.value.set(dir, { data: r, timestamp: Date.now() })
      return r
    } catch {
      return null
    }
  }

  async function fetchValidation(dir: string, force = false): Promise<ValidationResult | null> {
    const cached = validationCache.value.get(dir)
    if (!force && cached && !isExpired(cached)) return cached.data
    try {
      const d = await api.iterDetails(dir)
      const v = (d as IterDetails & { validation?: ValidationResult }).validation ?? null
      validationCache.value.set(dir, { data: v, timestamp: Date.now() })
      return v
    } catch {
      return null
    }
  }

  async function fetchChecks(id: string, force = false): Promise<TaskChecks | null> {
    const cached = checksCache.value.get(id)
    if (!force && cached && !isExpired(cached)) return cached.data
    try {
      const res = await api.getTaskChecks(id)
      const checks: TaskChecks = {
        verifyOutcome: res.verifyOutcome ?? null,
        scopeExtra: res.scopeExtra ?? [],
      }
      checksCache.value.set(id, { data: checks, timestamp: Date.now() })
      return checks
    } catch {
      return null // null = load error, distinct from a loaded-but-empty result
    }
  }

  function prefetchAll(dir: string) {
    void Promise.allSettled([
      fetchDetails(dir),
      fetchEvents(dir, 'primary'),
      fetchDiff(dir),
      fetchReviews(dir),
    ])
  }

  function clearCache() {
    itemCache.value.clear()
    detailsCache.value.clear()
    eventsCache.value.clear()
    diffCache.value.clear()
    reviewsCache.value.clear()
    validationCache.value.clear()
    checksCache.value.clear()
  }

  return {
    activeDrawerTaskId, activeTab, loading,
    openDrawer, closeDrawer, getItem,
    fetchDetails, fetchEvents, fetchDiff, fetchReviews, fetchValidation, fetchChecks,
    prefetchAll, clearCache,
  }
})
