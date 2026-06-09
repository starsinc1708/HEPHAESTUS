/**
 * WebSocket composable for subscribing to HEPHAESTUS backend rooms.
 *
 * When connected: state arrives via push. When disconnected:
 * the caller's fallback polling kicks in. On reconnect, one full
 * fetchState is issued to catch any missed updates.
 */

import { ref, onUnmounted } from 'vue'
import type { StateSnapshot } from '@/types/api'
import { api } from '@/api/client'

export interface WsClient {
  isConnected: import('vue').Ref<boolean>
  connect: (room: string, onStateUpdate: (state: StateSnapshot) => void) => void
  disconnect: () => void
}

export function useWebSocket(): WsClient {
  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let stateHandler: ((state: StateSnapshot) => void) | null = null
  let intentionalClose = false

  const isConnected = ref(false)

  function connect(room: string, onStateUpdate: (state: StateSnapshot) => void) {
    stateHandler = onStateUpdate
    intentionalClose = false
    _connect(room)
  }

  function _connect(room: string) {
    if (ws) {
      ws.onclose = null
      ws.onerror = null
      ws.onmessage = null
      ws.close()
      ws = null
    }

    try {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const url = `${protocol}//${window.location.host}/ws/${room}`
      ws = new WebSocket(url)

      ws.onopen = () => {
        isConnected.value = true
        // On reconnect: do one full fetchState to catch missed updates
        if (stateHandler) {
          api.getState().then(stateHandler).catch(() => {})
        }
      }

      ws.onmessage = (event: MessageEvent) => {
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === 'state_update' && msg.data && stateHandler) {
            stateHandler(msg.data)
          }
          // Ping/heartbeat messages are silently ignored
        } catch {
          // Malformed message — ignore
        }
      }

      ws.onclose = () => {
        isConnected.value = false
        ws = null
        if (!intentionalClose) {
          reconnectTimer = setTimeout(() => _connect(room), 3000)
        }
      }

      ws.onerror = () => {
        // onclose fires immediately after onerror
      }
    } catch {
      isConnected.value = false
    }
  }

  function disconnect() {
    intentionalClose = true
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws) {
      ws.onclose = null
      ws.close()
      ws = null
    }
    isConnected.value = false
  }

  onUnmounted(() => {
    disconnect()
  })

  return { isConnected, connect, disconnect }
}
