<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import type { Connection } from '@/types/api'
import { api } from '@/api/client'
import { useLoopStore } from '@/stores/loop'
import { useBoardStore } from '@/stores/board'
import { useToastStore } from '@/stores/toast'
import { useWorkspaceStore } from '@/stores/workspace'
import WorkspaceSwitcher from '@/components/WorkspaceSwitcher.vue'
import LangToggle from '@/components/LangToggle.vue'
import LogsDrawer from '@/components/LogsDrawer.vue'
import OnboardWizard from '@/components/OnboardWizard.vue'

const route = useRoute()
const { t } = useI18n()
const loopStore = useLoopStore()
const boardStore = useBoardStore()
const toastStore = useToastStore()
const ws = useWorkspaceStore()

// ── First-launch onboarding (blocking overlay) ──
const connections = ref<Connection[]>([])
async function refreshConnections() {
  try { connections.value = (await api.getConnections()).connections } catch { /* keep previous */ }
}
const needsOnboarding = computed(() => connections.value.length === 0 || ws.activeId == null)
// Gate the overlay on the initial fetch so configured users don't see a flash of
// the blocking wizard (connections/activeId start empty before onMounted resolves).
const onboardingReady = ref(false)
const skipped = ref(localStorage.getItem('hephaestus.onboarding.skipped') === '1')
function onSkip() {
  localStorage.setItem('hephaestus.onboarding.skipped', '1')
  skipped.value = true
}
function onReopen() {
  localStorage.removeItem('hephaestus.onboarding.skipped')
  skipped.value = false
}
const showWizard = computed(() => onboardingReady.value && needsOnboarding.value && !skipped.value)
const showBanner = computed(() => onboardingReady.value && needsOnboarding.value && skipped.value)

onMounted(async () => {
  // AppShell is the persistent root and never unmounts, so it owns driver/loop polling
  // app-wide. Do NOT call stopPolling here.
  loopStore.startPolling()
  await ws.fetchWorkspaces()
  await refreshConnections()
  onboardingReady.value = true
})

// Computed so labels re-render when the locale switches.
const navItems = computed(() => [
  { path: '/settings',  label: t('nav.settings'),  icon: '⚙' },
  { path: '/agents',    label: t('nav.agents'),    icon: '▶' },
  { path: '/board',     label: t('nav.board'),     icon: '▦' },
  { path: '/tools',     label: t('nav.tools'),     icon: '🔧' },
  { path: '/worktrees', label: t('nav.worktrees'), icon: '⑂' },
])

const activeNav = computed(() => route.path.startsWith('/board') ? '/board' : route.path)

const logsDrawerOpen = ref(false)

const driverRunning = computed(() => loopStore.driver.process.state === 'running')
const progressPct = computed(() => boardStore.summary.percent_done)
</script>

<template>
  <div class="app-shell" :class="{ 'with-banner': showBanner }">
    <aside class="sidebar">
      <div class="sidebar-brand">
        <span class="brand-name">hephaestus</span>
        <span class="brand-dot" :class="{ active: driverRunning }" />
      </div>

      <nav class="sidebar-nav">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-link"
          data-test="nav-link"
          :class="{ active: activeNav === item.path }"
        >
          <span class="nav-icon">{{ item.icon }}</span>
          <span class="nav-label">{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: progressPct + '%' }" />
        </div>
        <div class="progress-label">{{ t('shell.progressDone', { pct: progressPct }) }}</div>
      </div>
    </aside>

    <div class="main-area">
      <header class="top-bar">
        <div class="top-bar-left">
          <h1 class="page-title">
            <slot name="title">{{ route.name }}</slot>
          </h1>
        </div>
        <div class="top-bar-right">
          <LangToggle />
          <WorkspaceSwitcher />
          <button
            class="btn btn-sm"
            data-test="logs-toggle"
            :title="t('shell.logs')"
            @click="logsDrawerOpen = !logsDrawerOpen"
          >
            ▤ {{ t('shell.logs') }}
          </button>
          <button
            v-if="loopStore.driver.paused"
            class="btn btn-sm btn-primary"
            data-test="driver-toggle-shell"
            @click="loopStore.resumeDriver()"
          >
            ▶ {{ t('shell.driver.resume') }}
          </button>
          <button
            v-else-if="driverRunning"
            class="btn btn-sm btn-warn"
            data-test="driver-toggle-shell"
            @click="loopStore.pauseDriver()"
          >
            ⏸ {{ t('shell.driver.pause') }}
          </button>
        </div>
      </header>
      <main class="content">
        <slot />
      </main>
    </div>

    <!-- First-launch onboarding overlay (blocking) -->
    <OnboardWizard
      v-if="showWizard"
      data-test="onboard-wizard"
      :connections="connections"
      @connections-changed="connections = $event"
      @skip="onSkip"
    />

    <!-- Dismissed-onboarding reminder banner -->
    <div v-else-if="showBanner" class="onboard-banner" data-test="onboard-banner">
      <span>{{ t('shell.onboard.banner') }}</span>
      <button class="btn btn-sm" data-test="onboard-reopen" @click="onReopen">{{ t('shell.onboard.configure') }}</button>
    </div>

    <!-- Logs drawer -->
    <LogsDrawer v-if="logsDrawerOpen" @close="logsDrawerOpen = false" />

    <!-- Toasts -->
    <div class="toast-container">
      <TransitionGroup name="toast-list">
        <div
          v-for="t in toastStore.toasts"
          :key="t.id"
          class="toast"
          :class="'toast-' + t.kind"
          @click="t.undoAction ? undefined : toastStore.dismiss(t.id)"
        >
          <span>{{ t.message }}</span>
          <button
            v-if="t.undoAction"
            class="toast-undo"
            @click.stop="toastStore.undo(t.id)"
          >
            {{ $t('shell.toast.undo') }}
          </button>
        </div>
      </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
  font-family: var(--sans);
}

