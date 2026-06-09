// UI-001: i18n infrastructure (en/ru). vue-i18n in Composition mode (legacy: false).
//
// Default locale is Russian (the app shipped Russian-only), persisted in
// localStorage so the choice survives reloads. English falls back for any key
// not yet translated. Switch the language with setLocale().
import { createI18n } from 'vue-i18n'
import en from './locales/en'
import ru from './locales/ru'

export type Locale = 'ru' | 'en'

const STORAGE_KEY = 'hephaestus.locale'
const DEFAULT_LOCALE: Locale = 'ru'

export function savedLocale(): Locale {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return v === 'en' || v === 'ru' ? v : DEFAULT_LOCALE
  } catch {
    return DEFAULT_LOCALE
  }
}

/**
 * Slavic plural selector for Russian. Returns the index into a pipe-separated
 * message. Supports both 3-form catalogs (one | few | many) and 4-form catalogs
 * with an explicit zero form (zero | one | few | many) — the offset adapts to
 * `choicesLength`, so e.g. 1/21/31 -> "one", 2-4/22-24 -> "few", 5-20/11-14 ->
 * "many". Exported for direct unit testing.
 */
export function russianPlural(choice: number, choicesLength: number): number {
  const n = Math.abs(choice)
  const teen = n % 100 >= 11 && n % 100 <= 14
  const last = n % 10
  // 4-form catalogs carry a dedicated zero form at index 0.
  if (choicesLength >= 4 && choice === 0) return 0
  const one = choicesLength >= 4 ? 1 : 0 // index of the "one" form
  if (!teen && last === 1) return one
  if (!teen && last >= 2 && last <= 4) return one + 1
  return one + 2
}

export const i18n = createI18n({
  legacy: false,
  globalInjection: true,
  locale: savedLocale(),
  fallbackLocale: 'en',
  messages: { ru, en },
  pluralRules: { ru: russianPlural },
})

export function setLocale(locale: Locale): void {
  // i18n.global.locale is a WritableComputedRef in Composition mode.
  ;(i18n.global.locale as unknown as { value: Locale }).value = locale
  try {
    localStorage.setItem(STORAGE_KEY, locale)
  } catch {
    /* private mode / disabled storage — locale still applies for the session */
  }
  try {
    document.documentElement.lang = locale
  } catch {
    /* no document (SSR/tests) */
  }
}
