import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { defineComponent } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { useWebSocket, type WsClient } from '@/composables/useWebSocket'
import { api } from '@/api/client'

vi.mock('@/api/client', () => ({ api: { getState: vi.fn() } }))

// Controllable fake WebSocket — the real one isn't available/usable in jsdom, and we need to
// drive open/message/close deterministically to exercise the reconnect + fallback flow.
class FakeWS {
  static instances: FakeWS[] = []
  url: string
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor(url: string) { this.url = url; FakeWS.instances.push(this) }
  close() { /* caller nulls onclose for intentional closes */ }
  open() { this.onopen?.() }
  message(data: unknown) { this.onmessage?.({ data: JSON.stringify(data) }) }
  drop() { this.onclose?.() }   // server-side / network drop (non-intentional)
}

function mountClient(): { client: WsClient; unmount: () => void } {
  let client!: WsClient
  const Comp = defineComponent({ setup() { client = useWebSocket(); return () => null } })
  const w = mount(Comp)
  return { client, unmount: () => w.unmount() }
}

const SNAP = (n: number) => ({ items: [{ id: `s${n}` }], summary: {} } as unknown)

describe('useWebSocket — push + reconnect + fallback', () => {
  beforeEach(() => {
    FakeWS.instances = []
    vi.stubGlobal('WebSocket', FakeWS as unknown as typeof WebSocket)
    vi.useFakeTimers()
    ;(api.getState as ReturnType<typeof vi.fn>).mockReset().mockResolvedValue(SNAP(0))
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('drives connect → message → drop → reconnect → full fetch, ignoring noise', async () => {
    const handler = vi.fn()
    const { client, unmount } = mountClient()
    client.connect('board', handler)

    // 1) connect → onopen → isConnected + one full getState (catch missed updates)
    expect(FakeWS.instances).toHaveLength(1)
    FakeWS.instances[0].open()
    await flushPromises()
    expect(client.isConnected.value).toBe(true)
    expect(api.getState).toHaveBeenCalledTimes(1)
    expect(handler).toHaveBeenCalledWith(SNAP(0))

    // 2) state_update push → handler updated WITHOUT another HTTP fetch
    FakeWS.instances[0].message({ type: 'state_update', data: SNAP(2) })
    expect(handler).toHaveBeenLastCalledWith(SNAP(2))
    expect(api.getState).toHaveBeenCalledTimes(1)

    // 3) noise (ping / malformed) ignored
    FakeWS.instances[0].message({ type: 'ping', ts: 1 })
    FakeWS.instances[0].onmessage?.({ data: '{not json' })
    expect(handler).toHaveBeenCalledTimes(2)

    // 4) drop → isConnected false, reconnect scheduled (fallback polling owned by the store)
    FakeWS.instances[0].drop()
    expect(client.isConnected.value).toBe(false)
    expect(FakeWS.instances).toHaveLength(1)

    // 5) reconnect after the backoff → NEW socket → onopen → another full getState
    ;(api.getState as ReturnType<typeof vi.fn>).mockResolvedValue(SNAP(9))
    vi.advanceTimersByTime(3000)
    expect(FakeWS.instances).toHaveLength(2)
    FakeWS.instances[1].open()
    await flushPromises()
    expect(client.isConnected.value).toBe(true)
    expect(api.getState).toHaveBeenCalledTimes(2)
    expect(handler).toHaveBeenLastCalledWith(SNAP(9))

    unmount()
  })

  it('intentional disconnect does not reconnect', async () => {
    const handler = vi.fn()
    const { client } = mountClient()
    client.connect('board', handler)
    FakeWS.instances[0].open()
    await flushPromises()

    client.disconnect()
    expect(client.isConnected.value).toBe(false)
    vi.advanceTimersByTime(10000)
    expect(FakeWS.instances).toHaveLength(1) // no reconnect socket created
  })
})
