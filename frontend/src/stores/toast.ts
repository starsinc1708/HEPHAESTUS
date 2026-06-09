import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Toast, ToastKind } from '@/types/api'

let _nextId = 1

export const useToastStore = defineStore('toast', () => {
  const toasts = ref<Toast[]>([])

  function add(kind: ToastKind, message: string, ttl?: number, undoAction?: () => void) {
    const effectiveTtl = ttl ?? (undoAction ? 10_000 : 5_000)
    const id = _nextId++
    const t: Toast = { id, kind, message, createdAt: Date.now(), undoAction }
    toasts.value.push(t)
    if (effectiveTtl > 0) {
      setTimeout(() => dismiss(id), effectiveTtl)
    }
  }

  function dismiss(id: number) {
    const idx = toasts.value.findIndex(t => t.id === id)
    if (idx !== -1) toasts.value.splice(idx, 1)
  }

  function undo(id: number) {
    const t = toasts.value.find(t => t.id === id)
    if (t?.undoAction) {
      t.undoAction()
    }
    dismiss(id)
  }

  return { toasts, add, dismiss, undo }
})
