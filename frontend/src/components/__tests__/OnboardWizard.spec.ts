import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import OnboardWizard from '../OnboardWizard.vue'
import { useWorkspaceStore } from '@/stores/workspace'
import { api } from '@/api/client'
import type { Connection } from '@/types/api'

vi.mock('@/api/client', () => ({
  api: {
    getClis: vi.fn(),
    getConnections: vi.fn(),
    getConnectionPresets: vi.fn(),
    createConnection: vi.fn(),
    deleteConnection: vi.fn(),
    testConnection: vi.fn(),
    onboard: vi.fn(),
    listWorkspaces: vi.fn(),
    activateWorkspace: vi.fn(),
  },
}))

vi.mock('@/stores/toast', () => ({ useToastStore: () => ({ add: vi.fn() }) }))

type Fn = ReturnType<typeof vi.fn>

// Stub ConnectionsManager (step 1 controlled via the connections prop) and RepoPicker
// (step 3 onboarding is driven through the manual path input; the picker has its own spec).
const STUBS = {
  ConnectionsManager: { template: '<div data-test="conn-stub" />' },
  RepoPicker: { template: '<div data-test="repo-picker-stub" />' },
}

const CONNECTED: Connection = {
  id: 'conn-ok', label: 'DS', provider: 'deepseek', engine: 'claude',
  authMethod: 'api_key', model: 'deepseek-chat', env: {}, status: 'connected',
}
const UNTESTED: Connection = { ...CONNECTED, id: 'conn-x', status: 'untested' }

const WS = {
  id: 'ws1', name: 'repo', repoPath: '/r', baseBranch: 'main', remote: 'origin',
  branchPrefix: 'auto', strictness: 'standard', onboarded: true,
  agents: { useModels: false, primary: { provider: 'x', model: 'm' }, fallback: { provider: 'x', model: 'm' }, validators: [], arbiters: [], final: null, planner: null },
  review: { enabled: true, tier1Threshold: 5, tier2Threshold: 2, maxRevisions: 2 },
  verifySource: 'agent', verifyCommandsOverride: [], roleConnections: {},
}

function makeWrapper(connections: Connection[] = []) {
  return mount(OnboardWizard, {
    props: { connections },
    global: { plugins: [createPinia()], stubs: STUBS },
  })
}

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.clearAllMocks()
  ;(api.getClis as Fn).mockResolvedValue({
    ok: true,
    clis: {
      claude: { installed: true, version: '2.1.140', auth: {} },
      opencode: { installed: false, version: null, auth: {} },
      codex: { installed: true, version: '0.125.0', auth: {} },
    },
  })
  ;(api.getConnections as Fn).mockResolvedValue({ connections: [] })
  ;(api.listWorkspaces as Fn).mockResolvedValue({ ok: true, workspaces: [], activeId: null })
  ;(api.activateWorkspace as Fn).mockResolvedValue({ ok: true, activeId: 'ws1' })
  ;(api.onboard as Fn).mockResolvedValue({ ok: true, workspace: WS })
})

describe('OnboardWizard', () => {
  it('disables «Далее» on step 1 when no connection is connected', async () => {
    const w = makeWrapper([UNTESTED])
    await flushPromises()
    expect(w.find('[data-test="wiz-step-1"]').exists()).toBe(true)
    const next = w.find('[data-test="wiz-next-1"]')
    expect(next.exists()).toBe(true)
    expect((next.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('enables «Далее» on step 1 when at least one connection is connected', async () => {
    const w = makeWrapper([CONNECTED])
    await flushPromises()
    const next = w.find('[data-test="wiz-next-1"]')
    expect((next.element as HTMLButtonElement).disabled).toBe(false)
  })

  it('navigates to step 3 and gates «Готово» on an active workspace', async () => {
    const w = makeWrapper([CONNECTED])
    await flushPromises()

    // step 1 → step 2
    await w.find('[data-test="wiz-next-1"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="wiz-step-2"]').exists()).toBe(true)

    // step 2 → step 3 (always enabled)
    const next2 = w.find('[data-test="wiz-next-2"]')
    expect((next2.element as HTMLButtonElement).disabled).toBe(false)
    await next2.trigger('click')
    await flushPromises()

    expect(w.find('[data-test="wiz-step-3"]').exists()).toBe(true)
    const done = w.find('[data-test="wiz-done"]')
    expect(done.exists()).toBe(true)
    // activeId null → disabled
    expect((done.element as HTMLButtonElement).disabled).toBe(true)

    // set the store activeId → enabled
    const ws = useWorkspaceStore()
    ws.activeId = 'ws1'
    await flushPromises()
    expect((done.element as HTMLButtonElement).disabled).toBe(false)
  })

  it('shows CLI install state on step 2', async () => {
    const w = makeWrapper([CONNECTED])
    await flushPromises()
    await w.find('[data-test="wiz-next-1"]').trigger('click')
    await flushPromises()
    expect(api.getClis).toHaveBeenCalled()
    const txt = w.find('[data-test="wiz-step-2"]').text()
    expect(txt).toContain('claude')
    expect(txt).toContain('opencode')
    expect(txt).toContain('codex')
  })

  it('onboards the repo and activates the workspace from step 3', async () => {
    const w = makeWrapper([CONNECTED])
    await flushPromises()
    await w.find('[data-test="wiz-next-1"]').trigger('click')
    await flushPromises()
    await w.find('[data-test="wiz-next-2"]').trigger('click')
    await flushPromises()

    await w.find('[data-test="wiz-repo-path"]').setValue('/abs/repo')
    await w.find('[data-test="wiz-add-repo"]').trigger('click')
    await flushPromises()

    // ws.onboard(path) → api.onboard(path), then ws.activate(id) → api.activateWorkspace(id).
    expect(api.onboard).toHaveBeenCalled()
    expect(vi.mocked(api.onboard).mock.calls[0][0]).toBe('/abs/repo')
    expect(api.activateWorkspace).toHaveBeenCalledWith('ws1')

    // Workspace now active in the store → «Готово» becomes enabled.
    expect(useWorkspaceStore().activeId).toBe('ws1')
    expect((w.find('[data-test="wiz-done"]').element as HTMLButtonElement).disabled).toBe(false)
  })

  it('emits skip when «Пропустить» is clicked', async () => {
    const w = makeWrapper([])
    await flushPromises()
    await w.find('[data-test="wiz-skip"]').trigger('click')
    expect(w.emitted('skip')).toBeTruthy()
  })

  it('renders Russian by default and English after the locale switches (UI-001)', async () => {
    const { i18n } = await import('@/i18n')
    const w = makeWrapper([])
    await flushPromises()
    expect(w.find('[data-test="wiz-step-1"]').text()).toContain('Подключите провайдера')

    ;(i18n.global.locale as unknown as { value: string }).value = 'en'
    await flushPromises()
    expect(w.find('[data-test="wiz-step-1"]').text()).toContain('Connect a provider')
    expect(w.find('[data-test="wiz-skip"]').text()).toBe('Skip')
  })
})
