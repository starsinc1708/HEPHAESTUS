import { describe, it, expect } from 'vitest'
import { renderMarkdown } from '@/utils/markdown'

describe('renderMarkdown', () => {
  it('renders **bold** to <strong>', () => {
    const out = renderMarkdown('**bold**')
    expect(out).toContain('<strong>bold</strong>')
  })

  it('renders a fenced code block to <pre>/<code>', () => {
    const out = renderMarkdown('```js\ncode\n```')
    expect(out).toContain('<pre')
    expect(out).toContain('<code')
  })

  describe('XSS hardening', () => {
    it('strips onerror handlers from raw <img> html', () => {
      const out = renderMarkdown('<img src=x onerror=alert(1)>')
      expect(out).not.toContain('onerror')
    })

    it('strips <script> tags', () => {
      const out = renderMarkdown('<script>alert(1)</script>')
      expect(out).not.toContain('<script')
    })

    it('strips javascript: hrefs', () => {
      const out = renderMarkdown('[x](javascript:alert(1))')
      expect(out).not.toContain('javascript:')
    })
  })

  it('returns empty string for empty input', () => {
    expect(renderMarkdown('')).toBe('')
  })

  it('returns empty string for null input', () => {
    expect(renderMarkdown(null)).toBe('')
  })

  it('returns empty string for undefined input', () => {
    expect(renderMarkdown(undefined)).toBe('')
  })
})
