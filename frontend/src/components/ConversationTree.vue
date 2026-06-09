<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ConversationIteration, ConversationAgentRun } from '@/types/api'

const props = defineProps<{
  iterations: ConversationIteration[]
  selectedKey: string | null   // `${dir}::${stream}` of the currently open agent, or null
}>()

const emit = defineEmits<{ select: [payload: { dir: string; agent: ConversationAgentRun }] }>()

const { t } = useI18n()

// Mirror StatusBadge colour logic: green for success-ish, amber for needs_revision,
// rose for reject/failed, muted otherwise.
function statusColor(status: string): string {
  if (status === 'approve' || status === 'pass' || status === 'done' || status === 'merged') return 'var(--green)'
  if (status === 'needs_revision') return 'var(--amber)'
  if (status === 'reject' || status.startsWith('failed')) return 'var(--rose)'
  return 'var(--muted)'
}

const STAGE_LABEL = computed<Record<string, string>>(() => ({
  implement: t('conversation.stageImplementation'),
  validate: t('conversation.stageValidation'),
}))
function stageLabel(stage: string): string {
  return STAGE_LABEL.value[stage] ?? stage
}

function roleLabel(role: string): string {
  if (role === 'implementer') return t('conversation.roleImplementer')
  if (role === 'arbiter') return t('conversation.roleArbiter')
  if (role === 'final') return t('conversation.roleFinal')
  if (role.startsWith('validator:')) {
    const lens = role.split(':', 2)[1] ?? ''
    return t('conversation.validator', { lens })
  }
  return role
}

function shortDir(dir: string): string {
  // keep the trailing segment if a path-like dir is passed
  const parts = dir.split(/[\\/]/)
  return parts[parts.length - 1] || dir
}

function keyOf(dir: string, agent: ConversationAgentRun): string {
  return `${dir}::${agent.stream}`
}

function onSelect(dir: string, agent: ConversationAgentRun): void {
  emit('select', { dir, agent })
}
</script>

<template>
  <div class="conv-tree" data-test="conv-tree">
    <p v-if="!iterations.length" class="empty muted">{{ t('conversation.noConversationsShort') }}</p>

    <div v-for="iter in iterations" :key="iter.dir" class="iter">
      <div class="iter-head">
        <span class="iter-dir">{{ shortDir(iter.dir) }}</span>
        <span class="iter-meta muted">{{ iter.createdAt }}</span>
        <span class="iter-meta muted">{{ iter.attempts }} {{ t('conversation.revisions') }}</span>
      </div>

      <div v-for="stg in iter.stages" :key="stg.stage" class="stage">
        <div class="stage-head">{{ stageLabel(stg.stage) }}</div>

        <div
          v-for="agent in stg.agents"
          :key="keyOf(iter.dir, agent)"
          class="agent"
          :class="{ selected: keyOf(iter.dir, agent) === selectedKey }"
          :data-test="`conv-agent-${agent.stream}`"
          role="button"
          tabindex="0"
          @click="onSelect(iter.dir, agent)"
          @keydown.enter="onSelect(iter.dir, agent)"
          @keydown.space.prevent="onSelect(iter.dir, agent)"
        >
          <span class="dot" :style="{ background: statusColor(agent.status) }" />
          <div class="agent-body">
            <div class="agent-top">
              <span class="role">{{ roleLabel(agent.role) }}</span>
              <span class="rev">r{{ agent.revision }}</span>
              <span v-if="agent.current" class="cur">{{ t('conversation.current') }}</span>
            </div>
            <div class="agent-sub muted">
              <span v-if="agent.model" class="model">{{ agent.model }}</span>
               <span class="msgs">{{ agent.messages }} {{ t('conversation.messages') }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.conv-tree {
  display: flex;
  flex-direction: column;
  gap: 12px;
  font-family: var(--sans);
  font-size: 13px;
  color: var(--text);
  overflow-y: auto;
}
.empty {
  padding: 16px 8px;
  font-size: 12px;
}
.iter {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.iter-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 4px 6px;
  font-family: var(--mono);
  font-size: 11px;
}
.iter-dir {
  color: var(--text);
  font-weight: 600;
}
.iter-meta {
  font-size: 10px;
}
.stage {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.stage-head {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--muted);
  padding: 4px 6px 2px;
}
.agent {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 8px;
  margin-left: 6px;
  border: 1px solid transparent;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
}
.agent:hover {
  background: var(--panel-2);
  border-color: var(--border);
}
.agent:focus-visible {
  outline: none;
  border-color: var(--border-2);
}
.agent.selected {
  background: var(--panel-3);
  border-color: var(--primary);
}
.dot {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  margin-top: 4px;
  border-radius: 50%;
  background: var(--muted);
}
.agent-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.agent-top {
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
}
.role {
  color: var(--text);
  font-weight: 500;
}
.rev {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--cyan);
}
.cur {
  font-size: 10px;
  color: var(--green);
}
.agent-sub {
  display: flex;
  gap: 8px;
  font-size: 11px;
}
.model {
  font-family: var(--mono);
}
.muted {
  color: var(--muted);
}
</style>
