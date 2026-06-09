import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { EffectiveConfig } from '@/types/api'
import { api } from '@/api/client'
import { useToastStore } from './toast'
import { i18n } from '@/i18n'
const t = i18n.global.t

export const useConfigStore = defineStore('config', () => {
  const effective = ref<EffectiveConfig>({})
  const overrides = ref<Record<string, string>>({})
  const loading = ref(false)

  // Track original values for dirty detection
  let _originalOverrides: Record<string, string> = {}

  const isDirty = computed(() => {
    const origKeys = Object.keys(_originalOverrides).sort()
    const currKeys = Object.keys(overrides.value).sort()
    if (origKeys.length !== currKeys.length) return true
    return origKeys.some((key, i) => key !== currKeys[i] || _originalOverrides[key] !== overrides.value[key])
  })

  async function fetchConfig() {
    try {
      loading.value = true
      // GET /api/config returns { effective, overrides } — keep them separate so the
      // base-params editor reads real values (not the wrapper object) and saves don't wipe.
      const res = await api.getConfig()
      effective.value = res.effective ?? {}
      overrides.value = res.overrides ?? {}
    } catch {
      // silent
    } finally {
      loading.value = false
    }
  }

  async function saveConfig(newOverrides: Record<string, string>) {
    const toast = useToastStore()
    try {
      await api.putConfig(newOverrides)
      overrides.value = newOverrides
      _originalOverrides = { ...newOverrides }
      toast.add('success', t('settings.configSaved'))
      await fetchConfig()
    } catch (e: unknown) {
      toast.add('error', t('settings.saveError', { error: e instanceof Error ? e.message : String(e) }))
    }
  }

  async function applyPreset(name: string) {
    const toast = useToastStore()
    try {
      await api.configPreset(name)
      toast.add('success', t('settings.presetApplied', { name }))
      await fetchConfig()
    } catch (e: unknown) {
      toast.add('error', t('settings.presetError', { error: e instanceof Error ? e.message : String(e) }))
    }
  }

  function discardChanges() {
    overrides.value = { ..._originalOverrides }
  }

  function setOverrides(vals: Record<string, string>) {
    overrides.value = vals
  }

  function snapshotOriginals() {
    _originalOverrides = { ...overrides.value }
  }

  return { effective, overrides, loading, isDirty, fetchConfig, saveConfig, applyPreset, discardChanges, setOverrides, snapshotOriginals }
})
