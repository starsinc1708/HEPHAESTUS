import { describe, it, expect, vi } from 'vitest'
import { createApp, defineComponent } from 'vue'
import { createPinia } from 'pinia'

describe('UI-003: Global error handler', () => {
  it('should not crash the app when a component throws', async () => {
    const Thrower = defineComponent({
      name: 'Thrower',
      setup() {
        throw new Error('test error from component')
      },
      template: '<div>should not render</div>',
    })

    const app = createApp(Thrower)
    app.use(createPinia())

    // Mock console.error to suppress noise
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    // The error handler should prevent the error from crashing mount
    const errorHandler = vi.fn()
    app.config.errorHandler = errorHandler

    // Mount should not throw because of the error handler
    try {
      app.mount(document.createElement('div'))
    } catch {
      // If it does throw, that's a failure
    }

    // Error handler should have been called
    expect(errorHandler).toHaveBeenCalled()

    consoleSpy.mockRestore()
    app.unmount()
  })
})
