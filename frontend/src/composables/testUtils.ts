import { createApp, defineComponent } from 'vue'

/**
 * Mount a composable inside a minimal Vue app so lifecycle hooks
 * (onUnmounted etc.) are properly registered.
 * Returns `{ result, app, unmount }`.
 */
export function withSetup<T>(composable: () => T): { result: T; app: ReturnType<typeof createApp>; unmount: () => void } {
  let result!: T
  const app = createApp(
    defineComponent({
      setup() {
        result = composable()
        return () => null
      },
    }),
  )
  const div = document.createElement('div')
  app.mount(div)
  return {
    result,
    app,
    unmount: () => app.unmount(),
  }
}
