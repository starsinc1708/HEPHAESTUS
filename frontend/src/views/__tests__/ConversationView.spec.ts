import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import { routes } from '@/router'
import { api } from '@/api/client'
import ConversationView from '@/views/ConversationView.vue'
import type { TaskConversations, ConversationMessage } from '@/types/api'

vi.mock('@/api/client', () => ({
  api: {
    taskConversations: vi.fn(),
    iterConversation: vi.fn(),
  },
}))

vi.mock('@/stores/toast', () => ({
  useToastStore: () => ({ add: vi.fn() }),
}))

type Fn = ReturnType<typeof vi.fn>

const TREE: TaskConversations = {
  ok: true,
  itemId: 'task-1',
  iterations: [
    {
      dir: 'iter-0001',
      createdAt: '2026-06-08',
      attempts: 2,
      stages: [
        {
          stage: 'implement',
          agents: [
            {
              stream: 'output.primary', role: 'implementer', revision: 2, current: true,
              model: 'deepseek', status: 'done', messages: 12, costUsd: 0.01,
            },
          ],
        },
        {
          stage: 'validate',
          agents: [
            {
              stream: 'validation.r2.lint', role: 'validator:lint', revision: 2, current: false,
              model: 'deepseek', status: 'approve', messages: 4, costUsd: 0.002,
            },
          ],
        },
      ],
    },
  ],
}

const MESSAGES: ConversationMessage[] = [
  { role: 'user', kind: 'text', text: 'do the thing' },
  { role: 'assistant', kind: 'text', text: 'done' },
]

function makeRouter() {
  return createRouter({ history: createWebHistory(), routes })
}

async function mountView() {
  const router = makeRouter()
  const pinia = createPinia()
  setActivePinia(pinia)
  router.push('/board/task/task-1/conversation')
  await router.isReady()
  const w = mount(ConversationView, {
    props: { id: 'task-1' },
    global: { plugins: [router, pinia] },
  })
  await flushPromises()
  return { w, router }
}

describe('ConversationView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    ;(api.taskConversations as Fn).mockResolvedValue(TREE)
    ;(api.iterConversation as Fn).mockResolvedValue(MESSAGES)
  })

  it('renders the tree and pane after the tree loads', async () => {
    const { w } = await mountView()
    expect(w.find('[data-test="conv-tree"]').exists()).toBe(true)
    expect(w.find('[data-test="conv-pane"]').exists()).toBe(true)
    expect(w.find('[data-test="conv-back"]').exists()).toBe(true)
  })

  it('auto-selects the current output.primary implementer and loads its messages', async () => {
    await mountView()
    expect(api.taskConversations).toHaveBeenCalledWith('task-1')
    expect(api.iterConversation).toHaveBeenCalledWith('iter-0001', 'output.primary')
  })

  it('clicking a different agent row loads that stream', async () => {
    const { w } = await mountView()
    ;(api.iterConversation as Fn).mockClear()
    await w.find('[data-test="conv-agent-validation.r2.lint"]').trigger('click')
    await flushPromises()
    expect(api.iterConversation).toHaveBeenCalledWith('iter-0001', 'validation.r2.lint')
  })

  it('back button routes to board-task for this id', async () => {
    const { w, router } = await mountView()
    const spy = vi.spyOn(router, 'push')
    await w.find('[data-test="conv-back"]').trigger('click')
    await flushPromises()
    expect(spy).toHaveBeenCalledWith({ name: 'board-task', params: { id: 'task-1' } })
  })

  it('shows the empty state when there are no iterations', async () => {
    ;(api.taskConversations as Fn).mockResolvedValue({ ok: true, itemId: 'task-1', iterations: [] })
    const { w } = await mountView()
    expect(w.find('[data-test="conv-tree-empty"]').exists()).toBe(true)
    expect(w.find('[data-test="conv-tree"]').exists()).toBe(false)
  })
})
