import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useBoardStore } from '@/stores/board'
import { api } from '@/api/client'

vi.mock('@/api/client', () => ({
  api: { reorderTask: vi.fn(), getState: vi.fn() },
}))

describe('board.reorderItems', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('rolls back on {ok:false}', async () => {
    const store = useBoardStore()
    store.items = [
      { id: 'A', title: 'A', status: 'pending', orderIndex: 0 } as never,
      { id: 'B', title: 'B', status: 'pending', orderIndex: 1 } as never,
    ]
    ;(api.reorderTask as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: false, error: 'reorder breaks dependency A before B' })
    await store.reorderItems(['B', 'A'])
    // rolled back to original order
    expect(store.items.map(i => i.id)).toEqual(['A', 'B'])
  })

  it('keeps optimistic order and refetches on ok', async () => {
    const store = useBoardStore()
    store.items = [
      { id: 'A', title: 'A', status: 'pending', orderIndex: 0 } as never,
      { id: 'B', title: 'B', status: 'pending', orderIndex: 1 } as never,
    ]
    ;(api.reorderTask as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, order: ['B', 'A'] })
    ;(api.getState as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [{ id: 'B' }, { id: 'A' }], summary: store.summary,
    })
    await store.reorderItems(['B', 'A'])
    expect(api.getState).toHaveBeenCalled()
  })
})
