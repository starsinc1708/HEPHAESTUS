import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ConversationTree from '../ConversationTree.vue'
import type { ConversationIteration, ConversationAgentRun } from '@/types/api'

const DIR = 'iter-20260608-120000'

function fixture(): ConversationIteration[] {
  return [
    {
      dir: DIR,
      createdAt: '2026-06-08T12:00:00Z',
      attempts: 2,
      stages: [
        {
          stage: 'implement',
          agents: [
            {
              stream: 'output.primary.r0', role: 'implementer', revision: 0,
              current: false, model: 'sonnet', status: 'needs_revision',
              messages: 12, costUsd: 0.04,
            },
            {
              stream: 'output.primary', role: 'implementer', revision: 1,
              current: true, model: 'sonnet', status: 'done',
              messages: 18, costUsd: 0.07,
            },
          ],
        },
        {
          stage: 'validate',
          agents: [
            {
              stream: 'validation/layer1/correctness', role: 'validator:correctness',
              revision: 1, current: false, model: 'haiku', status: 'approve',
              messages: 4, costUsd: 0.01,
            },
            {
              stream: 'validation/layer3/final', role: 'final', revision: 1,
              current: false, model: null, status: 'pass', messages: 2, costUsd: 0.005,
            },
          ],
        },
      ],
    },
  ]
}

describe('ConversationTree', () => {
  it('renders the tree root and one row per agent', () => {
    const w = mount(ConversationTree, {
      props: { iterations: fixture(), selectedKey: null },
    })
    expect(w.find('[data-test="conv-tree"]').exists()).toBe(true)
    expect(w.findAll('[data-test^="conv-agent-"]')).toHaveLength(4)
  })

  it('renders rows whose stream contains dots and slashes', () => {
    const w = mount(ConversationTree, {
      props: { iterations: fixture(), selectedKey: null },
    })
    expect(w.find('[data-test="conv-agent-output.primary"]').exists()).toBe(true)
    expect(w.find('[data-test="conv-agent-validation/layer1/correctness"]').exists()).toBe(true)
  })

  it('emits select once with { dir, agent } on click', async () => {
    const w = mount(ConversationTree, {
      props: { iterations: fixture(), selectedKey: null },
    })
    await w.find('[data-test="conv-agent-output.primary"]').trigger('click')
    const events = w.emitted('select')!
    expect(events).toHaveLength(1)
    const payload = events[0][0] as { dir: string; agent: ConversationAgentRun }
    expect(payload.dir).toBe(DIR)
    expect(payload.agent.stream).toBe('output.primary')
  })

  it('emits select on Enter key', async () => {
    const w = mount(ConversationTree, {
      props: { iterations: fixture(), selectedKey: null },
    })
    await w.find('[data-test="conv-agent-output.primary"]').trigger('keydown.enter')
    expect(w.emitted('select')).toHaveLength(1)
  })

  it('marks only the selected row', () => {
    const w = mount(ConversationTree, {
      props: { iterations: fixture(), selectedKey: `${DIR}::output.primary` },
    })
    expect(w.find('[data-test="conv-agent-output.primary"]').classes()).toContain('selected')
    expect(w.find('[data-test="conv-agent-output.primary.r0"]').classes()).not.toContain('selected')
    expect(w.find('[data-test="conv-agent-validation/layer1/correctness"]').classes()).not.toContain('selected')
  })

  it('humanizes roles', () => {
    const w = mount(ConversationTree, {
      props: { iterations: fixture(), selectedKey: null },
    })
    expect(w.find('[data-test="conv-agent-validation/layer1/correctness"]').text()).toContain('correctness')
    expect(w.find('[data-test="conv-agent-validation/layer3/final"]').text()).toContain('Финал')
  })

  it('shows an empty message and zero rows when there are no iterations', () => {
    const w = mount(ConversationTree, {
      props: { iterations: [], selectedKey: null },
    })
    expect(w.find('[data-test="conv-tree"]').exists()).toBe(true)
    expect(w.findAll('[data-test^="conv-agent-"]')).toHaveLength(0)
    expect(w.text()).toContain('Нет переписок')
  })
})
