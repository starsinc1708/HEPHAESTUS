<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { IntegrationProvider } from '@/types/api'
import { api } from '@/api/client'
import { useToastStore } from '@/stores/toast'

const { t } = useI18n()
const toast = useToastStore()

const DEFAULT_GITLAB_HOST = 'https://gitlab.com'
const LABELS: Record<string, string> = { github: 'GitHub', gitlab: 'GitLab' }
const ORDER = ['github', 'gitlab']

const providers = ref<IntegrationProvider[]>([])
const loading = ref(false)
const busyName = ref<string | null>(null)

// Per-card connect-form state (token + GitLab host). Seeded for every known
// provider up-front so template bindings (v-model) are always defined.
const forms = reactive<Record<string, { token: string; host: string }>>({})
ORDER.forEach(name => {
  forms[name] = { token: '', host: name === 'gitlab' ? DEFAULT_GITLAB_HOST : '' }
})

function stub(name: string): IntegrationProvider {
  return {
    name,
    available: false,
    connected: false,
    status: 'disconnected',
    hasToken: false,
    token: null,
    host: name === 'gitlab' ? DEFAULT_GITLAB_HOST : null,
    lastError: null,
    lastTestedAt: null,
    capabilities: { issues: false, pullRequests: false },
  }
}

// Always render github + gitlab in a stable order, even if the API omits one.
const cards = computed<IntegrationProvider[]>(() => {
  const byName = new Map(providers.value.map(p => [p.name, p]))
  return ORDER.map(name => byName.get(name) ?? stub(name))
})

function ensureForm(p: IntegrationProvider) {
  if (!forms[p.name]) forms[p.name] = { token: '', host: p.host ?? DEFAULT_GITLAB_HOST }
  else if (p.host && p.name === 'gitlab' && !forms[p.name].host) forms[p.name].host = p.host
}

function capLabel(name: string): string {
  return name === 'gitlab' ? 'MR' : 'PR'
}

async function fetchProviders() {
  loading.value = true
  try {
    const res = await api.listIntegrations()
    if (res.ok) {
      providers.value = res.providers
      res.providers.forEach(ensureForm)
    }
  } catch (e: unknown) {
    toast.add('error', t('integrations.loadError', { error: e instanceof Error ? e.message : String(e) }))
  } finally {
    loading.value = false
  }
}

async function connect(name: string) {
  const form = forms[name]
  const token = (form?.token ?? '').trim()
  if (!token) return
  busyName.value = name
  try {
    const body = name === 'gitlab'
      ? { token, host: (form.host || DEFAULT_GITLAB_HOST).trim() }
      : { token }
    const res = await api.connectIntegration(name, body)
    if (res.connected) toast.add('success', t('integrations.connectedToast', { label: LABELS[name] ?? name }))
    else toast.add('error', t('integrations.resultToast', { label: LABELS[name] ?? name, error: res.error ?? t('integrations.verifyFailed') }))
    await fetchProviders()
  } catch (e: unknown) {
    toast.add('error', e instanceof Error ? e.message : String(e))
    await fetchProviders() // reflect any partial server-side state
  } finally {
    if (form) form.token = '' // never leave the raw token in the field
    busyName.value = null
  }
}

async function verify(name: string) {
  busyName.value = name
  try {
    const res = await api.verifyIntegration(name)
    if (res.connected) toast.add('success', t('integrations.connectedToast', { label: LABELS[name] ?? name }))
    else toast.add('error', t('integrations.resultToast', { label: LABELS[name] ?? name, error: res.error ?? t('integrations.error') }))
    await fetchProviders()
  } catch (e: unknown) {
    toast.add('error', e instanceof Error ? e.message : String(e))
  } finally {
    busyName.value = null
  }
}

async function disconnect(name: string) {
  busyName.value = name
  try {
    await api.disconnectIntegration(name)
    toast.add('success', t('integrations.disconnectedToast', { label: LABELS[name] ?? name }))
    await fetchProviders()
  } catch (e: unknown) {
    toast.add('error', e instanceof Error ? e.message : String(e))
  } finally {
    busyName.value = null
  }
}

onMounted(() => {
  void fetchProviders()
})
</script>

