import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/board',
  },
  {
    path: '/board',
    name: 'board',
    component: () => import('@/views/BoardView.vue'),
  },
  {
    path: '/board/task/:id',
    name: 'board-task',
    component: () => import('@/views/BoardView.vue'),
    props: true,
  },
  {
    path: '/board/task/:id/conversation',
    name: 'board-task-conversation',
    component: () => import('@/views/ConversationView.vue'),
    props: true,
  },
  {
    path: '/agents',
    name: 'agents',
    component: () => import('@/views/AgentsRunView.vue'),
  },
  {
    path: '/tools',
    name: 'tools',
    component: () => import('@/views/ToolsView.vue'),
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
  },
  {
    path: '/worktrees',
    name: 'worktrees',
    component: () => import('@/views/WorktreesView.vue'),
  },
  // ── Redirects from old routes ──
  { path: '/config', redirect: '/agents' },
  { path: '/prompts', redirect: '/agents' },
  { path: '/running', redirect: '/board' },
  { path: '/history', redirect: '/board' },
  { path: '/logs', redirect: '/board' },
  { path: '/onboard', redirect: '/board' },
  { path: '/branches', redirect: '/worktrees' },
  { path: '/insights', redirect: '/tools' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
