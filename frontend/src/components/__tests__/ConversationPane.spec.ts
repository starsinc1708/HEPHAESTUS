import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ConversationPane from '../ConversationPane.vue'
import type { ConversationMessage } from '@/types/api'

function fixture(): ConversationMessage[] {
  return [
    { role: 'user', kind: 'text', text: 'Fix the **bold** bug please' },
    { role: 'assistant', kind: 'thinking', thinking: 'Let me reason about this very carefully step by step.' },
    {
      role: 'assistant',
      kind: 'tool',
      tool: { name: 'bash', input: { command: 'pnpm test' }, output: '12 passed' },
      toolUseId: 'toolu_1',
      tokens: { input: 10, output: 20 },
    },
    { role: 'assistant', kind: 'text', text: 'Done — all tests pass.', tokens: { input: 5, output: 8 } },
    { role: null, kind: 'tool_result', tool: { name: null, input: null, output: 'orphan result payload' } },
  ]
}

describe('ConversationPane', () => {
  it('renders the pane root', () => {
    const w = mount(ConversationPane, { props: { messages: fixture() } })
    expect(w.find('[data-test="conv-pane"]').exists()).toBe(true)
  })

  it('renders a text message through markdown (bold)', () => {
    const w = mount(ConversationPane, {
      props: { messages: [{ role: 'user', kind: 'text', text: 'Fix the **bold** bug' }] },
    })
    const block = w.find('[data-test="msg-text"]')
    expect(block.exists()).toBe(true)
    expect(block.html()).toContain('<strong>bold</strong>')
  })

  it('sanitizes XSS in text messages (no onerror, no javascript:)', () => {
    const w = mount(ConversationPane, {
      props: {
        messages: [
          { role: 'assistant', kind: 'text', text: '<img src=x onerror=alert(1)>\n\n[x](javascript:alert(1))' },
        ],
      },
    })
    const html = w.html()
    expect(html).not.toContain('onerror')
    expect(html).not.toContain('javascript:')
  })

  it('collapses thinking by default and reveals it on toggle', async () => {
    const secret = 'Let me reason about this very carefully step by step.'
    const w = mount(ConversationPane, {
      props: { messages: [{ role: 'assistant', kind: 'thinking', thinking: secret }] },
    })
    const block = w.find('[data-test="msg-thinking"]')
    expect(block.exists()).toBe(true)
    expect(w.find('[data-test="msg-thinking-body"]').exists()).toBe(false)
    await w.find('[data-test="msg-thinking-toggle"]').trigger('click')
    const body = w.find('[data-test="msg-thinking-body"]')
    expect(body.exists()).toBe(true)
    expect(body.text()).toContain(secret)
  })

  it('expands a tool card to reveal input JSON and output', async () => {
    const w = mount(ConversationPane, {
      props: {
        messages: [
          {
            role: 'assistant',
            kind: 'tool',
            tool: { name: 'bash', input: { command: 'pnpm test' }, output: 'ALL GREEN' },
          },
        ],
      },
    })
    const card = w.find('[data-test="msg-tool"]')
    expect(card.exists()).toBe(true)
    expect(card.text()).toContain('bash')
    expect(w.find('[data-test="msg-tool-body"]').exists()).toBe(false)
    await w.find('[data-test="msg-tool-toggle"]').trigger('click')
    const body = w.find('[data-test="msg-tool-body"]')
    expect(body.exists()).toBe(true)
    expect(body.text()).toContain('"command"')
    expect(body.text()).toContain('ALL GREEN')
  })

  it('renders an orphan tool_result as a compact card', () => {
    const w = mount(ConversationPane, {
      props: {
        messages: [{ role: null, kind: 'tool_result', tool: { name: null, input: null, output: 'orphan output' } }],
      },
    })
    const card = w.find('[data-test="msg-tool-result"]')
    expect(card.exists()).toBe(true)
    expect(card.text()).toContain('orphan output')
  })

  it('shows per-message token footer', () => {
    const w = mount(ConversationPane, {
      props: { messages: [{ role: 'assistant', kind: 'text', text: 'hi', tokens: { input: 10, output: 20 } }] },
    })
    const footer = w.find('[data-test="msg-tokens"]')
    expect(footer.exists()).toBe(true)
    expect(footer.text()).toContain('10')
    expect(footer.text()).toContain('20')
  })

  it('shows "Нет сообщений" when empty and not loading', () => {
    const w = mount(ConversationPane, { props: { messages: [], loading: false } })
    expect(w.text()).toContain('Нет сообщений')
  })

  it('shows "Загрузка…" when empty and loading', () => {
    const w = mount(ConversationPane, { props: { messages: [], loading: true } })
    expect(w.text()).toContain('Загрузка…')
  })

  it('shows the title and a streaming indicator', () => {
    const w = mount(ConversationPane, {
      props: { messages: fixture(), title: 'Имплементер r1', streaming: true },
    })
    expect(w.text()).toContain('Имплементер r1')
    expect(w.text()).toContain('агент работает…')
  })

  it('caps rendering at 800 messages and shows a truncation banner', () => {
    const many: ConversationMessage[] = Array.from({ length: 801 }, (_, i) => ({
      role: 'assistant',
      kind: 'text',
      text: `msg ${i}`,
    }))
    const w = mount(ConversationPane, { props: { messages: many } })
    expect(w.find('[data-test="conv-truncated"]').exists()).toBe(true)
    expect(w.findAll('[data-test="msg-text"]')).toHaveLength(800)
  })

  it('renders all message kinds together without error', () => {
    const w = mount(ConversationPane, { props: { messages: fixture() } })
    expect(w.findAll('[data-test="msg-text"]')).toHaveLength(2)
    expect(w.find('[data-test="msg-thinking"]').exists()).toBe(true)
    expect(w.find('[data-test="msg-tool"]').exists()).toBe(true)
    expect(w.find('[data-test="msg-tool-result"]').exists()).toBe(true)
  })
})
