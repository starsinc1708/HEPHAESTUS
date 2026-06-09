<script setup lang="ts">
import { ref, inject } from 'vue'
import { useI18n } from 'vue-i18n'
import type { DirEntry } from '@/types/api'

interface ScopeCtx {
  isSelected: (p: string) => boolean
  isCovered: (p: string) => boolean
  toggle: (p: string) => void
  loadChildren: (path: string) => Promise<{ dirs: DirEntry[] }>
}

const { t } = useI18n()
const props = defineProps<{ node: DirEntry }>()
const ctx = inject<ScopeCtx>('scopeCtx')!

const expanded = ref(false)
const children = ref<DirEntry[] | null>(null)
const loading = ref(false)

async function toggleExpand() {
  if (!props.node.hasChildren) return
  expanded.value = !expanded.value
  if (expanded.value && children.value === null) {
    loading.value = true
    try {
      children.value = (await ctx.loadChildren(props.node.path)).dirs
    } catch {
      children.value = []
    } finally {
      loading.value = false
    }
  }
}
</script>

<template>
  <li class="node">
    <div class="node-row">
      <button
        class="caret"
        :class="{ open: expanded, leaf: !node.hasChildren }"
        :disabled="!node.hasChildren"
        @click="toggleExpand"
      >{{ node.hasChildren ? '▸' : '·' }}</button>
      <label class="node-label" :class="{ covered: ctx.isCovered(node.path) }">
        <input
          type="checkbox"
          :checked="ctx.isSelected(node.path) || ctx.isCovered(node.path)"
          :disabled="ctx.isCovered(node.path)"
          @change="ctx.toggle(node.path)"
        />
        <span class="name">{{ node.name }}</span>
        <span class="count">{{ node.files }}</span>
      </label>
    </div>
    <ul v-if="expanded" class="children">
      <li v-if="loading" class="muted small">…</li>
      <ScopeNode v-for="c in (children ?? [])" :key="c.path" :node="c" />
      <li v-if="children && !children.length && !loading" class="muted small">{{ t('tools.scopeNode.empty') }}</li>
    </ul>
  </li>
</template>

<style scoped>
.node { list-style: none; }
.node-row { display: flex; align-items: center; gap: 4px; }
.caret {
  width: 16px; height: 16px; line-height: 1; flex-shrink: 0;
  background: none; border: none; color: var(--muted); cursor: pointer;
  font-size: 10px; padding: 0; transition: transform 0.12s;
}
.caret.open { transform: rotate(90deg); }
.caret.leaf { cursor: default; opacity: 0.4; }
.node-label {
  display: flex; align-items: center; gap: 6px; flex: 1;
  font-size: 12px; padding: 2px 4px; border-radius: 4px; cursor: pointer;
}
.node-label:hover { background: var(--panel-2); }
.node-label.covered { opacity: 0.65; cursor: default; }
.node-label input { cursor: inherit; }
.name { font-family: var(--mono); color: var(--text); }
.count {
  font-size: 10px; color: var(--muted); background: var(--panel-2);
  border-radius: 3px; padding: 0 5px; margin-left: auto;
}
.children { margin: 0 0 0 16px; padding: 0; border-left: 1px solid var(--border); }
.muted { color: var(--muted); }
.small { font-size: 11px; }
</style>
