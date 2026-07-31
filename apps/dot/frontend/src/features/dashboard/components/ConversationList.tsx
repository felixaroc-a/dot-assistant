import { useCallback, useState, useRef, useEffect, memo } from 'react'

import type { ConversationSummary } from '@/lib/chat/client'

import './conversation-list.css'

type MenuState =
  | { type: 'idle' }
  | { type: 'menu'; id: string }
  | { type: 'renaming'; id: string }
  | { type: 'deleting'; id: string }

function formatRelativeDate(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  const diffHour = Math.floor(diffMs / 3600000)
  const diffDay = Math.floor(diffMs / 86400000)

  if (diffMin < 1) return 'Ahora'
  if (diffMin < 60) return `Hace ${diffMin} min`
  if (diffHour < 24) return `Hace ${diffHour}h`
  if (diffDay < 7) return `Hace ${diffDay}d`
  return date.toLocaleDateString('es-ES', { day: 'numeric', month: 'short' })
}

/**
 * Resalta las ocurrencias de query en text (case-insensitive).
 * Retorna un array de strings y elementos <mark>.
 */
function highlightMatch(text: string, query: string): React.ReactNode {
  if (!query) return text
  const lowerText = text.toLowerCase()
  const lowerQuery = query.toLowerCase()
  const parts: React.ReactNode[] = []
  let lastIndex = 0
  let idx = lowerText.indexOf(lowerQuery, lastIndex)
  while (idx >= 0) {
    if (idx > lastIndex) {
      parts.push(text.slice(lastIndex, idx))
    }
    parts.push(
      <mark key={idx} className="conv-list__highlight">
        {text.slice(idx, idx + query.length)}
      </mark>,
    )
    lastIndex = idx + query.length
    idx = lowerText.indexOf(lowerQuery, lastIndex)
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }
  return parts.length > 0 ? parts : text
}