/* Sidebar */
.sidebar {
  width: 180px;
  background: var(--panel);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px;
  border-bottom: 1px solid var(--border);
}

.brand-name {
  font-family: var(--mono);
  font-size: 18px;
  font-weight: 700;
  color: var(--primary);
}

.brand-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--muted);
}
.brand-dot.active {
  background: var(--green);
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.3; }
}

.sidebar-nav {
  display: flex;
  flex-direction: column;
  padding: 8px;
  flex: 1;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 13px;
  color: var(--muted);
  text-decoration: none;
  position: relative;
  transition: background 0.12s, color 0.12s;
}
.nav-link:hover { background: var(--panel-2); color: var(--text); }
.nav-link.active {
  background: var(--panel-2);
  color: var(--primary);
}
.nav-link.active::after {
  content: '';
  position: absolute;
  bottom: 2px;
  left: 10px;
  right: 10px;
  height: 2px;
  background: var(--primary);
  border-radius: 1px;
  animation: nav-underline 0.2s ease;
}

@keyframes nav-underline {
  from { transform: scaleX(0); }
  to   { transform: scaleX(1); }
}

.nav-icon { font-size: 15px; width: 20px; text-align: center; }
.nav-label { font-weight: 500; }

.sidebar-footer {
  padding: 12px;
  border-top: 1px solid var(--border);
}

.progress-bar {
  height: 4px;
  background: var(--panel-3);
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--primary);
  border-radius: 2px;
  transition: width 0.4s ease;
}

.progress-label {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
  margin-top: 4px;
  text-align: center;
}

/* Main */
.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--panel);
  flex-shrink: 0;
}

.page-title {
  font-size: 16px;
  font-weight: 600;
  margin: 0;
}

.btn {
  font-family: var(--mono);
  font-size: 12px;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 5px 12px;
  cursor: pointer;
  background: var(--panel-2);
  color: var(--text);
  transition: background 0.12s;
}
.btn:hover { background: var(--panel-3); }
.btn-sm { font-size: 11px; padding: 4px 10px; }
.btn-primary { border-color: var(--primary); color: var(--primary); }
.btn-warn { border-color: var(--amber); color: var(--amber); }

.content {
  flex: 1;
  padding: 16px 20px;
  overflow: auto;
}

/* Toasts */
.toast-container {
  position: fixed;
  bottom: 16px;
  right: 16px;
  z-index: 200;
  display: flex;
  flex-direction: column-reverse;
  gap: 6px;
}
.toast {
  font-family: var(--mono);
  font-size: 12px;
  padding: 8px 14px;
  border-radius: 6px;
  background: var(--panel-2);
  border: 1px solid var(--border);
  color: var(--text);
  cursor: pointer;
  max-width: 360px;
}
.toast-success { border-color: var(--green); color: var(--green); }
.toast-error   { border-color: var(--rose);  color: var(--rose); }
.toast-warn    { border-color: var(--amber); color: var(--amber); }
.toast-info    { border-color: var(--blue);  color: var(--blue); }

.toast-undo {
  display: inline-block;
  margin-left: 10px;
  padding: 1px 8px;
  border: 1px solid currentColor;
  border-radius: 3px;
  background: transparent;
  color: inherit;
  font-family: var(--mono);
  font-size: 11px;
  cursor: pointer;
  opacity: 0.85;
  transition: opacity 0.12s;
}
.toast-undo:hover { opacity: 1; }

/* Onboarding reminder banner */
/* Offset the shell below the fixed banner so it doesn't cover the top-bar controls. */
.app-shell.with-banner { padding-top: 34px; }
.onboard-banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 150;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 8px 16px;
  font-size: 12px;
  background: var(--amber, #b08900);
  color: #1a1a1a;
  border-bottom: 1px solid var(--border);
}
.onboard-banner .btn {
  background: rgba(0, 0, 0, 0.15);
  border-color: rgba(0, 0, 0, 0.25);
  color: #1a1a1a;
}

.toast-list-enter-active { transition: all 0.2s ease; }
.toast-list-leave-active { transition: all 0.15s ease; }
.toast-list-enter-from   { opacity: 0; transform: translateX(30px); }
.toast-list-leave-to     { opacity: 0; transform: translateY(10px); }
</style>
