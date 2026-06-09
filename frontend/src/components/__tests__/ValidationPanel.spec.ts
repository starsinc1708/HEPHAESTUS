import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ValidationPanel from '../ValidationPanel.vue'
import type { ValidationResult } from '@/types/api'

const vr: ValidationResult = {
  layer1: [
    { lens: 'correctness', verdict: 'approve', confidence: 0.9, reasoning: 'ok' },
    { lens: 'tests', verdict: 'needs_revision', confidence: 0.4, reasoning: 'no test' },
    { lens: 'scope', verdict: 'reject', confidence: 0.8, reasoning: 'creep' },
  ],
  layer2Summary: [{ arbiter: 0, verdict: 'needs_revision' }],
  gate: 'needs_revision',
  blocking: ['tests: no test', 'scope: creep'],
  revision: 1,
}

describe('ValidationPanel', () => {
  it('renders one row per lens', () => {
    const w = mount(ValidationPanel, { props: { validation: vr } })
    expect(w.findAll('[data-test="lens-row"]')).toHaveLength(3)
  })
  it('renders gate and blocking list', () => {
    const w = mount(ValidationPanel, { props: { validation: vr } })
    // needs_revision gate now renders a friendly "sent to revision" banner
    expect(w.find('[data-test="gate"]').text()).toContain('доработку')
    expect(w.findAll('[data-test="blocking-item"]')).toHaveLength(2)
  })
  it('shows placeholder when validation is null', () => {
    const w = mount(ValidationPanel, { props: { validation: null } })
    expect(w.find('[data-test="no-validation"]').exists()).toBe(true)
  })
})
