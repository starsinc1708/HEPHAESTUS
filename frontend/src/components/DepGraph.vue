<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Item } from '@/types/api'
import { computeLayout, byId, depsSatisfied } from '@/composables/deps'

const props = defineProps<{ items: Item[] }>()
const emit = defineEmits<{ 'task-click': [id: string] }>()
const { t } = useI18n()

const NODE_W = 140
const NODE_H = 48

const layout = computed(() =>
  computeLayout(props.items, { colWidth: 180, rowHeight: 72, nodeW: NODE_W, nodeH: NODE_H }),
)

const map = computed(() => byId(props.items))

/** Status → CSS var (mirrors the TaskCard border palette). */
function statusColor(status: string): string {
  if (status === 'pending') return 'var(--blue)'
  if (status === 'queued') return 'var(--cyan)'
  if (status === 'in_progress') return 'var(--amber)'
  if (status === 'in_review') return 'var(--blue)'
  if (status === 'needs_revision') return 'var(--primary)'
  if (status === 'done' || status === 'merged') return 'var(--green)'
  if (status.startsWith('failed')) return 'var(--rose)'
  return 'var(--border-2)'
}

/**
 * Readiness ring for a queued node: 'ready' (all deps done) | 'waiting' (deps pending).
 * Non-queued nodes get no ring.
 */
function ringKind(item: Item): '' | 'ready' | 'waiting' {
  if (item.status !== 'queued') return ''
  return depsSatisfied(item, map.value) ? 'ready' : 'waiting'
}

function shortTitle(t: string): string {
  return t.length > 22 ? t.slice(0, 21) + '…' : t
}

function onNodeClick(id: string) {
  emit('task-click', id)
}
</script>

<template>
  <div class="dep-graph-wrap" data-test="dep-graph">
    <div v-if="!items.length" class="dep-empty">{{ t('depGraph.empty') }}</div>
    <div v-else class="dep-scroll">
      <svg
        :width="layout.width"
        :height="layout.height"
        :viewBox="`0 0 ${layout.width} ${layout.height}`"
        class="dep-svg"
      >
        <defs>
          <marker
            id="dep-arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--muted)" />
          </marker>
        </defs>

        <!-- Edges: prereq (left) → dependent (right), arrowhead at the dependent. -->
        <line
          v-for="e in layout.edges"
          :key="e.from + '->' + e.to"
          data-test="dep-edge"
          class="dep-edge"
          :x1="e.x1"
          :y1="e.y1"
          :x2="e.x2"
          :y2="e.y2"
          marker-end="url(#dep-arrow)"
        />

        <!-- Nodes -->
        <g
          v-for="n in layout.nodes"
          :key="n.id"
          class="dep-node"
          data-test="dep-node"
          :transform="`translate(${n.x}, ${n.y})`"
          role="button"
          tabindex="0"
          @click="onNodeClick(n.id)"
          @keydown.enter="onNodeClick(n.id)"
          @keydown.space.prevent="onNodeClick(n.id)"
        >
          <rect
            :width="NODE_W"
            :height="NODE_H"
            rx="6"
            class="node-rect"
            :class="ringKind(n.item) ? 'ring-' + ringKind(n.item) : ''"
            :style="{ stroke: statusColor(n.item.status) }"
          />
          <text class="node-id" x="8" y="18">{{ n.id }}</text>
          <text class="node-title" x="8" y="36">{{ shortTitle(n.item.title) }}</text>
          <title>{{ n.id }} — {{ n.item.title }} ({{ n.item.status }})</title>
        </g>
      </svg>
    </div>
  </div>
</template>

<style scoped>
.dep-graph-wrap {
  width: 100%;
}
.dep-scroll {
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 8px;
}
.dep-svg {
  display: block;
}
.dep-empty {
  text-align: center;
  padding: 40px 0;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 13px;
}

.dep-edge {
  stroke: var(--muted);
  stroke-width: 1.5;
  opacity: 0.7;
}

.dep-node {
  cursor: pointer;
}
.dep-node:focus-visible {
  outline: none;
}
.dep-node:focus-visible .node-rect {
  stroke-width: 2.5;
}

.node-rect {
  fill: var(--panel-2);
  stroke-width: 2;
  transition: fill 0.12s;
}
.dep-node:hover .node-rect {
  fill: var(--panel-3);
}
/* queued readiness rings */
.node-rect.ring-ready {
  stroke-dasharray: none;
  filter: drop-shadow(0 0 3px var(--green));
}
.node-rect.ring-waiting {
  stroke-dasharray: 4 3;
  opacity: 0.85;
}

.node-id {
  font-family: var(--mono);
  font-size: 10px;
  fill: var(--primary);
}
.node-title {
  font-size: 11px;
  fill: var(--text);
}
</style>
