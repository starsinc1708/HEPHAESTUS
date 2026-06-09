import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import AgentListEditor from '../AgentListEditor.vue'
import type { AgentRef } from '@/types/api'

const refs = (): AgentRef[] => [
  { provider: 'a', model: '1', agent: null },
  { provider: 'a', model: '2', agent: null },
]
const last = (w: ReturnType<typeof mount>) =>
  w.emitted('update:modelValue')!.at(-1)![0] as AgentRef[]

describe('AgentListEditor', () => {
  it('renders one editor row per ref', () => {
    const w = mount(AgentListEditor, { props: { modelValue: refs(), useModels: true } })
    expect(w.findAll('[data-test="agent-ref"]')).toHaveLength(2)
  })

  it('add emits a longer list', async () => {
    const w = mount(AgentListEditor, { props: { modelValue: refs(), useModels: true } })
    await w.find('[data-test="al-add"]').trigger('click')
    expect(last(w)).toHaveLength(3)
  })

  it('remove emits a shorter list', async () => {
    const w = mount(AgentListEditor, { props: { modelValue: refs(), useModels: true } })
    await w.findAll('[data-test="al-remove"]')[0].trigger('click')
    expect(last(w)).toHaveLength(1)
  })

  it('fill-all copies the first row to all', async () => {
    const w = mount(AgentListEditor, { props: { modelValue: refs(), useModels: true } })
    await w.find('[data-test="al-fill"]').trigger('click')
    expect(last(w)[1].model).toBe('1')
  })
})
