<script setup lang="ts">
/**
 * Directory browser for picking a repository during onboarding.
 *
 * Typing an absolute path is error-prone — and under Docker the path is the *in-container*
 * mount (e.g. /projects/<repo>), not the host path. This component browses the filesystem the
 * **server** can see (GET /api/v1/fs/browse): click a folder to descend, "up" to ascend, and
 * pick either a flagged git repo (per-row button) or the current folder. The chosen absolute
 * path is emitted via v-model so the wizard can onboard it.
 */
import { ref, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import type { FsEntry } from '@/types/api'

const props = withDefaults(
  defineProps<{ modelValue: string; busy?: boolean; start?: string }>(),
  // Default to the conventional Docker mount; the backend falls back to the nearest existing
  // ancestor (→ filesystem root) when it doesn't exist, so host installs degrade gracefully.
  { busy: false, start: '/projects' },
)
const emit = defineEmits<{ 'update:modelValue': [string] }>()

const { t } = useI18n()

const cwd = ref('')
const parent = ref<string | null>(null)
const entries = ref<FsEntry[]>([])
const loading = ref(false)
const error = ref(false)

async function load(path: string): Promise<void> {
  loading.value = true
  error.value = false
  try {
    const r = await api.browseFs(path)
    cwd.value = r.path
    parent.value = r.parent
    entries.value = r.entries
  } catch (e) {
    error.value = true
    console.warn('browseFs failed:', e)
  } finally {
    loading.value = false
  }
}

function open(entry: FsEntry): void {
  if (props.busy) return
  void load(entry.path)
}

function goUp(): void {
  if (props.busy || parent.value == null) return
  void load(parent.value)
}

function select(path: string): void {
  if (props.busy) return
  emit('update:modelValue', path)
}

onMounted(() => void load(props.start))
// If the parent clears the path (e.g. after a successful add), keep showing the browser as-is;
// no reload needed. We only react to `start` changes (rare) to re-root.
watch(() => props.start, (s) => void load(s))
</script>

<template>
  <div class="repo-picker" data-test="repo-picker">
    <div class="rp-bar">
      <button
        class="btn rp-up"
        data-test="rp-up"
        :disabled="busy || parent == null || loading"
        :title="t('wizard.step3.picker.up')"
        @click="goUp"
      >↑</button>
      <code class="rp-path" data-test="rp-path">{{ cwd || '…' }}</code>
      <button
        class="btn rp-select-current"
        data-test="rp-select-current"
        :disabled="busy || !cwd || loading"
        @click="select(cwd)"
      >{{ t('wizard.step3.picker.selectFolder') }}</button>
    </div>

    <div class="rp-list" :class="{ busy }">
      <p v-if="loading" class="rp-msg" data-test="rp-loading">{{ t('wizard.step3.picker.loading') }}</p>
      <p v-else-if="error" class="rp-msg rp-err" data-test="rp-error">{{ t('wizard.step3.picker.error') }}</p>
      <p v-else-if="entries.length === 0" class="rp-msg" data-test="rp-empty">{{ t('wizard.step3.picker.empty') }}</p>
      <ul v-else class="rp-ul">
        <li
          v-for="e in entries"
          :key="e.path"
          class="rp-row"
          :class="{ git: e.isGitRepo, sel: e.path === modelValue }"
          :data-test="`rp-entry-${e.name}`"
        >
          <button class="rp-name" :disabled="busy" :title="e.path" @click="open(e)">
            <span class="rp-ico">{{ e.isGitRepo ? '◆' : '▸' }}</span>
            <span class="rp-label">{{ e.name }}</span>
            <span v-if="e.isGitRepo" class="rp-badge">{{ t('wizard.step3.picker.git') }}</span>
          </button>
          <button
            v-if="e.isGitRepo"
            class="btn rp-pick"
            :data-test="`rp-select-${e.name}`"
            :disabled="busy"
            @click="select(e.path)"
          >{{ e.path === modelValue ? t('wizard.step3.picker.selected') : t('wizard.step3.picker.select') }}</button>
        </li>
      </ul>
    </div>
    <p class="rp-hint">{{ t('wizard.step3.picker.hint') }}</p>
  </div>
</template>

<style scoped>
.repo-picker {
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 10px;
}
.rp-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  background: var(--panel-2);
  border-bottom: 1px solid var(--border);
}
.rp-path {
  flex: 1;
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  /* Left-truncate long paths so the tail (repo name) stays visible, while `plaintext`
     keeps the bidi order correct so short paths render "/projects", not "projects/". */
  direction: rtl;
  unicode-bidi: plaintext;
  text-align: left;
}
.rp-up { padding: 4px 10px; font-weight: 700; }
.rp-select-current { font-size: 11px; padding: 4px 8px; white-space: nowrap; }
.rp-list {
  max-height: 220px;
  overflow: auto;
}
.rp-list.busy { opacity: 0.6; pointer-events: none; }
.rp-ul { list-style: none; margin: 0; padding: 0; }
.rp-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 8px;
  border-bottom: 1px solid var(--border);
}
.rp-row:last-child { border-bottom: none; }
.rp-row.sel { background: color-mix(in srgb, var(--primary) 14%, transparent); }
.rp-name {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  background: transparent;
  border: none;
  color: var(--text);
  font-size: 13px;
  padding: 8px 0;
  cursor: pointer;
  text-align: left;
  overflow: hidden;
}
.rp-name:hover .rp-label { color: var(--primary); }
.rp-ico { color: var(--muted); font-size: 11px; width: 12px; }
.rp-row.git .rp-ico { color: var(--primary); }
.rp-label { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rp-badge {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--primary);
  border: 1px solid var(--primary);
  border-radius: 3px;
  padding: 0 4px;
  line-height: 14px;
}
.rp-pick { font-size: 11px; padding: 3px 8px; white-space: nowrap; }
.rp-msg { color: var(--muted); font-size: 12px; padding: 14px 10px; margin: 0; text-align: center; }
.rp-err { color: var(--rose, #e53935); }
.rp-hint { color: var(--muted); font-size: 11px; margin: 6px 2px 0; }
.btn {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-size: 12px;
  cursor: pointer;
}
.btn:hover:not(:disabled) { border-color: var(--primary); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
