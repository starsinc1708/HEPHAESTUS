import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import OrderBadge from '@/components/OrderBadge.vue'

describe('OrderBadge', () => {
  it('renders 1-based order', () => {
    const w = mount(OrderBadge, { props: { orderIndex: 0, conflictGroup: null } })
    expect(w.text()).toContain('#1')
    expect(w.find('.conflict-dot').exists()).toBe(false)
  })

  it('shows conflict dot when conflictGroup set', () => {
    const w = mount(OrderBadge, { props: { orderIndex: 4, conflictGroup: 'cg-deadbeef' } })
    expect(w.text()).toContain('#5')
    expect(w.find('.conflict-dot').exists()).toBe(true)
  })
})
