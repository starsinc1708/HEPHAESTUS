import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import AgentRolesPicker from '../AgentRolesPicker.vue'
import type { Connection, RoleConnections } from '@/types/api'

function conn(id: string, status: Connection['status']): Connection {
  return { id, label: id, provider: 'deepseek', engine: 'claude', authMethod: 'api_key', model: 'deepseek-chat', env: {}, status }
}

const CONNECTIONS: Connection[] = [
  conn('conn-ok', 'connected'),
  conn('conn-bad', 'failed'),
  conn('conn-new', 'untested'),
]

function factory(modelValue: RoleConnections = {}, warnings: string[] = []) {
  return mount(AgentRolesPicker, {
    props: { connections: CONNECTIONS, modelValue, warnings },
  })
}

describe('AgentRolesPicker', () => {
  it('renders a select per single role and rows for validators/arbiters', () => {
    const w = factory()
    for (const role of ['primary', 'fallback', 'planner', 'final', 'merge']) {
      expect(w.find(`[data-test="role-${role}"]`).exists()).toBe(true)
    }
    expect(w.findAll('[data-test^="role-validators-"]')).toHaveLength(5)
    expect(w.findAll('[data-test^="role-arbiters-"]')).toHaveLength(2)
  })

  it('only connected connections are enabled options; failed/untested are disabled', () => {
    const w = factory()
    const opts = w.find('[data-test="role-primary"]').findAll('option')
    const ok = opts.find(o => o.element.value === 'conn-ok')!
    const bad = opts.find(o => o.element.value === 'conn-bad')!
    const untested = opts.find(o => o.element.value === 'conn-new')!
    expect(ok.attributes('disabled')).toBeUndefined()
    expect(bad.attributes('disabled')).toBeDefined()
    expect(untested.attributes('disabled')).toBeDefined()
    expect(bad.text()).toContain('ошибка')
    expect(untested.text()).toContain('не проверено')
  })

  it('changing role-primary emits update:modelValue with primary set', async () => {
    const w = factory()
    await w.find('[data-test="role-primary"]').setValue('conn-ok')
    const emitted = w.emitted('update:modelValue')
    expect(emitted).toBeTruthy()
    const last = emitted!.at(-1)![0] as RoleConnections
    expect(last.primary).toBe('conn-ok')
  })

  it('«Применить ко всем» sets all single roles and fills the lists', async () => {
    const w = factory()
    // pick the apply-all source first
    await w.find('[data-test="roles-apply-all-select"]').setValue('conn-ok')
    await w.find('[data-test="roles-apply-all"]').trigger('click')
    const emitted = w.emitted('update:modelValue')
    expect(emitted).toBeTruthy()
    const last = emitted!.at(-1)![0] as RoleConnections
    expect(last.primary).toBe('conn-ok')
    expect(last.fallback).toBe('conn-ok')
    expect(last.planner).toBe('conn-ok')
    expect(last.final).toBe('conn-ok')
    expect(last.merge).toBe('conn-ok')
    expect(last.validators).toEqual(['conn-ok', 'conn-ok', 'conn-ok', 'conn-ok', 'conn-ok'])
    expect(last.arbiters).toEqual(['conn-ok', 'conn-ok'])
  })

  it('shows a warning banner when warnings is non-empty', () => {
    const w = factory({}, ['conn-gone'])
    const banner = w.find('[data-test="role-warning"]')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('conn-gone')
  })

  it('has no warning banner when warnings is empty', () => {
    const w = factory({}, [])
    expect(w.find('[data-test="role-warning"]').exists()).toBe(false)
  })
})
