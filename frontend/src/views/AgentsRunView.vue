<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RepoProfile, Connection, RoleConnections } from '@/types/api'
import { useWorkspaceStore } from '@/stores/workspace'
import { useToastStore } from '@/stores/toast'
import { api } from '@/api/client'
import AppShell from '@/components/AppShell.vue'
import AgentRolesPicker from '@/components/AgentRolesPicker.vue'
import AgentsScanConfig from '@/components/AgentsScanConfig.vue'
import AgentsRunControls from '@/components/AgentsRunControls.vue'
import AgentsPromptsEditor from '@/components/AgentsPromptsEditor.vue'

const ws = useWorkspaceStore()
const toast = useToastStore()
const { t } = useI18n()

const draft = ref<RepoProfile | null>(null)
const connections = ref<Connection[]>([])
const busy = ref(false)
const pageLoading = ref(true)

// Deep clone of the active profile; guarantee roleConnections/roleWarnings exist so the
// picker's get/set computeds never operate on undefined.
function clone(p: RepoProfile): RepoProfile {
  const d = JSON.parse(JSON.stringify(p)) as RepoProfile
  d.roleConnections = d.roleConnections ?? {}
  d.roleWarnings = d.roleWarnings ?? []
  return d
}

const roleConnections = computed<RoleConnections>({
  get: () => draft.value?.roleConnections ?? {},
  set: (v: RoleConnections) => { if (draft.value) draft.value.roleConnections = v },
})
const roleWarnings = computed<string[]>(() => draft.value?.roleWarnings ?? [])

async function loadConnections() {
  try {
    connections.value = (await api.getConnections()).connections
  } catch { /* leave previous list — never crash the page */ }
}

async function saveRoles() {
  if (!draft.value) return
  busy.value = true
  try {
    await ws.updateProfile(draft.value.id, { roleConnections: draft.value.roleConnections })
    toast.add('success', t('agents.rolesSaved'))
  } catch (e: unknown) {
    toast.add('error', e instanceof Error ? e.message : String(e))
  } finally { busy.value = false }
}

watch(() => ws.active, (a) => { draft.value = a ? clone(a) : null }, { immediate: true })

onMounted(async () => {
  pageLoading.value = true
  try {
    await ws.fetchWorkspaces()
    await loadConnections()
  } catch {
    // error handled by individual calls
  } finally {
    pageLoading.value = false
  }
})
</script>

<template>
  <AppShell>
    <template #title>{{ t('agents.title') }}</template>

    <!-- Loading state -->
    <div v-if="pageLoading" class="loading-state" data-test="agents-loading">
      <span class="loading-spinner" />
      <span>{{ t('agents.loading') }}</span>
    </div>

    <div v-else class="agents-page">
      <!-- Роли агентов -->
      <section class="agents-block" data-test="agents-roles">
        <h2 class="block-title">{{ t('agents.rolesTitle') }}</h2>
        <template v-if="draft">
          <AgentRolesPicker v-model="roleConnections" :connections="connections" :warnings="roleWarnings" />
          <button class="btn btn-primary save-roles" :disabled="busy" data-test="save-roles" @click="saveRoles">{{ t('agents.saveRoles') }}</button>
        </template>
        <p v-else class="muted">{{ t('agents.noRepo') }}</p>
      </section>

      <!-- Сканы и конфигурация -->
      <section class="agents-block" data-test="agents-scans">
        <h2 class="block-title">{{ t('agents.scanConfigTitle') }}</h2>
        <AgentsScanConfig />
      </section>

      <!-- Запуск -->
      <section class="agents-block" data-test="agents-run">
        <h2 class="block-title">{{ t('agents.runTitle') }}</h2>
        <AgentsRunControls />
      </section>

      <!-- Промпты -->
      <section class="agents-block" data-test="agents-prompts">
        <h2 class="block-title">{{ t('agents.promptsTitle') }}</h2>
        <AgentsPromptsEditor />
      </section>
    </div>
  </AppShell>
</template>

<style scoped>
.agents-page { display: flex; flex-direction: column; gap: 24px; max-width: 1100px; }
.agents-block { display: flex; flex-direction: column; gap: 12px; }
.block-title { font-size: 15px; font-weight: 600; margin: 0; }
.muted { color: var(--muted); }
.btn { background: var(--panel-2); border: 1px solid var(--border); border-radius: 4px; color: var(--text); font-size: 12px; padding: 6px 12px; cursor: pointer; }
.btn:hover { border-color: var(--primary); }
.btn-primary { background: var(--primary); color: var(--on-primary); border-color: var(--primary); font-weight: 600; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.save-roles { align-self: flex-start; }

.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 60px 0;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 14px;
}

.loading-spinner {
  display: inline-block;
  width: 18px;
  height: 18px;
  border: 2px solid var(--border);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
