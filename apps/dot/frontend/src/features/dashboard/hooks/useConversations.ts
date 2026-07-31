import { useCallback, useEffect, useRef, useState } from 'react'

import {
  getConversations,
  getArchivedConversations,
  searchMessages,
  createConversation as apiCreateConversation,
  renameConversation as apiRenameConversation,
  deleteConversation as apiDeleteConversation,
  type ConversationSummary,
} from '@/lib/chat/client'

const LAST_CONVERSATION_KEY = 'dot.lastConversationId'

function saveConversationId(id: string): void {
  try {
    window.localStorage.setItem(LAST_CONVERSATION_KEY, id)
  } catch {
    // localStorage no disponible (modo incógnito, storage lleno, etc.)
  }
}

function removeSavedConversationId(): void {
  try {
    window.localStorage.removeItem(LAST_CONVERSATION_KEY)
  } catch {
    // ignorar
  }
}

export type UseConversationsOptions = {
  getAccessToken: () => Promise<string | null>
}

export type UseConversationsResult = {
  conversations: ConversationSummary[]
  activeId: string | null
  isLoading: boolean
  isSearching: boolean
  searchQuery: string
  searchSnippets: Record<string, string>
  selectConversation: (id: string) => Promise<void>
  createConversation: (title?: string, channel?: string) => Promise<string>
  renameConversation: (id: string, title: string) => Promise<void>
  deleteConversation: (id: string) => Promise<void>
  refresh: () => Promise<void>
  searchConversations: (query: string, archived?: boolean) => Promise<void>
}

export function useConversations({
  getAccessToken,
}: UseConversationsOptions): UseConversationsResult {
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isSearching, setIsSearching] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchSnippets, setSearchSnippets] = useState<Record<string, string>>({})
  const inFlightRef = useRef(false)
  const searchRequestRef = useRef(0)
  const searchQueryRef = useRef('')

  const loadAllConversations = useCallback(async () => {
    if (inFlightRef.current) return
    inFlightRef.current = true
    try {
      const token = await getAccessToken()
      const list = await getConversations(token)
      setConversations(list)
    } catch (e) {
      console.warn('[useConversations] Error al cargar conversaciones:', e)
    } finally {
      inFlightRef.current = false
      setIsLoading(false)
    }
  }, [getAccessToken])

  const searchConversations = useCallback(
    async (query: string, archived = false) => {
      const trimmed = query.trim()
      setSearchQuery(trimmed)
      searchQueryRef.current = trimmed

      if (!trimmed) {
        setSearchSnippets({})
        if (!archived) {
          await loadAllConversations()
        }
        return
      }

      const requestId = ++searchRequestRef.current
      setIsSearching(true)
      try {
        const token = await getAccessToken()
        const fetchList = archived
          ? getArchivedConversations(token, trimmed)
          : getConversations(token, trimmed)
        const [list, messageSearch] = await Promise.all([
          fetchList,
          trimmed.length >= 2 ? searchMessages(trimmed, token) : Promise.resolve(null),
        ])

        if (requestId !== searchRequestRef.current) return

        setConversations(list)

        const snippets: Record<string, string> = {}
        if (messageSearch?.results) {
          for (const hit of messageSearch.results) {
            if (!snippets[hit.conversation_id]) {
              snippets[hit.conversation_id] = hit.snippet
            }
          }
        }
        setSearchSnippets(snippets)
      } catch (e) {
        if (requestId === searchRequestRef.current) {
          console.warn('[useConversations] Error al buscar conversaciones:', e)
        }
      } finally {
        if (requestId === searchRequestRef.current) {
          setIsSearching(false)
        }
      }
    },
    [getAccessToken, loadAllConversations],
  )

  const refresh = useCallback(async () => {
    if (searchQueryRef.current.trim()) {
      await searchConversations(searchQueryRef.current)
      return
    }
    setSearchSnippets({})
    await loadAllConversations()
  }, [loadAllConversations, searchConversations])

  useEffect(() => {
    void loadAllConversations()
  }, [loadAllConversations])

  const selectConversation = useCallback(async (id: string) => {
    setActiveId(id)
    saveConversationId(id)
  }, [])

  const createConversation = useCallback(
    async (title?: string, channel: string = 'pc'): Promise<string> => {
      const token = await getAccessToken()
      const conv = await apiCreateConversation(title, token, channel)
      setConversations((prev) => [conv, ...prev])
      setActiveId(conv.id)
      saveConversationId(conv.id)
      return conv.id
    },
    [getAccessToken],
  )

  const renameConversation = useCallback(
    async (id: string, title: string) => {
      const token = await getAccessToken()
      const updated = await apiRenameConversation(id, title, token)
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? { ...c, title: updated.title } : c)),
      )
    },
    [getAccessToken],
  )

  const deleteConversation = useCallback(
    async (id: string) => {
      const token = await getAccessToken()
      await apiDeleteConversation(id, token)
      setConversations((prev) => prev.filter((c) => c.id !== id))
      if (activeId === id) {
        setActiveId(null)
        removeSavedConversationId()
      }
    },
    [getAccessToken, activeId],
  )

  return {
    conversations,
    activeId,
    isLoading,
    isSearching,
    searchQuery,
    searchSnippets,
    selectConversation,
    createConversation,
    renameConversation,
    deleteConversation,
    refresh,
    searchConversations,
  }
}
