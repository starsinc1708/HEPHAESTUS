import { describe, it, expect, vi } from 'vitest'
import { matchShortcut, type ShortcutDef } from '@/composables/useKeyboardShortcuts'

function ev(init: Partial<KeyboardEvent> & { key: string }): KeyboardEvent {
  // jsdom KeyboardEvent doesn't let us set `target` via the ctor, so stub it.
  const e = new KeyboardEvent('keydown', init)
  if ('target' in init) Object.defineProperty(e, 'target', { value: init.target, configurable: true })
  return e
}

function defs(): ShortcutDef[] {
  return [
    { key: 'j', display: 'j', description: 'next', handler: vi.fn() },
    { key: '/', display: '/', description: 'search', handler: vi.fn() },
    { key: 'Escape', display: 'Esc', description: 'close', handler: vi.fn(), allowInInput: true },
  ]
}

describe('matchShortcut', () => {
  it('matches a plain key', () => {
    const s = defs()
    expect(matchShortcut(ev({ key: 'j' }), s)).toBe(s[0])
  })

  it('is case-insensitive for letters', () => {
    const s = defs()
    expect(matchShortcut(ev({ key: 'J' }), s)).toBe(s[0])
  })

  it('ignores modifier chords (Ctrl/Meta/Alt) so browser shortcuts pass through', () => {
    const s = defs()
    expect(matchShortcut(ev({ key: 'j', ctrlKey: true }), s)).toBeNull()
    expect(matchShortcut(ev({ key: 'j', metaKey: true }), s)).toBeNull()
    expect(matchShortcut(ev({ key: 'j', altKey: true }), s)).toBeNull()
  })

  it('does NOT fire normal shortcuts while typing in an input', () => {
    const s = defs()
    const input = document.createElement('input')
    expect(matchShortcut(ev({ key: 'j', target: input }), s)).toBeNull()
    expect(matchShortcut(ev({ key: '/', target: input }), s)).toBeNull()
  })

  it('still fires allowInInput shortcuts (Escape) while typing', () => {
    const s = defs()
    const input = document.createElement('input')
    expect(matchShortcut(ev({ key: 'Escape', target: input }), s)).toBe(s[2])
  })

  it('treats textarea/select/contentEditable as editable too', () => {
    const s = defs()
    const ta = document.createElement('textarea')
    const sel = document.createElement('select')
    const div = document.createElement('div')
    div.contentEditable = 'true'
    Object.defineProperty(div, 'isContentEditable', { value: true })
    expect(matchShortcut(ev({ key: 'j', target: ta }), s)).toBeNull()
    expect(matchShortcut(ev({ key: 'j', target: sel }), s)).toBeNull()
    expect(matchShortcut(ev({ key: 'j', target: div }), s)).toBeNull()
  })

  it('returns null when nothing matches', () => {
    expect(matchShortcut(ev({ key: 'z' }), defs())).toBeNull()
  })
})
