import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { TaskConversations, ConversationMessage } from '@/types/api'
import { api } from '@/api/client'
import { useToastStore } from './toast'
import { i18n } from '@/i18n'
const t = i18n.global.t

export const useConversationStore = defineStore('conversation', () => {
  const tree = ref<TaskConversations | null>(null)
  const loadingTree = ref(false)
  const loadingMessages = ref(false)
  const messagesCache = ref<Map<string, ConversationMessage[]>>(new Map())
  // Count in-flight fetches so concurrent (e.g. default-select + a quick reselect)
  // calls don't clear `loadingMessages` while another is still running.
  let inFlight = 0

  async function loadTree(id: string): Promise<TaskConversations | null> {
    loadingTree.value = true
    try {
      const conversations = await api.taskConversations(id)
      tree.value = conversations
      return conversations
    } catch (e: unknown) {
      useToastStore().add('error', t('conversation.convosLoadError', { error: e instanceof Error ? e.message : String(e) }))
      tree.value = null
      return null
    } finally {
      loadingTree.value = false
    }
  }

  function cacheKey(dir: string, stream: string): string { return `${dir}::${stream}` }

  async function fetchMessages(dir: string, stream: string, force = false): Promise<ConversationMessage[]> {
    const key = cacheKey(dir, stream)
    const cached = messagesCache.value.get(key)
    if (!force && cached) return cached
    inFlight += 1
    loadingMessages.value = true
    try {
      const msgs = await api.iterConversation(dir, stream)
      messagesCache.value.set(key, msgs)
      return msgs
    } catch (e: unknown) {
      useToastStore().add('error', t('conversation.messagesLoadError', { error: e instanceof Error ? e.message : String(e) }))
      return []
    } finally {
      inFlight = Math.max(0, inFlight - 1)
      loadingMessages.value = inFlight > 0
    }
  }

  function clear(): void {
    tree.value = null
    messagesCache.value = new Map()
  }

  return { tree, loadingTree, loadingMessages, loadTree, fetchMessages, clear }
})
