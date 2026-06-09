import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useConversationStore } from '@/stores/conversation'
import { api } from '@/api/client'
import type { TaskConversations, ConversationMessage } from '@/types/api'

vi.mock('@/api/client', () => ({
  api: { taskConversations: vi.fn(), iterConversation: vi.fn() },
}))

vi.mock('@/stores/toast', () => ({ useToastStore: () => ({ add: vi.fn() }) }))

type Fn = ReturnType<typeof vi.fn>

const TREE: TaskConversations = {
  ok: true,
  itemId: 'task-1',
  iterations: [
    { dir: 'iter-0001', createdAt: '2026-06-07T00:00:00Z', attempts: 1, stages: [] },
  ],
}

const MESSAGES: ConversationMessage[] = [
  { role: 'assistant', kind: 'text', text: '# hi', tsMs: 1700000000000, tokens: { input: 10, output: 20 } },
]

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('conversation store — loadTree', () => {
  it('loads the tree and sets state', async () => {
    ;(api.taskConversations as Fn).mockResolvedValue(TREE)
    const store = useConversationStore()

    const res = await store.loadTree('task-1')

    expect(api.taskConversations).toHaveBeenCalledWith('task-1')
    expect(res).toEqual(TREE)
    expect(store.tree).toEqual(TREE)
  })

  it('sets tree=null and does not throw on a rejected api call', async () => {
    ;(api.taskConversations as Fn).mockRejectedValue(new Error('boom'))
    const store = useConversationStore()

    const res = await store.loadTree('task-1')

    expect(res).toBeNull()
    expect(store.tree).toBeNull()
  })
})

describe('conversation store — fetchMessages', () => {
  it('returns messages and caches them (second call does not re-fetch)', async () => {
    ;(api.iterConversation as Fn).mockResolvedValue(MESSAGES)
    const store = useConversationStore()

    const first = await store.fetchMessages('iter-1', 'output.primary')
    expect(first).toEqual(MESSAGES)
    expect(api.iterConversation).toHaveBeenCalledTimes(1)
    expect(api.iterConversation).toHaveBeenCalledWith('iter-1', 'output.primary')

    const second = await store.fetchMessages('iter-1', 'output.primary')
    expect(second).toEqual(MESSAGES)
    expect(api.iterConversation).toHaveBeenCalledTimes(1) // served from cache
  })

  it('re-fetches when force=true', async () => {
    ;(api.iterConversation as Fn).mockResolvedValue(MESSAGES)
    const store = useConversationStore()

    await store.fetchMessages('iter-1', 'output.primary')
    await store.fetchMessages('iter-1', 'output.primary', true)

    expect(api.iterConversation).toHaveBeenCalledTimes(2)
  })

  it('returns [] and does not throw on a rejected api call', async () => {
    ;(api.iterConversation as Fn).mockRejectedValue(new Error('boom'))
    const store = useConversationStore()

    const res = await store.fetchMessages('iter-1', 'output.primary')

    expect(res).toEqual([])
  })
})

describe('conversation store — clear', () => {
  it('resets tree and message cache', async () => {
    ;(api.taskConversations as Fn).mockResolvedValue(TREE)
    ;(api.iterConversation as Fn).mockResolvedValue(MESSAGES)
    const store = useConversationStore()

    await store.loadTree('task-1')
    await store.fetchMessages('iter-1', 'output.primary')
    store.clear()

    expect(store.tree).toBeNull()
    // cache cleared → next fetch hits the api again
    await store.fetchMessages('iter-1', 'output.primary')
    expect(api.iterConversation).toHaveBeenCalledTimes(2)
  })
})
