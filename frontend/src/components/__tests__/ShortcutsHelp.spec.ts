import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ShortcutsHelp from '@/components/ShortcutsHelp.vue'
import type { ShortcutDef } from '@/composables/useKeyboardShortcuts'

const noop = () => {}
const shortcuts: ShortcutDef[] = [
  { key: 'j', display: 'j', description: 'Следующая задача', handler: noop },
  { key: '?', display: '?', description: 'Эта справка', handler: noop },
]

describe('ShortcutsHelp', () => {
  it('renders nothing when closed', () => {
    const w = mount(ShortcutsHelp, { props: { open: false, shortcuts } })
    expect(w.find('[data-test="shortcuts-help"]').exists()).toBe(false)
  })

  it('lists each shortcut key + description when open', () => {
    const w = mount(ShortcutsHelp, { props: { open: true, shortcuts } })
    expect(w.find('[data-test="shortcuts-help"]').exists()).toBe(true)
    const rows = w.findAll('.sh-row')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('j')
    expect(rows[0].text()).toContain('Следующая задача')
  })

  it('emits close on the ✕ button and on backdrop click', async () => {
    const w = mount(ShortcutsHelp, { props: { open: true, shortcuts } })
    await w.find('.sh-close').trigger('click')
    await w.find('[data-test="shortcuts-help"]').trigger('click') // self-click on overlay
    expect(w.emitted('close')).toHaveLength(2)
  })
})
