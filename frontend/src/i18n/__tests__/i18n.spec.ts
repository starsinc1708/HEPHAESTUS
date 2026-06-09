import { describe, it, expect, beforeEach } from 'vitest'
import { i18n, setLocale, savedLocale, russianPlural } from '@/i18n'
import ru from '@/i18n/locales/ru'
import en from '@/i18n/locales/en'

const t = (key: string, named?: Record<string, unknown>) =>
  i18n.global.t(key, named ?? {})

beforeEach(() => {
  localStorage.clear()
  ;(i18n.global.locale as unknown as { value: string }).value = 'ru'
})

describe('i18n infrastructure (UI-001)', () => {
  it('defaults to Russian copy', () => {
    expect(t('nav.board')).toBe('Доска')
    expect(t('wizard.done')).toBe('Готово')
  })

  it('switches to English when the locale changes', () => {
    setLocale('en')
    expect(t('nav.board')).toBe('Board')
    expect(t('wizard.done')).toBe('Done')
  })

  it('persists the chosen locale to localStorage and savedLocale reads it back', () => {
    setLocale('en')
    expect(localStorage.getItem('hephaestus.locale')).toBe('en')
    expect(savedLocale()).toBe('en')
    setLocale('ru')
    expect(savedLocale()).toBe('ru')
  })

  it('savedLocale falls back to ru for missing/garbage values', () => {
    localStorage.clear()
    expect(savedLocale()).toBe('ru')
    localStorage.setItem('hephaestus.locale', 'fr')
    expect(savedLocale()).toBe('ru')
  })

  it('interpolates named params', () => {
    expect(t('shell.progressDone', { pct: 42 })).toBe('42% выполнено')
    expect(t('wizard.repoAdded', { name: 'hephaestus' })).toBe('Репозиторий добавлен: hephaestus')
  })

  it('ru and en catalogs have identical key structures', () => {
    const keys = (o: object, prefix = ''): string[] =>
      Object.entries(o).flatMap(([k, v]) =>
        v && typeof v === 'object' ? keys(v, `${prefix}${k}.`) : [`${prefix}${k}`],
      )
    expect(keys(ru).sort()).toEqual(keys(en).sort())
  })
})

describe('russianPlural rule', () => {
  // 4-form catalog: zero | one | few | many  →  indices 0 | 1 | 2 | 3
  const cases: [number, number][] = [
    [0, 0],
    [1, 1], [21, 1], [101, 1],
    [2, 2], [3, 2], [4, 2], [22, 2], [24, 2],
    [5, 3], [10, 3], [11, 3], [12, 3], [14, 3], [25, 3], [100, 3],
  ]
  for (const [n, idx] of cases) {
    it(`maps ${n} -> form ${idx}`, () => {
      expect(russianPlural(n, 4)).toBe(idx)
    })
  }

  it('renders the right Russian form through the catalog', () => {
    // vue-i18n selects the plural form from the numeric 2nd arg; {n} is the count.
    const tc = (n: number) => i18n.global.t('units.tasks', n)
    expect(tc(1)).toBe('1 задача')
    expect(tc(3)).toBe('3 задачи')
    expect(tc(5)).toBe('5 задач')
    expect(tc(11)).toBe('11 задач')
    expect(tc(21)).toBe('21 задача')
  })
})
