import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import ScansPanel from '@/components/ScansPanel.vue'
import { api } from '@/api/client'

vi.mock('@/api/client', () => ({
  api: {
    scanList: vi.fn(),
    scanResults: vi.fn(),
    scansImport: vi.fn(),
  },
}))

vi.mock('@/stores/toast', () => ({ useToastStore: () => ({ add: vi.fn() }) }))

type Fn = ReturnType<typeof vi.fn>

const FINDINGS = [
  { id: 'f1', title: 'Fix NPE', proposal: 'guard the null', category: 'bug', severity: 'high' },
  { id: 'f2', title: 'Add cache', proposal: 'memoize the call', category: 'perf', severity: 'medium' },
]

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  ;(api.scanList as Fn).mockResolvedValue([
    { dir: 'scan-2', phase: 'done', detail: '', n_proposals: 2 },
    { dir: 'scan-1', phase: 'done', detail: '', n_proposals: 0 },
  ])
  ;(api.scanResults as Fn).mockResolvedValue({ ok: true, proposals: FINDINGS, n_unique: 2 })
  ;(api.scansImport as Fn).mockResolvedValue({ ok: true, added: ['f1'], skipped: [] })
})

describe('ScansPanel', () => {
  it('loads the newest importable scan and renders its findings', async () => {
    const w = mount(ScansPanel)
    await flushPromises()

    expect(api.scanList).toHaveBeenCalled()
    // Newest first → scan-2 selected, its results fetched.
    expect(api.scanResults).toHaveBeenCalledWith('scan-2')
    expect(w.findAll('[data-test="finding-card"]').length).toBe(2)
    expect(w.text()).toContain('Fix NPE')
  })

  it('import button is disabled until a finding is selected', async () => {
    const w = mount(ScansPanel)
    await flushPromises()
    expect(w.find('[data-test="scans-import"]').attributes('disabled')).toBeDefined()

    await w.find('[data-test="import-select-f1"]').trigger('click')
    expect(w.find('[data-test="scans-import"]').attributes('disabled')).toBeUndefined()
  })

  it('imports selected finding ids with the selected dirname', async () => {
    const w = mount(ScansPanel)
    await flushPromises()

    await w.find('[data-test="import-select-f1"]').trigger('click')
    await w.find('[data-test="scans-import"]').trigger('click')
    await flushPromises()

    expect(api.scansImport).toHaveBeenCalledWith(['f1'], 'scan-2')
  })

  it('shows an empty message when there are no importable scans', async () => {
    ;(api.scanList as Fn).mockResolvedValue([])
    const w = mount(ScansPanel)
    await flushPromises()
    expect(w.find('[data-test="scans-import"]').exists()).toBe(false)
    expect(w.text()).toContain('Нет завершённых сканирований')
  })
})
