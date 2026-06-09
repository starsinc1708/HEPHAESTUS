// Vitest global setup. Installs i18n on every @vue/test-utils mount so components
// using $t / useI18n render, and pins the locale to ru before each test (existing
// specs assert Russian copy; without a reset a locale-switching test could leak).
import { beforeEach } from 'vitest'
import { config } from '@vue/test-utils'
import { i18n } from '@/i18n'

config.global.plugins = [...(config.global.plugins ?? []), i18n]

beforeEach(() => {
  ;(i18n.global.locale as unknown as { value: string }).value = 'ru'
})
