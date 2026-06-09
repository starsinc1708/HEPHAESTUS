import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import SettingsView from '../SettingsView.vue'
import { api } from '@/api/client'

vi.mock('@/api/client', () => ({
  api: {
    // workspace store
    listWorkspaces: vi.fn(),
    updateWorkspace: vi.fn(),
    activateWorkspace: vi.fn(),
    onboard: vi.fn(),
    // config store
    getConfig: vi.fn(),
    putConfig: vi.fn(),
    configPreset: vi.fn(),
    // connections
    getClis: vi.fn(),
    getConnectionPresets: vi.fn(),
    getConnections: vi.fn(),
    createConnection: vi.fn(),
    deleteConnection: vi.fn(),
    testConnection: vi.fn(),
    // integrations (IntegrationsPanel calls this on mount)
    listIntegrations: vi.fn(),
  },
}))

vi.mock('@/stores/toast', () => ({ useToastStore: () => ({ add: vi.fn() }) }))

type Fn = ReturnType<typeof vi.fn>

const WS = {
  id: 'ws1', name: 'repo', repoPath: '/r', baseBranch: 'main', remote: 'origin',
  branchPrefix: 'auto', strictness: 'standard', onboarded: true,
  agents: {
    useModels: false,
    primary: { provider: 'x', model: 'm' },
    fallback: { provider: 'x', model: 'm' },
    validators: [], arbiters: [], final: null, planner: null,
  },
  review: { enabled: true, tier1Threshold: 5, tier2Threshold: 2, maxRevisions: 2 },
  verifySource: 'agent', verifyCommandsOverride: [],
  roleConnections: { primary: 'conn-ok' },
  roleWarnings: [],
}

const STUBS = { AppShell: { template: '<div><slot name="title" /><slot /></div>' } }

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  ;(api.listWorkspaces as Fn).mockResolvedValue({ ok: true, workspaces: [WS], activeId: 'ws1' })
  ;(api.updateWorkspace as Fn).mockResolvedValue({ ok: true, workspace: WS })
  ;(api.getConfig as Fn).mockResolvedValue({ effective: {}, overrides: {} })
  ;(api.getClis as Fn).mockResolvedValue({
    ok: true,
    clis: {
      claude: { installed: true, version: '2.1.140', auth: {} },
      opencode: { installed: true, version: '1.16.2', auth: { providers: [] } },
      codex: { installed: true, version: '0.125.0', auth: {} },
    },
  })
  ;(api.getConnectionPresets as Fn).mockResolvedValue({
    catalog: [{
      provider: 'deepseek', label: 'DeepSeek', blurb: 'DeepSeek API key',
      combos: [{ engine: 'claude', authMethod: 'api_key', models: ['deepseek-chat'] }],
    }],
  })
  ;(api.getConnections as Fn).mockResolvedValue({
    connections: [{
      id: 'conn-ok', label: 'DS', provider: 'deepseek', engine: 'claude', authMethod: 'api_key', model: 'deepseek-chat',
      env: {}, status: 'connected',
    }],
  })
  ;(api.listIntegrations as Fn).mockResolvedValue({
    ok: true,
    default: 'github',
    providers: [{ name: 'github', available: true, capabilities: { issues: true, pullRequests: true } }],
  })
})

describe('SettingsView connections integration', () => {
  it('renders ConnectionsManager and IntegrationsPanel', async () => {
    const w = mount(SettingsView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    // ConnectionsManager — its add-form provider select
    expect(w.find('[data-test="conn-provider"]').exists()).toBe(true)
    // IntegrationsPanel — its github provider row appears after mount
    expect(w.find('[data-test="provider-github"]').exists()).toBe(true)
    w.unmount()
  })

  it('does NOT render the removed raw engine editor', async () => {
    const w = mount(SettingsView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    expect(w.find('[data-test="engine"]').exists()).toBe(false)
    expect(w.find('[data-test="engine-env"]').exists()).toBe(false)
    expect(w.find('[data-test="add-profile"]').exists()).toBe(false)
    w.unmount()
  })

  it('no longer renders the roles block (moved to AgentsRunView)', async () => {
    const w = mount(SettingsView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    expect(w.find('[data-test="role-primary"]').exists()).toBe(false)
    expect(w.find('[data-test="save-roles"]').exists()).toBe(false)
    w.unmount()
  })
})
