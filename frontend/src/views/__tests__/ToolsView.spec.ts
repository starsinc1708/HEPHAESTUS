import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ToolsView from '../ToolsView.vue'
import { api } from '@/api/client'

vi.mock('@/api/client', () => ({
  api: {
    // workspace store
    listWorkspaces: vi.fn(),
    // ToolsView onMount
    scanStatus: vi.fn(),
    scanList: vi.fn(),
    driverStatus: vi.fn(),
    // Ralph-only autonomous launcher
    driverStart: vi.fn(),
  },
}))

vi.mock('@/stores/toast', () => ({ useToastStore: () => ({ add: vi.fn() }) }))

type Fn = ReturnType<typeof vi.fn>

// Stub heavy children so the test stays focused on composition (incl. the new Insights section).
const STUBS = {
  AppShell: { template: '<div><slot name="title" /><slot /></div>' },
  ScopePicker: { template: '<div />' },
  IntegrationsPanel: { template: '<div />' },
  IdeasPanel: { template: '<div />' },
  ScansPanel: { template: '<div />' },
  InsightsChat: { template: '<div class="insights-chat-stub" />' },
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  ;(api.listWorkspaces as Fn).mockResolvedValue({ ok: true, workspaces: [], activeId: null })
  ;(api.scanStatus as Fn).mockResolvedValue({ phase: 'idle', running: false })
  ;(api.scanList as Fn).mockResolvedValue([])
  ;(api.driverStatus as Fn).mockResolvedValue({ ok: true, runSummary: null })
  ;(api.driverStart as Fn).mockResolvedValue({ ok: true })
})

describe('ToolsView', () => {
  it('renders the folded-in Insights section', async () => {
    const w = mount(ToolsView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    expect(w.find('[data-test="tools-insights"]').exists()).toBe(true)
    w.unmount()
  })

  it('has no queue run-mode selector (Ralph-only autonomous launcher)', async () => {
    const w = mount(ToolsView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    expect(w.find('[data-test="run-mode"]').exists()).toBe(false)
    w.unmount()
  })

  it('starting calls driverStart with runMode ralph + budgets', async () => {
    const w = mount(ToolsView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    await w.find('[data-test="ralph-start"]').trigger('click')
    await flushPromises()
    expect(api.driverStart).toHaveBeenCalledWith(
      expect.objectContaining({ runMode: 'ralph', costBudgetUsd: 1, wallclockSec: 3600 }),
    )
    w.unmount()
  })
})
