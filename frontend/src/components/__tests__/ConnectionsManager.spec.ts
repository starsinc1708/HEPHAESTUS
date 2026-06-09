import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ConnectionsManager from '../ConnectionsManager.vue'
import { api } from '@/api/client'

vi.mock('@/api/client', () => ({
  api: {
    getClis: vi.fn(),
    getConnectionPresets: vi.fn(),
    getConnections: vi.fn(),
    createConnection: vi.fn(),
    deleteConnection: vi.fn(),
    testConnection: vi.fn(),
  },
}))

vi.mock('@/stores/toast', () => ({ useToastStore: () => ({ add: vi.fn() }) }))

type Fn = ReturnType<typeof vi.fn>

// Catalog: anthropic (claude sub + claude api_key), deepseek (claude/opencode api_key),
// glm (claude api_key only), openai (codex sub + codex/opencode api_key).
const CATALOG = [
  {
    provider: 'anthropic', label: 'Claude (Anthropic)', blurb: 'Подписка Claude или ключ.',
    combos: [
      { engine: 'claude', authMethod: 'subscription', models: ['claude-opus-4-5', 'claude-sonnet-4-5'], loginCmd: 'claude   (затем /login)' },
      { engine: 'claude', authMethod: 'api_key', keyEnv: 'ANTHROPIC_API_KEY', models: ['claude-opus-4-5', 'claude-sonnet-4-5'] },
    ],
  },
  {
    provider: 'deepseek', label: 'DeepSeek', blurb: 'DeepSeek API key',
    combos: [
      { engine: 'claude', authMethod: 'api_key', keyEnv: 'ANTHROPIC_AUTH_TOKEN', baseUrl: 'https://api.deepseek.com/anthropic', models: ['deepseek-chat', 'deepseek-reasoner'] },
      { engine: 'opencode', authMethod: 'api_key', keyEnv: 'DEEPSEEK_API_KEY', models: ['deepseek-chat', 'deepseek-reasoner'] },
    ],
  },
  {
    provider: 'glm', label: 'GLM', blurb: 'z.ai coding plan',
    combos: [{ engine: 'claude', authMethod: 'api_key', keyEnv: 'ANTHROPIC_AUTH_TOKEN', baseUrl: 'https://api.z.ai/api/anthropic', models: ['glm-4.6', 'glm-4.5'] }],
  },
  {
    provider: 'openai', label: 'OpenAI / GPT', blurb: 'ChatGPT подписка через codex или ключ.',
    combos: [
      { engine: 'codex', authMethod: 'subscription', models: ['gpt-5-codex', 'gpt-4o'], loginCmd: 'codex login' },
      { engine: 'codex', authMethod: 'api_key', keyEnv: 'OPENAI_API_KEY', models: ['gpt-5-codex', 'gpt-4o'] },
      { engine: 'opencode', authMethod: 'api_key', keyEnv: 'OPENAI_API_KEY', models: ['gpt-4o'] },
    ],
  },
]

const ALL_INSTALLED = {
  claude: { installed: true, version: '2.1.140', auth: {} },
  opencode: { installed: true, version: '1.16.2', auth: { providers: [] } },
  codex: { installed: true, version: '0.125.0', auth: {} },
}

beforeEach(() => {
  vi.clearAllMocks()
  ;(api.getClis as Fn).mockResolvedValue({ ok: true, clis: ALL_INSTALLED })
  ;(api.getConnectionPresets as Fn).mockResolvedValue({ ok: true, catalog: CATALOG })
  ;(api.getConnections as Fn).mockResolvedValue({
    connections: [
      {
        id: 'conn-1', label: 'DS', provider: 'deepseek', engine: 'claude', authMethod: 'api_key', model: 'deepseek-chat',
        env: { ANTHROPIC_AUTH_TOKEN: 'sk-***ef' }, status: 'untested',
      },
      {
        id: 'conn-2', label: 'Claude Max', provider: 'anthropic', engine: 'claude', authMethod: 'subscription',
        model: 'claude-opus-4-5', env: { ANTHROPIC_MODEL: 'claude-opus-4-5' }, status: 'connected',
      },
    ],
  })
  ;(api.createConnection as Fn).mockResolvedValue({ ok: true, connection: { id: 'conn-3' } })
  ;(api.deleteConnection as Fn).mockResolvedValue({ ok: true })
  ;(api.testConnection as Fn).mockResolvedValue({ ok: true, status: 'connected', error: null })
})

