import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AgentsRunControls from '@/components/AgentsRunControls.vue'
import { useLoopStore } from '@/stores/loop'
import { api } from '@/api/client'
import type { DriverStatus } from '@/types/api'

vi.mock('@/api/client', () => ({
  api: {
    getState: vi.fn(),
    driverStatus: vi.fn(),
    driverPause: vi.fn(),
    driverResume: vi.fn(),
    driverKill: vi.fn(),
  },
}))

// Keep the live grid inert — we only assert on the controls row.
const STUBS = {
  LiveConsole: { template: '<div />' },
  StatusBadge: { template: '<span />' },
}

type Fn = ReturnType<typeof vi.fn>

function driver(partial: Partial<DriverStatus>): DriverStatus {
  return {
    process: { state: 'idle', pid: null, children: [] },
    tmux: false, driver_pid: null, opencode_pids: [],
    runSummary: null, paused: false, queued: 0, inProgress: 0,
    ...partial,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  ;(api.getState as Fn).mockResolvedValue({ items: [] })
  ;(api.driverStatus as Fn).mockResolvedValue(driver({}))
  ;(api.driverPause as Fn).mockResolvedValue({ ok: true, paused: true })
  ;(api.driverResume as Fn).mockResolvedValue({ ok: true, paused: false })
  ;(api.driverKill as Fn).mockResolvedValue({ ok: true })
})

describe('AgentsRunControls — auto-driver status', () => {
  it('never renders a «Старт» button', async () => {
    const w = mount(AgentsRunControls, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    expect(w.find('[data-test="loop-start"]').exists()).toBe(false)
    w.unmount()
  })

  it('shows the running indicator with in-progress / queued counts', async () => {
    const w = mount(AgentsRunControls, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    const store = useLoopStore()
    store.driver = driver({ process: { state: 'running', pid: 1, children: [] }, inProgress: 2, queued: 3 })
    await flushPromises()
    const ind = w.find('[data-test="driver-indicator"]')
    expect(ind.text()).toContain('работает (2 в работе, 3 в очереди)')
    w.unmount()
  })

  it('shows the paused indicator when paused', async () => {
    const w = mount(AgentsRunControls, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    const store = useLoopStore()
    store.driver = driver({ process: { state: 'running', pid: 1, children: [] }, paused: true })
    await flushPromises()
    expect(w.find('[data-test="driver-indicator"]').text()).toContain('на паузе')
    w.unmount()
  })

  it('shows the idle indicator when not running and not paused', async () => {
    const w = mount(AgentsRunControls, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    const store = useLoopStore()
    store.driver = driver({ process: { state: 'idle', pid: null, children: [] } })
    await flushPromises()
    expect(w.find('[data-test="driver-indicator"]').text()).toContain('простаивает')
    w.unmount()
  })

  it('shows «Стоп» (calls driverPause) when running & not paused', async () => {
    const w = mount(AgentsRunControls, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    const store = useLoopStore()
    store.driver = driver({ process: { state: 'running', pid: 1, children: [] }, paused: false })
    await flushPromises()
    const toggle = w.find('[data-test="driver-toggle"]')
    expect(toggle.exists()).toBe(true)
    expect(toggle.text()).toContain('Стоп')
    await toggle.trigger('click')
    await flushPromises()
    expect(api.driverPause).toHaveBeenCalled()
    expect(api.driverResume).not.toHaveBeenCalled()
    w.unmount()
  })

  it('shows «Возобновить» (calls driverResume) when paused', async () => {
    const w = mount(AgentsRunControls, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    const store = useLoopStore()
    store.driver = driver({ process: { state: 'running', pid: 1, children: [] }, paused: true })
    await flushPromises()
    const toggle = w.find('[data-test="driver-toggle"]')
    expect(toggle.exists()).toBe(true)
    expect(toggle.text()).toContain('Возобновить')
    await toggle.trigger('click')
    await flushPromises()
    expect(api.driverResume).toHaveBeenCalled()
    expect(api.driverPause).not.toHaveBeenCalled()
    w.unmount()
  })

  it('renders NO toggle button when idle & not paused (indicator only)', async () => {
    const w = mount(AgentsRunControls, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    const store = useLoopStore()
    store.driver = driver({ process: { state: 'idle', pid: null, children: [] }, paused: false })
    await flushPromises()
    // No pause/resume toggle — clicking a phantom «Стоп» must not POST to an idle driver.
    expect(w.find('[data-test="driver-toggle"]').exists()).toBe(false)
    // The status indicator is still shown.
    expect(w.find('[data-test="driver-indicator"]').exists()).toBe(true)
    w.unmount()
  })
})
