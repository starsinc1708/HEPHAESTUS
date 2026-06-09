import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import WorktreesView from '../WorktreesView.vue'
import { api } from '@/api/client'
import type { Worktree, MergePreflightResponse } from '@/types/api'

vi.mock('@/api/client', () => ({
  api: {
    listWorktrees: vi.fn(),
    worktreeDiff: vi.fn(),
    getActiveMergeJob: vi.fn(),
    branchAction: vi.fn(),
    createPr: vi.fn(),
  },
}))

vi.mock('@/stores/toast', () => ({ useToastStore: () => ({ add: vi.fn() }) }))

type Fn = ReturnType<typeof vi.fn>

const STUBS = {
  AppShell: { template: '<div><slot name="title" /><slot /></div>' },
  MergeButton: {
    template: '<div class="merge-button-stub" :data-disabled="disabled" :data-branch="branch" />',
    props: ['branch', 'disabled'],
  },
}

function preflight(over: Partial<MergePreflightResponse> = {}): MergePreflightResponse {
  return {
    cleanTree: true,
    verifyGreen: true,
    verifyUnverified: false,
    validationPassed: true,
    loopActive: false,
    baseBranch: 'main',
    conflicts: [],
    ok: true,
    ...over,
  }
}

function fixture(): Worktree[] {
  return [
    {
      branch: 'auto/idea-x-1',
      task: { id: 't1', title: 'Add login form', status: 'done' },
      changedFiles: ['frontend/src/a.ts', 'frontend/src/b.ts'],
      changedCount: 2,
      preflight: preflight(),
      conflictsWith: [
        {
          branch: 'auto/idea-y',
          task: { id: 't2', title: 'Refactor auth', status: 'queued' },
          files: ['frontend/src/a.ts'],
        },
      ],
    },
    {
      branch: 'auto/idea-z',
      task: null,
      changedFiles: ['backend/main.py'],
      changedCount: 1,
      preflight: preflight({ cleanTree: false, ok: false }),
      conflictsWith: [],
    },
  ]
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  ;(api.listWorktrees as Fn).mockResolvedValue({ ok: true, worktrees: fixture() })
  ;(api.getActiveMergeJob as Fn).mockResolvedValue({ ok: true, job: null })
  ;(api.worktreeDiff as Fn).mockResolvedValue('diff --git a/x b/x\n+hello')
  ;(api.branchAction as Fn).mockResolvedValue({ ok: true })
  ;(api.createPr as Fn).mockResolvedValue({ ok: true, url: 'http://pr' })
})

describe('WorktreesView', () => {
  it('renders a row per worktree from the fixture', async () => {
    const w = mount(WorktreesView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()

    expect(w.find('[data-test="worktrees-list"]').exists()).toBe(true)
    const rows = w.findAll('.wt-row')
    expect(rows.length).toBe(2)

    // task title + branch + changedCount visible
    expect(w.text()).toContain('Add login form')
    expect(w.text()).toContain('auto/idea-x-1')
    expect(w.text()).toContain('2 файлов')

    // null-task row shows muted placeholder + still listed/mergeable
    expect(w.text()).toContain('— нет задачи')

    // one MergeButton stub per row
    expect(w.findAll('.merge-button-stub').length).toBe(2)

    // status chip derived from preflight: ok=true → «готов к merge»; cleanTree=false → «дерево не чистое»
    expect(rows[0].find('.tone-green').text()).toBe('готов к merge')
    expect(rows[1].find('.tone-amber').text()).toBe('дерево не чистое')

    w.unmount()
  })

  it('shows the conflict badge only on the overlapping row', async () => {
    const w = mount(WorktreesView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()

    const badges = w.findAll('[data-test="wt-conflict"]')
    expect(badges.length).toBe(1)
    expect(badges[0].text()).toContain('Refactor auth')
    expect(badges[0].text()).toContain('1 файлов')

    w.unmount()
  })

  it('lazy-loads and expands the diff on toggle', async () => {
    const w = mount(WorktreesView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()

    expect(w.find('.diff-block').exists()).toBe(false)
    const toggle = w.findAll('[data-test="wt-diff-toggle"]')[0]
    await toggle.trigger('click')
    await flushPromises()

    expect(api.worktreeDiff).toHaveBeenCalledWith('auto/idea-x-1')
    const pre = w.find('.diff-block')
    expect(pre.exists()).toBe(true)
    expect(pre.text()).toContain('+hello')

    w.unmount()
  })

  it('caches the diff and does not refetch on re-toggle', async () => {
    const w = mount(WorktreesView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()

    const toggle = w.findAll('[data-test="wt-diff-toggle"]')[0]
    await toggle.trigger('click')
    await flushPromises()
    await toggle.trigger('click') // collapse
    await flushPromises()
    await toggle.trigger('click') // expand again
    await flushPromises()

    expect(api.worktreeDiff).toHaveBeenCalledTimes(1)

    w.unmount()
  })

  it('expands shared files when the conflict badge is clicked', async () => {
    const w = mount(WorktreesView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()

    expect(w.find('.conflict-detail').exists()).toBe(false)
    await w.find('[data-test="wt-conflict"]').trigger('click')
    await flushPromises()

    const detail = w.find('.conflict-detail')
    expect(detail.exists()).toBe(true)
    expect(detail.text()).toContain('frontend/src/a.ts')

    w.unmount()
  })

  it('gates other rows when a non-terminal merge job is active', async () => {
    ;(api.getActiveMergeJob as Fn).mockResolvedValue({
      ok: true,
      job: { id: 'j1', branch: 'auto/idea-x-1', baseBranch: 'main', status: 'resolving', conflicts: [], resolvedFiles: [] },
    })

    const w = mount(WorktreesView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()

    const stubs = w.findAll('.merge-button-stub')
    const xStub = stubs.find((s) => s.attributes('data-branch') === 'auto/idea-x-1')!
    const zStub = stubs.find((s) => s.attributes('data-branch') === 'auto/idea-z')!

    // the active row is NOT disabled; the other row IS disabled
    expect(xStub.attributes('data-disabled')).toBe('false')
    expect(zStub.attributes('data-disabled')).toBe('true')

    w.unmount()
  })

  it('does not gate rows for a terminal merge job', async () => {
    ;(api.getActiveMergeJob as Fn).mockResolvedValue({
      ok: true,
      job: { id: 'j1', branch: 'auto/idea-x-1', baseBranch: 'main', status: 'accepted', conflicts: [], resolvedFiles: [] },
    })

    const w = mount(WorktreesView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()

    const stubs = w.findAll('.merge-button-stub')
    for (const s of stubs) {
      expect(s.attributes('data-disabled')).toBe('false')
    }

    w.unmount()
  })

  it('refetches via the manual refresh button', async () => {
    const w = mount(WorktreesView, { attachTo: document.body, global: { stubs: STUBS } })
    await flushPromises()
    ;(api.listWorktrees as Fn).mockClear()

    await w.find('[data-test="wt-refresh"]').trigger('click')
    await flushPromises()

    expect(api.listWorktrees).toHaveBeenCalledTimes(1)

    w.unmount()
  })
})