describe('ConnectionsManager', () => {
  it('renders the engines panel with installed/missing state from getClis', async () => {
    ;(api.getClis as Fn).mockResolvedValue({
      ok: true,
      clis: {
        claude: { installed: true, version: '2.1.140', auth: {} },
        opencode: { installed: false, version: null, auth: {} },
        codex: { installed: true, version: '0.125.0', auth: {} },
      },
    })
    const w = mount(ConnectionsManager)
    await flushPromises()
    const panel = w.find('[data-test="engines-panel"]')
    expect(panel.exists()).toBe(true)
    expect(w.find('[data-test="engine-claude"]').exists()).toBe(true)
    expect(w.find('[data-test="engine-opencode"]').exists()).toBe(true)
    expect(w.find('[data-test="engine-codex"]').exists()).toBe(true)
    // installed engine shows its version; missing one shows the install hint
    expect(w.find('[data-test="engine-claude"]').text()).toContain('2.1.140')
    expect(w.find('[data-test="engine-opencode"]').text()).toContain('установите')
  })

  it('renders connection rows with status badges from getConnections', async () => {
    const w = mount(ConnectionsManager)
    await flushPromises()
    const rows = w.findAll('[data-test="conn-row"]')
    expect(rows).toHaveLength(2)
    const statuses = w.findAll('[data-test="conn-status"]').map(s => s.text())
    expect(statuses.join(' ')).toContain('untested')
    expect(statuses.join(' ')).toContain('connected')
  })

  it('shows an auth badge: «подписка» for subscription rows, «ключ» for api_key rows', async () => {
    const w = mount(ConnectionsManager)
    await flushPromises()
    const badges = w.findAll('[data-test="conn-auth-badge"]').map(b => b.text())
    expect(badges).toContain('ключ')
    expect(badges).toContain('подписка')
  })

  it('selecting provider=glm limits engine options to those installed AND in the catalog', async () => {
    const w = mount(ConnectionsManager)
    await flushPromises()
    await w.find('[data-test="conn-provider"]').setValue('glm')
    await flushPromises()
    const engineOpts = w.find('[data-test="conn-engine"]').findAll('option')
    expect(engineOpts.map(o => o.element.value)).toEqual(['claude'])
    const modelOpts = w.find('[data-test="conn-model"]').findAll('option')
    expect(modelOpts.map(o => o.element.value)).toEqual(['glm-4.6', 'glm-4.5'])
    expect((w.find('[data-test="conn-model"]').element as HTMLSelectElement).value).toBe('glm-4.6')
  })

  it('engine options exclude CLIs that are not installed', async () => {
    ;(api.getClis as Fn).mockResolvedValue({
      ok: true,
      clis: {
        claude: { installed: true, version: '2.1.140', auth: {} },
        opencode: { installed: false, version: null, auth: {} },
        codex: { installed: true, version: '0.125.0', auth: {} },
      },
    })
    const w = mount(ConnectionsManager)
    await flushPromises()
    // deepseek has claude + opencode combos, but opencode CLI is missing → only claude
    await w.find('[data-test="conn-provider"]').setValue('deepseek')
    await flushPromises()
    const engineOpts = w.find('[data-test="conn-engine"]').findAll('option')
    expect(engineOpts.map(o => o.element.value)).toEqual(['claude'])
  })

  it('shows the provider blurb', async () => {
    const w = mount(ConnectionsManager)
    await flushPromises()
    await w.find('[data-test="conn-provider"]').setValue('glm')
    await flushPromises()
    expect(w.find('[data-test="conn-blurb"]').text()).toContain('z.ai')
  })

  it('subscription auth hides the key input and shows the loginCmd', async () => {
    const w = mount(ConnectionsManager)
    await flushPromises()
    await w.find('[data-test="conn-provider"]').setValue('anthropic')
    await flushPromises()
    await w.find('[data-test="conn-auth"]').setValue('subscription')
    await flushPromises()
    expect(w.find('[data-test="conn-key"]').exists()).toBe(false)
    expect(w.find('[data-test="conn-login-cmd"]').exists()).toBe(true)
    expect(w.find('[data-test="conn-login-cmd"]').text()).toContain('/login')
  })

  it('api_key auth shows the key input and hides the loginCmd', async () => {
    const w = mount(ConnectionsManager)
    await flushPromises()
    await w.find('[data-test="conn-provider"]').setValue('anthropic')
    await flushPromises()
    await w.find('[data-test="conn-auth"]').setValue('api_key')
    await flushPromises()
    expect(w.find('[data-test="conn-key"]').exists()).toBe(true)
    expect(w.find('[data-test="conn-login-cmd"]').exists()).toBe(false)
  })

  it('submits a subscription connection with no key and the right payload', async () => {
    const w = mount(ConnectionsManager)
    await flushPromises()
    await w.find('[data-test="conn-provider"]').setValue('openai')
    await flushPromises()
    await w.find('[data-test="conn-engine"]').setValue('codex')
    await flushPromises()
    await w.find('[data-test="conn-auth"]').setValue('subscription')
    await flushPromises()
    await w.find('[data-test="conn-model"]').setValue('gpt-5-codex')
    // no key field for subscription → submit should be enabled
    await w.find('[data-test="conn-add"]').trigger('click')
    await flushPromises()
    expect(api.createConnection).toHaveBeenCalledWith(
      expect.objectContaining({ provider: 'openai', engine: 'codex', authMethod: 'subscription', model: 'gpt-5-codex' }),
    )
    const payload = (api.createConnection as Fn).mock.calls[0][0]
    expect('key' in payload).toBe(false)  // spec: key OMITTED (not empty) for subscription
  })

  it('submits an api_key connection with provider/engine/authMethod/model/key', async () => {
    const w = mount(ConnectionsManager)
    await flushPromises()
    await w.find('[data-test="conn-provider"]').setValue('deepseek')
    await flushPromises()
    await w.find('[data-test="conn-engine"]').setValue('opencode')
    await flushPromises()
    await w.find('[data-test="conn-auth"]').setValue('api_key')
    await flushPromises()
    await w.find('[data-test="conn-model"]').setValue('deepseek-reasoner')
    await w.find('[data-test="conn-key"]').setValue('sk-secret')
    await w.find('[data-test="conn-add"]').trigger('click')
    await flushPromises()
    expect(api.createConnection).toHaveBeenCalledWith(
      expect.objectContaining({
        provider: 'deepseek', engine: 'opencode', authMethod: 'api_key',
        model: 'deepseek-reasoner', key: 'sk-secret',
      }),
    )
  })

  it('does not submit an api_key connection without a key', async () => {
    const w = mount(ConnectionsManager)
    await flushPromises()
    await w.find('[data-test="conn-provider"]').setValue('deepseek')
    await flushPromises()
    await w.find('[data-test="conn-auth"]').setValue('api_key')
    await flushPromises()
    // key left empty → add button disabled, click is a no-op
    await w.find('[data-test="conn-add"]').trigger('click')
    await flushPromises()
    expect(api.createConnection).not.toHaveBeenCalled()
  })

  it('clicking «Проверить» calls testConnection, shows status, and emits changed', async () => {
    const w = mount(ConnectionsManager)
    await flushPromises()
    await w.find('[data-test="conn-test"]').trigger('click')
    await flushPromises()
    expect(api.testConnection).toHaveBeenCalledWith('conn-1')
    expect(w.emitted('changed')).toBeTruthy()
  })

  it('emits changed even when testConnection rejects', async () => {
    ;(api.testConnection as Fn).mockRejectedValue(new Error('boom'))
    const w = mount(ConnectionsManager)
    await flushPromises()
    await w.find('[data-test="conn-test"]').trigger('click')
    await flushPromises()
    expect(w.emitted('changed')).toBeTruthy()
  })

  it('clicking delete calls deleteConnection and emits changed', async () => {
    const w = mount(ConnectionsManager)
    await flushPromises()
    await w.find('[data-test="conn-del"]').trigger('click')
    await flushPromises()
    expect(api.deleteConnection).toHaveBeenCalledWith('conn-1')
    expect(w.emitted('changed')).toBeTruthy()
  })
})
