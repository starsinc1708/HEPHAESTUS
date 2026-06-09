import { onMounted, onUnmounted } from 'vue'

// UI-006: power-user keyboard shortcuts.
//
// A shortcut is a single key plus a handler. The composable owns the global
// keydown listener (and its cleanup) and enforces two universal rules so
// shortcuts never fight the browser or text entry:
//   1. Modifier chords (Ctrl/Meta/Alt) are ignored — those belong to the
//      browser/OS (Ctrl+R, Cmd+L, …).
//   2. While the user is typing in an input/textarea/select/contentEditable,
//      only shortcuts marked `allowInInput` fire (e.g. Escape to blur).
//
// The same `ShortcutDef[]` drives both the listener and the help overlay, so
// the documented keys can never drift from the wired ones.

export interface ShortcutDef {
  /** `KeyboardEvent.key` to match (letters compared case-insensitively). */
  key: string
  /** Human label shown verbatim in the help overlay (e.g. "?" or "Esc"). */
  display: string
  /** What the shortcut does — shown in the help overlay. */
  description: string
  handler: (e: KeyboardEvent) => void
  /** Fire even while a text field is focused. Default false. */
  allowInInput?: boolean
}

function isEditable(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable
}

/**
 * Match a keydown event against a shortcut list and run the first hit.
 * Exported (not just used internally) so it can be unit-tested without a
 * mounted component or a real `window`.
 */
export function matchShortcut(e: KeyboardEvent, shortcuts: ShortcutDef[]): ShortcutDef | null {
  if (e.ctrlKey || e.metaKey || e.altKey) return null
  const editable = isEditable(e.target)
  for (const s of shortcuts) {
    if (s.key.toLowerCase() !== e.key.toLowerCase()) continue
    if (editable && !s.allowInInput) continue
    return s
  }
  return null
}

export function useKeyboardShortcuts(shortcuts: ShortcutDef[]): void {
  function onKeydown(e: KeyboardEvent): void {
    const hit = matchShortcut(e, shortcuts)
    if (!hit) return
    e.preventDefault()
    hit.handler(e)
  }
  onMounted(() => window.addEventListener('keydown', onKeydown))
  onUnmounted(() => window.removeEventListener('keydown', onKeydown))
}
