import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { RepoProfile } from '@/types/api'
import { api } from '@/api/client'

export const useWorkspaceStore = defineStore('workspace', () => {
  const workspaces = ref<RepoProfile[]>([])
  const activeId = ref<string | null>(null)
  const active = computed(() => workspaces.value.find(w => w.id === activeId.value) ?? null)

  async function fetchWorkspaces(): Promise<void> {
    try {
      const res = await api.listWorkspaces()
      workspaces.value = res.workspaces
      activeId.value = res.activeId
    } catch {
      // leave previous state; callers (onMounted) must not crash on a transient failure
    }
  }
  async function onboard(repoPath: string, name?: string): Promise<RepoProfile> {
    const res = await api.onboard(repoPath, name)
    await fetchWorkspaces()
    return res.workspace
  }
  async function activate(id: string): Promise<void> {
    await api.activateWorkspace(id)
    activeId.value = id
  }
  async function updateProfile(id: string, patch: Partial<RepoProfile>): Promise<void> {
    await api.updateWorkspace(id, patch)
    await fetchWorkspaces()
  }

  return { workspaces, activeId, active, fetchWorkspaces, onboard, activate, updateProfile }
})
