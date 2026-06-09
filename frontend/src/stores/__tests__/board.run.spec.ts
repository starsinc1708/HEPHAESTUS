import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useBoardStore } from '@/stores/board'
import { api } from '@/api/client'

vi.mock('@/api/client', () => ({
  api: { runTask: vi.fn(), unqueueTask: vi.fn(), getState: vi.fn() },
}))

vi.mock('@/stores/toast', () => ({ useToastStore: () => ({ add: vi.fn() }) }))

type Fn = ReturnType<typeof vi.fn>

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('board.runTask', () => {
  it('optimistically flips to queued, calls api.runTask, and refetches', async () => {
    const store = useBoardStore()
    store.items = [{ id: 'A', title: 'A', status: 'pending' } as never]
    ;(api.runTask as Fn).mockResolvedValue({ ok: true, status: 'queued' })
    ;(api.getState as Fn).mockResolvedValue({ items: [{ id: 'A', status: 'queued' }], summary: store.summary })

    await store.runTask('A')

    expect(api.runTask).toHaveBeenCalledWith('A')
    expect(api.getState).toHaveBeenCalled()
  })

  it('rolls back on error', async () => {
    const store = useBoardStore()
    store.items = [{ id: 'A', title: 'A', status: 'pending' } as never]
    ;(api.runTask as Fn).mockRejectedValue(new Error('boom'))

    await store.runTask('A')

    expect(store.items[0].status).toBe('pending')
    expect(api.getState).not.toHaveBeenCalled()
  })
})

describe('board.unqueueTask', () => {
  it('optimistically flips to pending, calls api.unqueueTask, and refetches', async () => {
    const store = useBoardStore()
    store.items = [{ id: 'A', title: 'A', status: 'queued' } as never]
    ;(api.unqueueTask as Fn).mockResolvedValue({ ok: true, status: 'pending' })
    ;(api.getState as Fn).mockResolvedValue({ items: [{ id: 'A', status: 'pending' }], summary: store.summary })

    await store.unqueueTask('A')

    expect(api.unqueueTask).toHaveBeenCalledWith('A')
    expect(api.getState).toHaveBeenCalled()
  })

  it('rolls back on error', async () => {
    const store = useBoardStore()
    store.items = [{ id: 'A', title: 'A', status: 'queued' } as never]
    ;(api.unqueueTask as Fn).mockRejectedValue(new Error('boom'))

    await store.unqueueTask('A')

    expect(store.items[0].status).toBe('queued')
    expect(api.getState).not.toHaveBeenCalled()
  })
})
