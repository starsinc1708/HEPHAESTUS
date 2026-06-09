import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import RepoPicker from '../RepoPicker.vue'
import { api } from '@/api/client'

vi.mock('@/api/client', () => ({ api: { browseFs: vi.fn() } }))

type Fn = ReturnType<typeof vi.fn>

const ROOT = {
  ok: true,
  path: '/projects',
  parent: '/',
  entries: [
    { name: 'repo-a', path: '/projects/repo-a', isGitRepo: true },
    { name: 'plain', path: '/projects/plain', isGitRepo: false },
  ],
}

function makeWrapper(modelValue = '') {
  return mount(RepoPicker, { props: { modelValue } })
}

beforeEach(() => {
  vi.clearAllMocks()
  ;(api.browseFs as Fn).mockResolvedValue(ROOT)
})

describe('RepoPicker', () => {
  it('loads the start dir on mount and lists subdirs with a git badge', async () => {
    const w = makeWrapper()
    await flushPromises()
    // Default start is the Docker mount.
    expect(api.browseFs).toHaveBeenCalledWith('/projects')
    expect(w.find('[data-test="rp-path"]').text()).toBe('/projects')
    expect(w.find('[data-test="rp-entry-repo-a"]').exists()).toBe(true)
    expect(w.find('[data-test="rp-entry-plain"]').exists()).toBe(true)
    // The git repo gets a per-row select button; the plain dir does not.
    expect(w.find('[data-test="rp-select-repo-a"]').exists()).toBe(true)
    expect(w.find('[data-test="rp-select-plain"]').exists()).toBe(false)
  })

  it('navigates into a folder when its row is clicked', async () => {
    const w = makeWrapper()
    await flushPromises()
    ;(api.browseFs as Fn).mockResolvedValueOnce({
      ok: true, path: '/projects/plain', parent: '/projects', entries: [],
    })
    await w.find('[data-test="rp-entry-plain"] .rp-name').trigger('click')
    await flushPromises()
    expect(api.browseFs).toHaveBeenLastCalledWith('/projects/plain')
    expect(w.find('[data-test="rp-path"]').text()).toBe('/projects/plain')
    expect(w.find('[data-test="rp-empty"]').exists()).toBe(true)
  })

  it('emits update:modelValue with the repo path when a git repo is selected', async () => {
    const w = makeWrapper()
    await flushPromises()
    await w.find('[data-test="rp-select-repo-a"]').trigger('click')
    expect(w.emitted('update:modelValue')?.[0]).toEqual(['/projects/repo-a'])
  })

  it('emits the current folder when "select this folder" is clicked', async () => {
    const w = makeWrapper()
    await flushPromises()
    await w.find('[data-test="rp-select-current"]').trigger('click')
    expect(w.emitted('update:modelValue')?.[0]).toEqual(['/projects'])
  })

  it('goes up to the parent, and disables "up" at the root', async () => {
    const w = makeWrapper()
    await flushPromises()
    // parent is '/projects' has parent '/', so up is enabled
    const up = w.find('[data-test="rp-up"]')
    expect((up.element as HTMLButtonElement).disabled).toBe(false)

    ;(api.browseFs as Fn).mockResolvedValueOnce({
      ok: true, path: '/', parent: null, entries: [],
    })
    await up.trigger('click')
    await flushPromises()
    expect(api.browseFs).toHaveBeenLastCalledWith('/')
    // At the root, parent is null → up disabled.
    expect((w.find('[data-test="rp-up"]').element as HTMLButtonElement).disabled).toBe(true)
  })

  it('shows an error message when the browse call fails', async () => {
    ;(api.browseFs as Fn).mockRejectedValueOnce(new Error('nope'))
    const w = makeWrapper()
    await flushPromises()
    expect(w.find('[data-test="rp-error"]').exists()).toBe(true)
  })
})
