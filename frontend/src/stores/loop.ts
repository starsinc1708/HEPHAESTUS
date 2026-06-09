import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { LoopStatus, ProcessManagerStatus, DriverStatus } from '@/types/api'
import { api } from '@/api/client'
import { useWebSocket } from '@/composables/useWebSocket'

export const useLoopStore = defineStore('loop', () => {
  const status = ref<LoopStatus>({
    process: { state: 'idle', pid: null, children: [] },
    tmux: false, driver_pid: null, opencode_pids: [],
  })
  const driver = ref<DriverStatus>({
    process: { state: 'idle', pid: null, children: [] },
    tmux: false, driver_pid: null, opencode_pids: [],
    runSummary: null, paused: false, queued: 0, inProgress: 0,
  })
  const killswitchPresent = ref(false)
  const loading = ref(false)
  let _timer: ReturnType<typeof setInterval> | null = null
  let _ws: ReturnType<typeof useWebSocket> | null = null

  async function pollLoop() {
    try {
      loading.value = true
      const state = await api.getState()
      const ls = state.loopStatus
      const ps = ls.process ?? { state: 'idle' as const, pid: null as null, children: [] as number[] }
      status.value = {
        process: {
          state: (ps.state as ProcessManagerStatus['state']) ?? 'idle',
          pid: ps.pid ?? ls.driver_pid ?? null,
          children: ps.children ?? ls.opencode_pids ?? [],
        },
        tmux: ls.tmux,
        driver_pid: ls.driver_pid,
        opencode_pids: ls.opencode_pids,
      }
      killswitchPresent.value = false
    } catch {
      // silent
    } finally {
      loading.value = false
    }
  }

  async function pollDriver() {
    try {
      driver.value = await api.driverStatus()
    } catch {
      // silent — keep last known driver status
    }
  }

  async function pauseDriver() {
    await api.driverPause()
    await pollDriver()
  }

  async function resumeDriver() {
    await api.driverResume()
    await pollDriver()
  }

  async function startDriver(opts?: Record<string, unknown>) {
    await api.driverStart(opts)
    await pollLoop()
  }

  async function stopDriver() {
    await api.driverStop()
    killswitchPresent.value = true
    await pollLoop()
  }

  async function killDriver() {
    await api.driverKill()
    await pollLoop()
  }

  function startPolling(interval = 3000) {
    stopPolling()
    // Subscribe to WebSocket push for real-time state notifications
    _ws = useWebSocket()
    _ws.connect('board', () => {
      // On any state update, refresh loop/driver status from HTTP
      void pollLoop()
      void pollDriver()
    })
    void pollLoop()
    void pollDriver()
    _timer = setInterval(() => {
      void pollLoop()
      void pollDriver()
    }, interval)
  }

  function stopPolling() {
    if (_timer !== null) {
      clearInterval(_timer)
      _timer = null
    }
    if (_ws) {
      _ws.disconnect()
      _ws = null
    }
  }

  return {
    status, driver, killswitchPresent, loading,
    pollLoop, pollDriver, pauseDriver, resumeDriver,
    startDriver, stopDriver, killDriver,
    startPolling, stopPolling,
  }
})
