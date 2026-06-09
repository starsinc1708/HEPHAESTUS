import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AgentsRunView from '../AgentsRunView.vue'
import AgentRolesPicker from '@/components/AgentRolesPicker.vue'
import { api } from '@/api/client'

vi.mock('@/api/client', () => ({
  api: {
    // workspace store + roles
    listWorkspaces: vi.fn(),
    updateWorkspace: vi.fn(),
    getConnections: vi.fn(),
    // config store (children may pull it; harmless if stubbed)
    getConfig: vi.fn(),
    putConfig: vi.fn(),
    configPreset: vi.fn(),
    // loop / run + running tasks
    getState: vi.fn(),
    driverStop: vi.fn(),
    driverKill: vi.fn(),
    // prompts
    listWsPrompts: vi.fn(),
    getWsPrompt: vi.fn(),
    putWsPrompt: vi.fn(),
    resetWsPrompt: vi.fn(),
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

// Stub AppShell (it would otherwise pull in router/board store) and the three heavy
// section children so the test stays focused on the composition + real roles picker.
const STUBS = {
  AppShell: { template: '<div><slot name="title" /><slot /></div>' },
  AgentsScanConfig: true,
  AgentsRunControls: true,
  AgentsPromptsEditor: true,
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  ;(api.listWorkspaces as Fn).mockResolvedValue({ ok: true, workspaces: [WS], activeId: 'ws1' })
  ;(api.updateWorkspace as Fn).mockResolvedValue({ ok: true, workspace: WS })
  ;(api.getConnections as Fn).mockResolvedValue({
    connections: [{
      id: 'conn-ok', label: 'DS', provider: 'deepseek', engine: 'claude', authMethod: 'api_key',
      model: 'deepseek-chat', env: {}, status: 'connected',
    }],
  })
  ;(api.getConfig as Fn).mockResolvedValue({ effective: {}, overrides: {} })
  ;(api.getState as Fn).mockResolvedValue({
    items: [], summary: {}, current: null, log_tail: [],
    loopStatus: { process: { state: 'idle', pid: null, children: [] }, tmux: false, driver_pid: null, opencode_pids: [] },
    git: {}, updatedAt: '',
  })
  ;(api.listWsPrompts as Fn).mockResolvedValue({ prompts: [] })
})

describe('AgentsRunView composition', () => {
  it('renders the four composed sections', async () => {
    const w = mount(AgentsRunView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    expect(w.find('[data-test="agents-roles"]').exists()).toBe(true)
    expect(w.find('[data-test="agents-scans"]').exists()).toBe(true)
    expect(w.find('[data-test="agents-run"]').exists()).toBe(true)
    expect(w.find('[data-test="agents-prompts"]').exists()).toBe(true)
    w.unmount()
  })

  it('renders the real AgentRolesPicker wired to the loaded connection', async () => {
    const w = mount(AgentsRunView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    // AgentRolesPicker rendered its primary-role select.
    expect(w.find('[data-test="role-primary"]').exists()).toBe(true)
    // The picker received the one connected connection loaded on mount.
    const picker = w.findComponent(AgentRolesPicker)
    expect(picker.props('connections')).toHaveLength(1)
    expect((picker.props('connections') as { id: string }[])[0].id).toBe('conn-ok')
    w.unmount()
  })

  it('saving roles sends roleConnections to updateWorkspace', async () => {
    const w = mount(AgentsRunView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    await w.find('[data-test="save-roles"]').trigger('click')
    await flushPromises()
    expect(api.updateWorkspace).toHaveBeenCalledWith(
      'ws1',
      expect.objectContaining({ roleConnections: expect.objectContaining({ primary: 'conn-ok' }) }),
    )
    w.unmount()
  })
})
