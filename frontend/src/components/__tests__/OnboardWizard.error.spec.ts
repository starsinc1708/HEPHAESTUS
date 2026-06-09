import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import OnboardWizard from '../OnboardWizard.vue'
import type { Connection } from '@/types/api'

// Mock API client
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

// Import the mocked api
import { api } from '@/api/client'

type Fn = ReturnType<typeof vi.fn>

const STUBS = { ConnectionsManager: { template: '<div data-test="conn-stub" />' } }

const CONNECTED: Connection = {
  id: 'conn-ok', label: 'DS', provider: 'deepseek', engine: 'claude',
  authMethod: 'api_key', model: 'deepseek-chat', env: {}, status: 'connected',
}

function makeWrapper() {
  return mount(OnboardWizard, {
    props: { connections: [CONNECTED] },
    global: { plugins: [createPinia()], stubs: STUBS },
  })
}

describe('UI-004: OnboardWizard CLI detection error feedback', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    vi.clearAllMocks()
    // Default: other API calls succeed silently
    ;(api.getConnections as Fn).mockResolvedValue({ connections: [] })
    ;(api.listWorkspaces as Fn).mockResolvedValue({ ok: true, workspaces: [], activeId: null })
  })

  it('shows error feedback when CLI detection fails', async () => {
    vi.mocked(api.getClis).mockRejectedValue(new Error('Network error'))

    const wrapper = makeWrapper()
    await flushPromises()

    // Navigate to step 2 (triggers loadClis)
    await wrapper.find('[data-test="wiz-next-1"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="wiz-cli-error"]').exists()).toBe(true)
  })

  it('shows retry button on error', async () => {
    vi.mocked(api.getClis).mockRejectedValue(new Error('Network error'))

    const wrapper = makeWrapper()
    await flushPromises()

    await wrapper.find('[data-test="wiz-next-1"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="wiz-cli-retry"]').exists()).toBe(true)
  })

  it('retries CLI detection on retry button click', async () => {
    vi.mocked(api.getClis)
      .mockRejectedValueOnce(new Error('Network error'))
      .mockResolvedValueOnce({ ok: true, clis: { claude: { installed: true, version: '1.0', auth: {} } } })

    const wrapper = makeWrapper()
    await flushPromises()

    await wrapper.find('[data-test="wiz-next-1"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="wiz-cli-error"]').exists()).toBe(true)

    // Click retry
    await wrapper.find('[data-test="wiz-cli-retry"]').trigger('click')
    await flushPromises()

    // Error banner should disappear after successful retry
    expect(wrapper.find('[data-test="wiz-cli-error"]').exists()).toBe(false)
    expect(api.getClis).toHaveBeenCalledTimes(2)
  })
})
