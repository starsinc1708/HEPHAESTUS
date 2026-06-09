import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { i18n, savedLocale } from './i18n'
import './styles/tokens.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(i18n)
// Reflect the persisted locale on <html lang> for a11y / native UI hints.
try { document.documentElement.lang = savedLocale() } catch { /* no document */ }

// UI-003: Global error handler — logs + toast, prevents app crash
app.config.errorHandler = (err, vm, info) => {
  console.error('[HEPHAESTUS]', err, { component: vm?.$options?.name, info })
  // Import toast lazily to avoid circular deps at module init
  import('./stores/toast').then(({ useToastStore }) => {
    const toast = useToastStore()
    const msg = err instanceof Error ? err.message : String(err)
    toast.add('error', msg, 8000)
  }).catch(() => {
    // Toast itself failed — nothing more we can do
  })
}

app.mount('#app')
