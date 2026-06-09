import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'

// markdown-it renders the (untrusted, LLM-authored) source to HTML; DOMPurify is the
// single authoritative XSS gate on the rendered output. We deliberately enable
// html:true so that any raw HTML the model emits reaches DOMPurify as *real* nodes
// (which it neutralizes — stripping onerror=, <script>, etc.) rather than being
// pre-escaped by markdown-it into inert-but-still-visible literal text. validateLink
// is widened to true for the same reason: it lets markdown-it emit links like
// [x](javascript:alert(1)) as <a href="javascript:…">, which DOMPurify then strips the
// dangerous href from — instead of markdown-it silently leaving the literal
// "javascript:…" text in place. DOMPurify (jsdom in tests, the real DOM in the browser)
// removes event handlers, <script>/<iframe>/etc., and javascript:/data: URLs.
const md: MarkdownIt = new MarkdownIt({ html: true, linkify: true, breaks: true })
md.validateLink = () => true

// Defence-in-depth: any link the model emits with target="_blank" gets
// rel="noopener noreferrer" so the opened page can't reach back via window.opener.
DOMPurify.addHook('afterSanitizeAttributes', (node: Element) => {
  if (node.tagName === 'A' && node.getAttribute('target') === '_blank') {
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

export function renderMarkdown(src: string | null | undefined): string {
  if (!src) return ''
  const rawHtml = md.render(src)
  return DOMPurify.sanitize(rawHtml)
}
