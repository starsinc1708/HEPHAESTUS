import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import AgentRefEditor from '../AgentRefEditor.vue'
import type { AgentRef } from '@/types/api'

describe('AgentRefEditor', () => {
  it('omo mode shows the agent field, hides provider/model', () => {
    const w = mount(AgentRefEditor, {
      props: { modelValue: { provider: 'p', model: 'm', agent: 'sisyphus' }, useModels: false },
    })
    expect(w.find('[data-test="ar-agent"]').exists()).toBe(true)
    expect(w.find('[data-test="ar-provider"]').exists()).toBe(false)
    expect((w.find('[data-test="ar-agent"]').element as HTMLInputElement).value).toBe('sisyphus')
  })

  it('models mode shows provider + model, hides agent', () => {
    const w = mount(AgentRefEditor, {
      props: { modelValue: { provider: 'anthropic', model: 'opus', agent: null }, useModels: true },
    })
    expect(w.find('[data-test="ar-provider"]').exists()).toBe(true)
    expect(w.find('[data-test="ar-model"]').exists()).toBe(true)
    expect(w.find('[data-test="ar-agent"]').exists()).toBe(false)
  })

  it('modelOnly mode shows only the model field (Claude engine)', () => {
    const w = mount(AgentRefEditor, {
      props: { modelValue: { provider: 'p', model: 'sonnet', agent: 'x' }, useModels: false, modelOnly: true },
    })
    expect(w.find('[data-test="ar-model"]').exists()).toBe(true)
    expect(w.find('[data-test="ar-provider"]').exists()).toBe(false)
    expect(w.find('[data-test="ar-agent"]').exists()).toBe(false)
  })

  it('emits update:modelValue on input', async () => {
    const w = mount(AgentRefEditor, {
      props: { modelValue: { provider: 'a', model: 'b', agent: null }, useModels: true },
    })
    await w.find('[data-test="ar-model"]').setValue('new-model')
    const ev = w.emitted('update:modelValue')
    expect(ev).toBeTruthy()
    expect((ev!.at(-1)![0] as AgentRef).model).toBe('new-model')
  })
})