function ConversationItem({
  conv,
  isActive,
  menuState,
  onOpenMenu,
  onToggleMenu,
  onRename,
  onDelete,
  onSelect,
  onUnarchive,
  unreadCount = 0,
  searchQuery = '',
  matchSnippet = '',
  isArchived = false,
}: {
  conv: ConversationSummary
  isActive: boolean
  menuState: MenuState
  onOpenMenu: (id: string) => void
  onToggleMenu: (id: string) => void
  onRename: (id: string, title: string) => Promise<void>
  onDelete: (id: string) => Promise<void>
  onSelect: (id: string) => void
  onUnarchive?: (id: string) => Promise<void>
  unreadCount?: number
  searchQuery?: string
  matchSnippet?: string
  isArchived?: boolean
}) {
  const [renameValue, setRenameValue] = useState(conv.title)
  const inputRef = useRef<HTMLInputElement>(null)

  const isRenaming = menuState.type === 'renaming' && menuState.id === conv.id
  const isDeleting = menuState.type === 'deleting' && menuState.id === conv.id
  const isMenuOpen = menuState.type === 'menu' && menuState.id === conv.id
  const isWhatsApp = conv.channel === 'whatsapp'

  const handleRenameSubmit = useCallback(() => {
    const trimmed = renameValue.trim()
    if (trimmed && trimmed !== conv.title) {
      void onRename(conv.id, trimmed)
    }
  }, [renameValue, conv.id, conv.title, onRename])

  const displayTitle = conv.title || 'Nueva conversación'
  const titleContent = searchQuery ? highlightMatch(displayTitle, searchQuery) : displayTitle

  return (
    <div
      className={`conv-list__item${isActive ? ' conv-list__item--active' : ''}${isArchived ? ' conv-list__item--archived' : ''}`}
      onClick={() => onSelect(conv.id)}
      onContextMenu={(e) => {
        e.preventDefault()
        onOpenMenu(conv.id)
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelect(conv.id)
        }
      }}
    >
      <div className="conv-list__item-content">
        {isRenaming ? (
          <input
            ref={inputRef}
            className="conv-list__rename-input"
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onBlur={handleRenameSubmit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                handleRenameSubmit()
              } else if (e.key === 'Escape') {
                setRenameValue(conv.title)
                onOpenMenu(conv.id)
              }
            }}
            autoFocus
            maxLength={200}
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <>
            <div className="conv-list__item-header">
              <span className="conv-list__item-title">
                {isWhatsApp ? (
                  <span className="conv-list__channel-badge conv-list__channel-badge--whatsapp" title="WhatsApp">
                    WA
                  </span>
                ) : null}
                {isArchived ? (
                  <span className="conv-list__channel-badge conv-list__channel-badge--archived" title="Archivada">
                    A
                  </span>
                ) : null}
                {titleContent}
                {isWhatsApp && unreadCount > 0 ? (
                  <span
                    className="conv-list__unread-badge"
                    title={`${unreadCount} mensaje(s) nuevo(s)`}
                  >
                    {unreadCount > 99 ? '99+' : unreadCount}
                  </span>
                ) : null}
              </span>
              <div className="conv-list__item-actions">
                <span className="conv-list__item-date">{formatRelativeDate(conv.updated_at)}</span>
                <button
                  type="button"
                  className="conv-list__menu-trigger"
                  aria-label="Opciones de conversación"
                  aria-haspopup="menu"
                  aria-expanded={isMenuOpen}
                  onClick={(e) => {
                    e.stopPropagation()
                    onToggleMenu(conv.id)
                  }}
                >
                  ⋯
                </button>
              </div>
            </div>
            {isWhatsApp ? (
              <span className="conv-list__channel-label">WhatsApp</span>
            ) : null}
            {matchSnippet ? (
              <span className="conv-list__match-snippet" title={matchSnippet}>
                {searchQuery ? highlightMatch(matchSnippet, searchQuery) : matchSnippet}
              </span>
            ) : null}
          </>
        )}
      </div>

      {isMenuOpen && !isRenaming && !isDeleting ? (
        <div className="conv-list__menu" onClick={(e) => e.stopPropagation()} role="menu">
          {isArchived ? (
            <button
              type="button"
              className="conv-list__menu-btn"
              onClick={() => onUnarchive?.(conv.id)}
              role="menuitem"
            >
              Restaurar
            </button>
          ) : (
            <>
              <button
                type="button"
                className="conv-list__menu-btn"
                onClick={() => onOpenMenu(`renaming:${conv.id}`)}
                role="menuitem"
              >
                Renombrar
              </button>
              <button
                type="button"
                className="conv-list__menu-btn conv-list__menu-btn--danger"
                onClick={() => onOpenMenu(`deleting:${conv.id}`)}
                role="menuitem"
              >
                Archivar
              </button>
            </>
          )}
        </div>
      ) : null}

      {isDeleting ? (
        <div className="conv-list__confirm" onClick={(e) => e.stopPropagation()}>
          <span className="conv-list__confirm-text">¿Archivar esta conversación?</span>
          <div className="conv-list__confirm-actions">
            <button
              type="button"
              className="conv-list__confirm-btn conv-list__confirm-btn--yes"
              onClick={() => void onDelete(conv.id)}
            >
              Archivar
            </button>
            <button
              type="button"
              className="conv-list__confirm-btn"
              onClick={() => onOpenMenu(conv.id)}
            >
              Cancelar
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

export type ConversationListProps = {
  conversations: ConversationSummary[]
  activeId: string | null
  isLoading?: boolean
  isSearching?: boolean
  searchSnippets?: Record<string, string>
  onSearchChange?: (query: string) => void
  onSelect: (id: string) => Promise<void>
  onNew: () => void
  onRename: (id: string, title: string) => Promise<void>
  onDelete: (id: string) => Promise<void>
  onUnarchive?: (id: string) => Promise<void>
  onToggleArchived?: () => void
  showingArchived?: boolean
  whatsappUnreadCount?: number
}

export const ConversationList = memo(function ConversationList({
  conversations,
  activeId,
  isLoading = false,
  isSearching = false,
  searchSnippets = {},
  onSearchChange,
  onSelect,
  onNew,
  onRename,
  onDelete,
  onUnarchive,
  onToggleArchived,
  showingArchived = false,
  whatsappUnreadCount = 0,
}: ConversationListProps) {
  const [menuState, setMenuState] = useState<MenuState>({ type: 'idle' })
  const [rawSearchQuery, setRawSearchQuery] = useState('')
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState('')
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // CH06: Debounce 300ms en búsqueda
  const handleSearchChange = useCallback((value: string) => {
    setRawSearchQuery(value)
    if (debounceRef.current) {
      clearTimeout(debounceRef.current)
    }
    debounceRef.current = setTimeout(() => {
      const trimmed = value.trim()
      setDebouncedSearchQuery(trimmed)
      onSearchChange?.(trimmed)
    }, 300)
  }, [onSearchChange])

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  const handleOpenMenu = useCallback((idOrAction: string) => {
    if (idOrAction.startsWith('renaming:')) {
      setMenuState({ type: 'renaming', id: idOrAction.slice(9) })
    } else if (idOrAction.startsWith('deleting:')) {
      setMenuState({ type: 'deleting', id: idOrAction.slice(9) })
    } else {
      setMenuState({ type: 'menu', id: idOrAction })
    }
  }, [])

  const handleToggleMenu = useCallback((id: string) => {
    setMenuState((prev) =>
      prev.type === 'menu' && prev.id === id ? { type: 'idle' } : { type: 'menu', id },
    )
  }, [])

  const handleSelect = useCallback(
    (id: string) => {
      setMenuState({ type: 'idle' })
      void onSelect(id)
    },
    [onSelect],
  )

  const handleRename = useCallback(
    async (id: string, title: string) => {
      await onRename(id, title)
      setMenuState({ type: 'idle' })
    },
    [onRename],
  )

  const handleDelete = useCallback(
    async (id: string) => {
      await onDelete(id)
      setMenuState({ type: 'idle' })
    },
    [onDelete],
  )

  const sortedConvs = [...conversations].sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  )

  const showInitialSkeleton = isLoading && conversations.length === 0 && !rawSearchQuery

  return (
    <aside className="conv-list" aria-label="Conversaciones">
      <div className="conv-list__header">
        <h2 className="conv-list__title">
          {showingArchived ? 'Archivadas' : 'Conversaciones'}
        </h2>
        <input
          type="search"
          className="conv-list__search"
          placeholder={
            showingArchived
              ? 'Buscar archivadas por título o mensajes…'
              : 'Buscar por título o mensajes…'
          }
          value={rawSearchQuery}
          onChange={(e) => handleSearchChange(e.target.value)}
          aria-label="Buscar conversaciones por título o contenido"
        />
        <div className="conv-list__search-hint">
          {isSearching
            ? 'Buscando en tu historial…'
            : 'Ej.: «¿qué te pedí la semana pasada?» — busca en título y mensajes'}
        </div>
      </div>
      <div className="conv-list__actions-row">
        {!showingArchived ? (
          <button type="button" className="conv-list__new-btn" onClick={onNew}>
            + Nueva conversación
          </button>
        ) : null}
        {onToggleArchived ? (
          <button
            type="button"
            className="conv-list__toggle-archived-btn"
            onClick={onToggleArchived}
          >
            {showingArchived ? '← Ver activas' : 'Ver archivadas'}
          </button>
        ) : null}
      </div>
      <div className="conv-list__scroll">
        {showInitialSkeleton ? (
          <div className="conv-list__skeleton" aria-busy="true" aria-label="Cargando conversaciones">
            {[1, 2, 3].map((n) => (
              <div key={n} className="conv-list__skeleton-item" />
            ))}
          </div>
        ) : conversations.length === 0 && !rawSearchQuery ? (
          <div className="conv-list__empty-state">
            <div className="conv-list__empty-icon">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" aria-hidden>
                <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
              </svg>
            </div>
            <p className="conv-list__empty-title">
              {showingArchived ? 'No hay conversaciones archivadas' : 'No hay conversaciones aún'}
            </p>
            <p className="conv-list__empty-desc">
              {showingArchived
                ? 'Las conversaciones que archives aparecerán aquí.'
                : 'Crea una nueva conversación para empezar a chatear con DOT.'}
            </p>
          </div>
        ) : sortedConvs.length === 0 ? (
          <div className="conv-list__empty-state">
            <div className="conv-list__empty-icon">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" aria-hidden>
                <circle cx="11" cy="11" r="8" />
                <path d="M21 21l-4.35-4.35" />
              </svg>
            </div>
            <p className="conv-list__empty-title">Sin resultados para tu búsqueda</p>
            <p className="conv-list__empty-desc">
              Prueba con palabras clave de lo que pediste o del tema del chat.
            </p>
          </div>
        ) : (
          sortedConvs.map((conv) => (
            <ConversationItem
              key={conv.id}
              conv={conv}
              isActive={activeId === conv.id}
              menuState={menuState}
              onOpenMenu={handleOpenMenu}
              onToggleMenu={handleToggleMenu}
              onRename={handleRename}
              onDelete={handleDelete}
              onSelect={handleSelect}
              onUnarchive={onUnarchive}
              unreadCount={conv.channel === 'whatsapp' ? whatsappUnreadCount : 0}
              searchQuery={debouncedSearchQuery}
              matchSnippet={searchSnippets[conv.id] ?? ''}
              isArchived={showingArchived}
            />
          ))
        )}
      </div>
    </aside>
  )
})

