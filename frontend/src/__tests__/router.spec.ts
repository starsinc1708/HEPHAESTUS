import { test, expect } from 'vitest'
import { routes } from '@/router'

const byName = (n: string) => routes.find(r => r.name === n)

test('five primary screens exist', () => {
  for (const n of ['settings', 'agents', 'board', 'tools', 'worktrees']) expect(byName(n)).toBeTruthy()
})

test('conversation viewer route exists with the right path + props', () => {
  const r = byName('board-task-conversation')
  expect(r).toBeTruthy()
  expect(r!.path).toBe('/board/task/:id/conversation')
  expect(r!.props).toBe(true)
})

test('old paths redirect to their new home', () => {
  const red = (p: string) => routes.find(r => r.path === p)?.redirect
  expect(red('/config')).toBe('/agents'); expect(red('/running')).toBe('/board')
  expect(red('/history')).toBe('/board'); expect(red('/branches')).toBe('/worktrees')
  expect(red('/prompts')).toBe('/agents'); expect(red('/insights')).toBe('/tools')
  expect(red('/logs')).toBe('/board'); expect(red('/onboard')).toBe('/board')
})
