import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import InsightsChat from '@/components/InsightsChat.vue'
import { api } from '@/api/client'

vi.mock('@/api/client', () => ({
  api: {
    askInsights: vi.fn().mockResolvedValue({
      ok: true,
      sessionId: 'sess-1',
      iterDir: 'iter_20240101_120000',
      answer: 'The auth module uses JWT tokens.',
      modifiedFiles: [],
    }),
    // rebuildMap now returns job shape immediately
    rebuildMap: vi.fn().mockResolvedValue({ ok: true, jobId: 'ajob-1', kind: 'map' }),
    getAgentJob: vi.fn().mockResolvedValue({
      ok: true,
      id: 'ajob-1',
      kind: 'map',
      status: 'done',
      result: { count: 42 },
      error: null,
      outputDir: 'ajob-1',
    }),
  },
}))

vi.mock('@/stores/toast', () => ({ useToastStore: () => ({ add: vi.fn() }) }))

// Stub LiveConsole to avoid EventSource issues in jsdom
vi.mock('@/components/LiveConsole.vue', () => ({
  default: {
    name: 'LiveConsole',
    props: ['iterDir', 'active', 'streamUrl'],
    template: '<div class="live-console-stub" />',
  },
}))

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  ;(api.askInsights as ReturnType<typeof vi.fn>).mockResolvedValue({
    ok: true,
    sessionId: 'sess-1',
    iterDir: 'iter_20240101_120000',
    answer: 'The auth module uses JWT tokens.',
    modifiedFiles: [],
  })
  ;(api.rebuildMap as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, jobId: 'ajob-1', kind: 'map' })
  ;(api.getAgentJob as ReturnType<typeof vi.fn>).mockResolvedValue({
    ok: true,
    id: 'ajob-1',
    kind: 'map',
    status: 'done',
    result: { count: 42 },
    error: null,
    outputDir: 'ajob-1',
  })
})

describe('InsightsChat', () => {
  it('typing a question and clicking Send calls askInsights', async () => {
    const w = mount(InsightsChat)

    await w.find('textarea').setValue('How does auth work?')
    await w.find('[data-test="send-insight"]').trigger('click')
    await flushPromises()

    expect(api.askInsights).toHaveBeenCalledWith('How does auth work?', undefined)
  })

  it('after resolve, the answer text is rendered in the transcript', async () => {
    const w = mount(InsightsChat)

    await w.find('textarea').setValue('How does auth work?')
    await w.find('[data-test="send-insight"]').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('The auth module uses JWT tokens.')
  })

  it('send button is disabled when textarea is empty', () => {
    const w = mount(InsightsChat)
    expect(w.find('[data-test="send-insight"]').attributes('disabled')).toBeDefined()
  })

  it('renders user bubble with the question', async () => {
    const w = mount(InsightsChat)

    await w.find('textarea').setValue('What is the DB schema?')
    await w.find('[data-test="send-insight"]').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('What is the DB schema?')
  })

  it('rebuild-map button calls rebuildMap and then getAgentJob', async () => {
    const w = mount(InsightsChat)

    await w.find('[data-test="rebuild-map"]').trigger('click')
    await flushPromises()

    expect(api.rebuildMap).toHaveBeenCalled()
    expect(api.getAgentJob).toHaveBeenCalledWith('ajob-1')
  })

  it('passes sessionId on subsequent questions', async () => {
    const w = mount(InsightsChat)

    await w.find('textarea').setValue('First question')
    await w.find('[data-test="send-insight"]').trigger('click')
    await flushPromises()

    await w.find('textarea').setValue('Follow-up question')
    await w.find('[data-test="send-insight"]').trigger('click')
    await flushPromises()

    expect(api.askInsights).toHaveBeenNthCalledWith(2, 'Follow-up question', 'sess-1')
  })
})
