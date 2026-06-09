import { mount, flushPromises } from '@vue/test-utils'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import IntegrationsPanel from '../IntegrationsPanel.vue'

const caps = { issues: true, pullRequests: true }

function provider(over: Record<string, unknown> = {}) {
  return {
    name: 'github',
    available: false,
    connected: false,
    status: 'disconnected',
    hasToken: false,
    token: null,
    host: null,
    lastError: null,
    lastTestedAt: null,
    capabilities: caps,
    ...over,
  }
}

const listIntegrations = vi.fn()
const connectIntegration = vi.fn()
const verifyIntegration = vi.fn()
const disconnectIntegration = vi.fn()

vi.mock('@/api/client', () => ({
  api: {
    listIntegrations: () => listIntegrations(),
    connectIntegration: (n: string, b: unknown) => connectIntegration(n, b),
    verifyIntegration: (n: string) => verifyIntegration(n),
    disconnectIntegration: (n: string) => disconnectIntegration(n),
  },
}))

vi.mock('@/stores/toast', () => ({ useToastStore: () => ({ add: vi.fn() }) }))

function defaultList() {
  return {
    ok: true,
    default: null,
    providers: [
      provider({ name: 'github', connected: true, hasToken: true, available: true, status: 'connected', token: 'ghp***ab' }),
      provider({ name: 'gitlab', host: 'https://gitlab.com' }),
    ],
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  listIntegrations.mockResolvedValue(defaultList())
})

describe('IntegrationsPanel', () => {
  it('renders github + gitlab cards', async () => {
    const w = mount(IntegrationsPanel)
    await flushPromises()
    expect(w.find('[data-test="provider-github"]').exists()).toBe(true)
    expect(w.find('[data-test="provider-gitlab"]').exists()).toBe(true)
  })

  it('shows masked token + verify/disconnect for a connected provider', async () => {
    const w = mount(IntegrationsPanel)
    await flushPromises()
    expect(w.find('[data-test="int-token-display-github"]').text()).toContain('***')
    expect(w.find('[data-test="int-verify-github"]').exists()).toBe(true)
    expect(w.find('[data-test="int-disconnect-github"]').exists()).toBe(true)
    // No connect form for a connected provider
    expect(w.find('[data-test="int-token-github"]').exists()).toBe(false)
  })

  it('shows a connect form (with GitLab host) for a disconnected provider', async () => {
    const w = mount(IntegrationsPanel)
    await flushPromises()
    expect(w.find('[data-test="int-token-gitlab"]').exists()).toBe(true)
    // GitLab gets a host field; GitHub does not.
    expect(w.find('[data-test="int-host-gitlab"]').exists()).toBe(true)
    expect(w.find('[data-test="int-host-github"]').exists()).toBe(false)
  })

  it('connect sends { token, host } for GitLab', async () => {
    connectIntegration.mockResolvedValue({ ok: true, name: 'gitlab', connected: true, status: 'connected', error: null, token: 'glp***x', host: 'https://gl.example.com' })
    const w = mount(IntegrationsPanel)
    await flushPromises()
    await w.find('[data-test="int-token-gitlab"]').setValue('glpat_secret')
    await w.find('[data-test="int-host-gitlab"]').setValue('https://gl.example.com')
    await w.find('[data-test="int-connect-gitlab"]').trigger('click')
    await flushPromises()
    expect(connectIntegration).toHaveBeenCalledWith('gitlab', {
      token: 'glpat_secret',
      host: 'https://gl.example.com',
    })
  })

  it('connect sends only { token } for GitHub (no host)', async () => {
    listIntegrations.mockResolvedValue({
      ok: true,
      default: null,
      providers: [provider({ name: 'github' }), provider({ name: 'gitlab', host: 'https://gitlab.com' })],
    })
    connectIntegration.mockResolvedValue({ ok: true, name: 'github', connected: true, status: 'connected', error: null, token: 'ghp***x', host: null })
    const w = mount(IntegrationsPanel)
    await flushPromises()
    await w.find('[data-test="int-token-github"]').setValue('ghp_secret')
    await w.find('[data-test="int-connect-github"]').trigger('click')
    await flushPromises()
    expect(connectIntegration).toHaveBeenCalledWith('github', { token: 'ghp_secret' })
  })

  it('connect button is disabled with an empty token', async () => {
    listIntegrations.mockResolvedValue({
      ok: true,
      default: null,
      providers: [provider({ name: 'github' }), provider({ name: 'gitlab', host: 'https://gitlab.com' })],
    })
    const w = mount(IntegrationsPanel)
    await flushPromises()
    expect(w.find('[data-test="int-connect-github"]').attributes('disabled')).toBeDefined()
  })

  it('clears the typed token even when connect fails', async () => {
    listIntegrations.mockResolvedValue({
      ok: true,
      default: null,
      providers: [provider({ name: 'github' }), provider({ name: 'gitlab', host: 'https://gitlab.com' })],
    })
    connectIntegration.mockRejectedValue(new Error('network down'))
    const w = mount(IntegrationsPanel)
    await flushPromises()
    const input = w.find('[data-test="int-token-github"]')
    await input.setValue('ghp_secret')
    await w.find('[data-test="int-connect-github"]').trigger('click')
    await flushPromises()
    // raw token must not linger in the field; button no longer busy
    expect((w.find('[data-test="int-token-github"]').element as HTMLInputElement).value).toBe('')
    expect(w.find('[data-test="int-connect-github"]').attributes('disabled')).toBeDefined() // empty token → disabled
  })

  it('renders both cards even if the API omits one (stub)', async () => {
    listIntegrations.mockResolvedValue({
      ok: true,
      default: null,
      providers: [provider({ name: 'github' })], // gitlab omitted
    })
    const w = mount(IntegrationsPanel)
    await flushPromises()
    expect(w.find('[data-test="provider-github"]').exists()).toBe(true)
    expect(w.find('[data-test="provider-gitlab"]').exists()).toBe(true)
    expect(w.find('[data-test="int-host-gitlab"]').exists()).toBe(true)
  })

  it('verify re-checks the stored token and refetches', async () => {
    verifyIntegration.mockResolvedValue({ ok: true, name: 'github', connected: true, status: 'connected', error: null, token: 'ghp***ab', host: null })
    const w = mount(IntegrationsPanel)
    await flushPromises()
    await w.find('[data-test="int-verify-github"]').trigger('click')
    await flushPromises()
    expect(verifyIntegration).toHaveBeenCalledWith('github')
    expect(listIntegrations).toHaveBeenCalledTimes(2) // initial + after verify
  })

  it('disconnect clears the credential and refetches', async () => {
    disconnectIntegration.mockResolvedValue({ ok: true, name: 'github' })
    const w = mount(IntegrationsPanel)
    await flushPromises()
    await w.find('[data-test="int-disconnect-github"]').trigger('click')
    await flushPromises()
    expect(disconnectIntegration).toHaveBeenCalledWith('github')
    expect(listIntegrations).toHaveBeenCalledTimes(2)
  })

  it('no longer renders autofix/changelog UI', async () => {
    const w = mount(IntegrationsPanel)
    await flushPromises()
    expect(w.find('[data-test="autofix-sync"]').exists()).toBe(false)
    expect(w.find('[data-test="gen-changelog"]').exists()).toBe(false)
    expect(w.find('[data-test="changelog-md"]').exists()).toBe(false)
  })
})
