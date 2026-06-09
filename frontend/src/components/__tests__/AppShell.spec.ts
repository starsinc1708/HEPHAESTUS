import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import { routes } from '@/router'
import { api } from '@/api/client'
import { useLoopStore } from '@/stores/loop'
import type { DriverStatus } from '@/types/api'
import AppShell from '../AppShell.vue'

vi.mock('@/api/client', () => ({
  api: {
    getState: vi.fn(),
    listWorkspaces: vi.fn(),
    activateWorkspace: vi.fn(),
    getConnections: vi.fn(),
    driverStatus: vi.fn(),
    driverPause: vi.fn(),
    driverResume: vi.fn(),
  },
}))

vi.mock('@/stores/toast', () => ({
  useToastStore: () => ({ toasts: [], add: vi.fn(), dismiss: vi.fn(), undo: vi.fn() }),
}))

type Fn = ReturnType<typeof vi.fn>

const STATE = {
  items: [], summary: {}, current: null, log_tail: ['line one', 'line two'],
  loopStatus: { process: { state: 'idle', pid: null, children: [] }, tmux: false, driver_pid: null, opencode_pids: [] },
  git: {}, updatedAt: '',
}

function driver(partial: Partial<DriverStatus>): DriverStatus {
  return {
    process: { state: 'idle', pid: null, children: [] },
    tmux: false, driver_pid: null, opencode_pids: [],
    runSummary: null, paused: false, queued: 0, inProgress: 0,
    ...partial,
  }
}

const CONNECTED = {
  id: 'conn-ok', label: 'DS', provider: 'deepseek', engine: 'claude',
  authMethod: 'api_key', model: 'deepseek-chat', env: {}, status: 'connected',
}

// Stub OnboardWizard so AppShell tests don't pull in ConnectionsManager's api churn.
const ONBOARD_STUB = {
  OnboardWizard: {
    template: '<div data-test="onboard-wizard"><button data-test="wiz-skip" @click="$emit(\'skip\')" /></div>',
    emits: ['skip', 'connections-changed'],
  },
}

function makeRouter() {
  return createRouter({ history: createWebHistory(), routes })
}

function mountShell() {
  const router = makeRouter()
  router.push('/board')
  // Use the active pinia (set in beforeEach) so tests can drive loopStore.driver.
  const pinia = createPinia()
  setActivePinia(pinia)
  return router.isReady().then(() =>
    mount(AppShell, {
      global: { plugins: [router, pinia], stubs: { 'router-view': true, ...ONBOARD_STUB } },
    }),
  )
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  setActivePinia(createPinia())
  ;(api.getState as Fn).mockResolvedValue(STATE)
  // Default: NOT needing onboarding (one connected connection + active workspace).
  ;(api.listWorkspaces as Fn).mockResolvedValue({ ok: true, workspaces: [], activeId: 'ws1' })
  ;(api.getConnections as Fn).mockResolvedValue({ connections: [CONNECTED] })
  ;(api.driverStatus as Fn).mockResolvedValue(driver({}))
  ;(api.driverPause as Fn).mockResolvedValue({ ok: true, paused: true })
  ;(api.driverResume as Fn).mockResolvedValue({ ok: true, paused: false })
})

describe('AppShell', () => {
  it('renders exactly five nav items', async () => {
    const w = await mountShell()
    expect(w.findAll('[data-test="nav-link"]')).toHaveLength(5)
  })

  it('logs toggle opens the logs drawer', async () => {
    const w = await mountShell()
    expect(w.find('[data-test="logs-drawer"]').exists()).toBe(false)
    await w.find('[data-test="logs-toggle"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="logs-drawer"]').exists()).toBe(true)
  })

  it('does not show the wizard when connections exist and a workspace is active', async () => {
    const w = await mountShell()
    await flushPromises()
    expect(w.find('[data-test="onboard-wizard"]').exists()).toBe(false)
  })

  it('shows the wizard when there are no connections', async () => {
    ;(api.getConnections as Fn).mockResolvedValue({ connections: [] })
    const w = await mountShell()
    await flushPromises()
    expect(w.find('[data-test="onboard-wizard"]').exists()).toBe(true)
  })

  it('shows the wizard when no workspace is active', async () => {
    ;(api.listWorkspaces as Fn).mockResolvedValue({ ok: true, workspaces: [], activeId: null })
    const w = await mountShell()
    await flushPromises()
    expect(w.find('[data-test="onboard-wizard"]').exists()).toBe(true)
  })

  it('replaces the wizard with a banner after skip', async () => {
    ;(api.getConnections as Fn).mockResolvedValue({ connections: [] })
    const w = await mountShell()
    await flushPromises()
    expect(w.find('[data-test="onboard-wizard"]').exists()).toBe(true)
    await w.find('[data-test="wiz-skip"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="onboard-wizard"]').exists()).toBe(false)
    expect(w.find('[data-test="onboard-banner"]').exists()).toBe(true)
  })

  it('reopens the wizard from the banner', async () => {
    ;(api.getConnections as Fn).mockResolvedValue({ connections: [] })
    const w = await mountShell()
    await flushPromises()
    await w.find('[data-test="wiz-skip"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="onboard-banner"]').exists()).toBe(true)
    await w.find('[data-test="onboard-reopen"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="onboard-wizard"]').exists()).toBe(true)
    expect(w.find('[data-test="onboard-banner"]').exists()).toBe(false)
  })

  // ── Auto-driver toggle (Sub-project #3): the shell NEVER starts the loop ──

  it('shows no driver toggle when the driver is idle (and never a start button)', async () => {
    const w = await mountShell()
    const store = useLoopStore()
    store.driver = driver({ process: { state: 'idle', pid: null, children: [] }, paused: false })
    await flushPromises()
    // Idle + not paused → no toggle rendered at all (no manual start).
    expect(w.find('[data-test="driver-toggle-shell"]').exists()).toBe(false)
  })

  it('shows «Стоп» that calls pauseDriver when the driver is running', async () => {
    const w = await mountShell()
    const store = useLoopStore()
    store.driver = driver({ process: { state: 'running', pid: 1, children: [] }, paused: false })
    await flushPromises()
    const toggle = w.find('[data-test="driver-toggle-shell"]')
    expect(toggle.exists()).toBe(true)
    expect(toggle.text()).toContain('Стоп')
    await toggle.trigger('click')
    await flushPromises()
    expect(api.driverPause).toHaveBeenCalled()
    expect(api.driverResume).not.toHaveBeenCalled()
  })

  it('shows «Возобновить» that calls resumeDriver when the driver is paused', async () => {
    const w = await mountShell()
    const store = useLoopStore()
    store.driver = driver({ process: { state: 'running', pid: 1, children: [] }, paused: true })
    await flushPromises()
    const toggle = w.find('[data-test="driver-toggle-shell"]')
    expect(toggle.exists()).toBe(true)
    expect(toggle.text()).toContain('Возобновить')
    await toggle.trigger('click')
    await flushPromises()
    expect(api.driverResume).toHaveBeenCalled()
    expect(api.driverPause).not.toHaveBeenCalled()
  })
})
