import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import LangToggle from '@/components/LangToggle.vue'
import { i18n } from '@/i18n'

beforeEach(() => {
  localStorage.clear()
  ;(i18n.global.locale as unknown as { value: string }).value = 'ru'
})

describe('LangToggle (UI-001)', () => {
  it('marks the active locale and switches on click', async () => {
    const w = mount(LangToggle)
    expect(w.find('[data-test="lang-ru"]').classes()).toContain('active')
    expect(w.find('[data-test="lang-en"]').classes()).not.toContain('active')

    await w.find('[data-test="lang-en"]').trigger('click')
    expect((i18n.global.locale as unknown as { value: string }).value).toBe('en')
    expect(w.find('[data-test="lang-en"]').classes()).toContain('active')
    expect(localStorage.getItem('hephaestus.locale')).toBe('en')
  })

  it('switches back to ru', async () => {
    ;(i18n.global.locale as unknown as { value: string }).value = 'en'
    const w = mount(LangToggle)
    await w.find('[data-test="lang-ru"]').trigger('click')
    expect((i18n.global.locale as unknown as { value: string }).value).toBe('ru')
    expect(localStorage.getItem('hephaestus.locale')).toBe('ru')
  })
})
