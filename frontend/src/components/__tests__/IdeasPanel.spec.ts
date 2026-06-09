import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import IdeasPanel from '@/components/IdeasPanel.vue'
import { api } from '@/api/client'

// IDEAS must be defined inside vi.mock factory (hoisted before module init).
// We repeat the data in beforeEach resets via a factory function.
function makeIdeas() {
  return [
    {
      id: 'idea-1',
      title: 'Refactor auth module',
      proposal: 'Extract auth logic into a dedicated service',
      rationale: 'Improves testability',
      category: 'quality',
      severity: 'quality',
      touches: ['src/auth.ts'],
      imported: false,
    },
    {
      id: 'idea-2',
      title: 'Add rate limiting',
      proposal: 'Implement rate limiting on public API endpoints',
      rationale: 'Security improvement',
      category: 'security',
      severity: 'security',
      touches: ['src/api.ts'],
      imported: false,
    },
  ]
}

vi.mock('@/api/client', () => ({
  api: {
    listIdeas: vi.fn().mockResolvedValue({ ok: true, ideas: [] }),
    // generateIdeas now returns job shape immediately
    generateIdeas: vi.fn().mockResolvedValue({ ok: true, jobId: 'ajob-1', kind: 'ideas' }),
    getAgentJob: vi.fn().mockResolvedValue({
      ok: true,
      id: 'ajob-1',
      kind: 'ideas',
      status: 'done',
      result: {
        ideas: [
          {
            id: 'idea-1',
            title: 'Refactor auth module',
            proposal: 'Extract auth logic into a dedicated service',
            rationale: 'Improves testability',
            category: 'quality',
            severity: 'quality',
            touches: ['src/auth.ts'],
            imported: false,
          },
          {
            id: 'idea-2',
            title: 'Add rate limiting',
            proposal: 'Implement rate limiting on public API endpoints',
            rationale: 'Security improvement',
            category: 'security',
            severity: 'security',
            touches: ['src/api.ts'],
            imported: false,
          },
        ],
      },
      error: null,
      outputDir: 'ajob-1',
    }),
    importIdeas: vi.fn().mockResolvedValue({ ok: true, added: 1 }),
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
  ;(api.listIdeas as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, ideas: [] })
  ;(api.generateIdeas as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, jobId: 'ajob-1', kind: 'ideas' })
  ;(api.getAgentJob as ReturnType<typeof vi.fn>).mockResolvedValue({
    ok: true,
    id: 'ajob-1',
    kind: 'ideas',
    status: 'done',
    result: { ideas: makeIdeas() },
    error: null,
    outputDir: 'ajob-1',
  })
  ;(api.importIdeas as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, added: 1 })
})

describe('IdeasPanel', () => {
  it('calls listIdeas on mount', async () => {
    mount(IdeasPanel)
    await flushPromises()
    expect(api.listIdeas).toHaveBeenCalled()
  })

  it('generate renders at least 1 idea card after job completes', async () => {
    const w = mount(IdeasPanel)
    await flushPromises()

    await w.find('[data-test="gen-ideas"]').trigger('click')
    await flushPromises()

    expect(api.generateIdeas).toHaveBeenCalled()
    expect(api.getAgentJob).toHaveBeenCalledWith('ajob-1')
    const cards = w.findAll('[data-test="idea-card"]')
    expect(cards.length).toBeGreaterThanOrEqual(1)
    expect(w.text()).toContain('Refactor auth module')
  })

  it('selecting a card + import calls importIdeas with that id', async () => {
    const w = mount(IdeasPanel)
    await flushPromises()

    // Generate ideas first
    await w.find('[data-test="gen-ideas"]').trigger('click')
    await flushPromises()

    // Click the first idea card to select it
    const firstCard = w.find('[data-test="idea-card"]')
    await firstCard.trigger('click')

    // Click import
    await w.find('[data-test="ideas-import"]').trigger('click')
    await flushPromises()

    expect(api.importIdeas).toHaveBeenCalledWith(['idea-1'])
  })

  it('import button is disabled when nothing is selected', async () => {
    const w = mount(IdeasPanel)
    await flushPromises()
    await w.find('[data-test="gen-ideas"]').trigger('click')
    await flushPromises()

    expect(w.find('[data-test="ideas-import"]').attributes('disabled')).toBeDefined()
  })

  it('renders idea title and category badge', async () => {
    const w = mount(IdeasPanel)
    await flushPromises()
    await w.find('[data-test="gen-ideas"]').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('Refactor auth module')
    expect(w.text()).toContain('quality')
  })
})