<template>
  <div class="integrations-panel">
    <section class="int-section">
      <h4 class="int-section-title">{{ t('integrations.trackersTitle') }}</h4>
      <p class="int-hint">{{ t('integrations.hint') }}</p>

      <div v-if="loading && providers.length === 0" class="int-loading">{{ t('integrations.loading') }}</div>

      <div v-else class="provider-grid">
        <div
          v-for="p in cards"
          :key="p.name"
          class="provider-card"
          :data-test="`provider-${p.name}`"
        >
          <div class="card-head">
            <span class="provider-name">{{ LABELS[p.name] ?? p.name }}</span>
            <span
              class="status-chip"
              :class="p.connected ? 'chip-on' : 'chip-off'"
              :data-test="`int-status-${p.name}`"
            >{{ p.connected ? t('integrations.connected') : t('integrations.notConnected') }}</span>
          </div>

          <!-- Connected / token stored -->
          <template v-if="p.hasToken">
            <div class="cred-row">
              <span class="muted small">{{ t('integrations.token') }}</span>
              <code class="mono token" :data-test="`int-token-display-${p.name}`">{{ p.token }}</code>
            </div>
            <div v-if="p.host" class="cred-row">
              <span class="muted small">{{ t('integrations.host') }}</span>
              <code class="mono">{{ p.host }}</code>
            </div>
            <div
              v-if="p.status === 'failed' && p.lastError"
              class="int-error small"
              :data-test="`int-error-${p.name}`"
            >{{ p.lastError }}</div>

            <div v-if="p.connected" class="capability-chips">
              <span v-if="p.capabilities.issues" class="chip">{{ t('integrations.capIssues') }}</span>
              <span v-if="p.capabilities.pullRequests" class="chip">{{ capLabel(p.name) }}</span>
            </div>

            <div class="card-actions">
              <button
                class="btn mini"
                :data-test="`int-verify-${p.name}`"
                :disabled="busyName === p.name"
                @click="verify(p.name)"
              >{{ busyName === p.name ? t('integrations.testing') : t('integrations.verify') }}</button>
              <button
                class="btn mini btn-danger"
                :data-test="`int-disconnect-${p.name}`"
                :disabled="busyName === p.name"
                @click="disconnect(p.name)"
              >{{ t('integrations.disconnect') }}</button>
            </div>
          </template>

          <!-- Not connected — connect form -->
          <template v-else>
            <div class="connect-form">
              <input
                class="input mono"
                type="password"
                autocomplete="off"
                v-model="forms[p.name].token"
                :data-test="`int-token-${p.name}`"
                :placeholder="t('integrations.pat')"
              />
              <input
                v-if="p.name === 'gitlab'"
                class="input mono"
                type="text"
                v-model="forms[p.name].host"
                data-test="int-host-gitlab"
                :placeholder="DEFAULT_GITLAB_HOST"
              />
              <button
                class="btn btn-primary mini"
                :data-test="`int-connect-${p.name}`"
                :disabled="busyName === p.name || !forms[p.name].token.trim()"
                @click="connect(p.name)"
              >{{ busyName === p.name ? t('integrations.connecting') : t('integrations.connect') }}</button>
            </div>
          </template>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.integrations-panel {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.int-section {
  margin-bottom: 24px;
}

.int-section-title {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  margin: 0 0 6px;
}

.int-hint {
  font-size: 11px;
  color: var(--muted);
  margin: 0 0 12px;
  line-height: 1.5;
}

.int-loading,
.int-empty {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--muted);
  padding: 8px 0;
}

.provider-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
}

.provider-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 6px;
}

.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.provider-name {
  font-weight: 600;
  font-size: 13px;
  color: var(--text);
}

.status-chip {
  font-family: var(--mono);
  font-size: 10px;
  padding: 2px 7px;
  border-radius: 10px;
  margin-left: auto;
  border: 1px solid var(--border);
}

.chip-on {
  background: color-mix(in srgb, var(--green) 15%, transparent);
  color: var(--green);
  border-color: color-mix(in srgb, var(--green) 40%, transparent);
}

.chip-off {
  background: color-mix(in srgb, var(--muted) 12%, transparent);
  color: var(--muted);
}

.cred-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.cred-row .token {
  color: var(--text);
}

.mono {
  font-family: var(--mono);
}

.muted {
  color: var(--muted);
}

.small {
  font-size: 11px;
}

.int-error {
  color: var(--rose, #e53935);
}

.capability-chips {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.chip {
  font-family: var(--mono);
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--panel-3, var(--panel));
  border: 1px solid var(--border);
  color: var(--muted);
}

.connect-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.input {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-size: 12px;
  padding: 6px 10px;
  outline: none;
  width: 100%;
}

.input:focus {
  border-color: var(--primary);
}

.card-actions {
  display: flex;
  gap: 6px;
}

.btn {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-size: 12px;
  padding: 6px 12px;
  cursor: pointer;
}

.btn:hover {
  border-color: var(--primary);
}

.btn.mini {
  font-size: 11px;
  padding: 5px 10px;
}

.btn-primary {
  background: var(--primary);
  color: var(--on-primary);
  border-color: var(--primary);
  font-weight: 600;
}

.btn-danger {
  color: var(--rose, #e53935);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
