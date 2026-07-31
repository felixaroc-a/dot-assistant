import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type { ChatError, ChatMessage, SendMessageOptions } from '@/lib/chat/types'
import { AttachmentPreview } from './FileAttachment'
import { ChatComposer } from './ChatComposer'
import { ChatMessageBubble } from './ChatMessageBubble'
import { QuickTips } from './QuickTips'
import { validateVisionImage } from './visionImageValidation'
import {
  hasImageGenerationIntent,
  IMAGE_GEN_DRAFT_PREFIX,
} from './imageGenerationIntent'
import { ModelSelector, type AvailableModel } from './ModelSelector'

import './chat-attachments.css'

const DROP_OVERLAY_LABEL = 'Suelta la imagen o documento aquí'

function mimeFromFilename(name: string): string {
  const lower = name.toLowerCase()
  if (lower.endsWith('.pdf')) return 'application/pdf'
  if (lower.endsWith('.docx')) {
    return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  }
  if (lower.endsWith('.txt') || lower.endsWith('.md') || lower.endsWith('.csv')) {
    return 'text/plain'
  }
  return 'application/octet-stream'
}

function hasFileDrag(dataTransfer?: DataTransfer | null): boolean {
  if (!dataTransfer) return false
  const types = dataTransfer.types
  if (!types) return false
  for (let i = 0; i < types.length; i += 1) {
    if (types[i] === 'Files') return true
  }
  return false
}

function getFileFromDataTransfer(dataTransfer?: DataTransfer | null): File | null {
  if (!dataTransfer) return null
  if (dataTransfer.files && dataTransfer.files.length) {
    return dataTransfer.files[0] ?? null
  }
  const items = dataTransfer.items
  if (!items) return null
  for (let index = 0; index < items.length; index += 1) {
    const item = items[index]
    if (item?.kind === 'file') {
      const file = item.getAsFile?.()
      if (file) return file
    }
  }
  return null
}

export type DotChatPanelProps = {
  messages: ChatMessage[]
  isSending: boolean
  canExportConversation?: boolean
  isExportingConversation?: boolean
  exportingFormat?: 'docx' | 'pdf' | null
  lastError: ChatError | null
  conversationId?: string | null
  conversationTitle?: string
  conversationChannel?: string
  onRenameConversation?: (title: string) => Promise<void>
  getAccessToken: () => Promise<string | null>
  onClearError: () => void
  onSend: (text: string, options?: SendMessageOptions) => void
  onSendImage: (file: File, prompt: string) => Promise<void>
  onGenerateImage: (text: string) => Promise<void>
  onExportConversation?: (format: 'docx' | 'pdf') => void
  /** A07: modo WhatsApp manual activado */
  whatsappMode?: boolean
  /** A07: toggle manual entre canal PC y WhatsApp */
  onToggleWhatsappMode?: () => void
  /** A07: si WhatsApp está vinculado (muestra el toggle) */
  whatsappModeAvailable?: boolean
  /** SP05: ocultar botón generar imagen si feature flag=false */
  imageGenEnabled?: boolean
  /** B06: TTS — voz configurada (GEMINI_API_KEY presente) */
  voiceTtsAvailable?: boolean
  /** B06: STT — dictado disponible en el servidor */
  voiceSttAvailable?: boolean
  /** Abrir panel Configuración cuando la voz no está lista */
  onOpenAppSettings?: () => void
  /** Abrir drawer Google (reconectar scope Drive) */
  onOpenGoogleIntegrations?: () => void
  /** Traducir texto de una burbuja en un clic */
  onTranslateText?: (text: string) => Promise<void>
  /** Resumir texto de una burbuja en un clic */
  onSummarizeText?: (text: string) => Promise<void>
  /** B06: TTS — loading mientras se sintetiza un mensaje específico */
  ttsLoadingMessageId?: string | null
  /** B06: TTS — callback para sintetizar y reproducir */
  onTextToSpeech?: (text: string, messageId: string) => void
  /** TTS auto: DOT lee respuestas al terminar */
  dotSpeaksEnabled?: boolean
  /** TTS auto: toggle "DOT habla" */
  onToggleDotSpeaks?: () => void
  /** TTS: reproduciendo audio ahora */
  ttsPlaying?: boolean
  /** VOX: Talk Mode — conversación por voz activada */
  talkMode?: boolean
  /** VOX: toggle talk mode on/off */
  onToggleTalkMode?: () => void
  /** VOX: estado del modo escucha para feedback visual */
  wakeWordState?: 'idle' | 'listening' | 'detected' | 'speaking' | 'denied' | 'error'
  /** VOX: activa detección de voz (modo escucha) */
  onStartWakeWord?: () => void
  /** VOX: desactiva detección de voz (modo escucha) */
  onStopWakeWord?: () => void
  reasoningEnabled?: boolean
  reasoningLevel?: 'low' | 'medium' | 'high' | 'auto'
  onReasoningEnabledChange?: (enabled: boolean) => void
  onReasoningLevelChange?: (level: 'low' | 'medium' | 'high' | 'auto') => void
  /** Modelo IA preferido (id del modelo) */
  preferredModel?: string
  /** Modelos disponibles cargados desde GET /v1/models */
  availableModels?: AvailableModel[]
  /** Callback al cambiar de modelo */
  onPreferredModelChange?: (modelId: string) => void
  /** Inicia un chat nuevo (multi-chat) */
  onNewChat?: () => void
  /** Bloqueo IA al 100% */
  usageBlocked?: boolean
  usageBlockedMessage?: string
}

const CMD_SUGGESTIONS = [
  { cmd: '/doc', desc: 'Crear documento' },
  { cmd: '/imagen', desc: 'Generar imagen con IA' },
  { cmd: '/agenda', desc: 'Ver agenda de hoy' },
  { cmd: '/correo', desc: 'Correos sin leer' },
  { cmd: '/responder', desc: 'Responder correo' },
  { cmd: '/archivar', desc: 'Archivar correos' },
  { cmd: '/adjuntos', desc: 'Descargar adjuntos Gmail' },
  { cmd: '/recordar', desc: 'Programar recordatorio' },
  { cmd: '/buscar', desc: 'Buscar en internet' },
  { cmd: '/traducir', desc: 'Traducir texto' },
  { cmd: '/resumir', desc: 'Resumir texto' },
  { cmd: '/analizar', desc: 'Analizar Excel local' },
  { cmd: '/leer', desc: 'Leer archivo local' },
  { cmd: '/escribir', desc: 'Guardar archivo local' },
  { cmd: '/listar', desc: 'Listar archivos locales' },
]

export function DotChatPanel({
  messages,
  isSending,
  canExportConversation = false,
  isExportingConversation = false,
  exportingFormat = null,
  lastError,
  conversationId,
  conversationTitle,
  conversationChannel,
  onRenameConversation,
  getAccessToken,
  onClearError,
  onSend,
  onSendImage,
  onGenerateImage,
  onExportConversation,
  whatsappMode = false,
  onToggleWhatsappMode,
  whatsappModeAvailable = false,
  imageGenEnabled = true,
  voiceTtsAvailable = false,
  voiceSttAvailable = true,
  onOpenAppSettings,
  onOpenGoogleIntegrations,
  onTranslateText,
  onSummarizeText,
  ttsLoadingMessageId = null,
  onTextToSpeech,
  dotSpeaksEnabled = false,
  onToggleDotSpeaks,
  ttsPlaying = false,
  talkMode = false,
  onToggleTalkMode,
  wakeWordState = 'idle',
  onStartWakeWord,
  onStopWakeWord,
  reasoningEnabled = false,
  reasoningLevel = 'auto',
  onReasoningEnabledChange,
  onReasoningLevelChange,
  preferredModel,
  availableModels = [],
  onPreferredModelChange,
  onNewChat,
  usageBlocked = false,
  usageBlockedMessage,
}: DotChatPanelProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [draft, setDraft] = useState('')
  const [activeSuggestionIndex, setActiveSuggestionIndex] = useState(0)
  const [selectedImage, setSelectedImage] = useState<File | null>(null)
  const [selectedDocument, setSelectedDocument] = useState<{
    file: File
    name: string
    text: string
  } | null>(null)
  const [isParsingDocument, setIsParsingDocument] = useState(false)
  const [isDragActive, setIsDragActive] = useState(false)
  const dragCounterRef = useRef(0)

  // B01: título editable
  const isEditingTitle = useRef(false)
  const [editTitleValue, setEditTitleValue] = useState(conversationTitle || '')
  const titleInputRef = useRef<HTMLInputElement>(null)
  const [showEditTitle, setShowEditTitle] = useState(false)

  useEffect(() => {
    setEditTitleValue(conversationTitle || '')
    setShowEditTitle(false)
    isEditingTitle.current = false
    // A11y: auto-focus en el textarea al abrir una conversación
    requestAnimationFrame(() => textareaRef.current?.focus())
  }, [conversationTitle, conversationId])

  const handleStartEditTitle = useCallback(() => {
    setShowEditTitle(true)
    setEditTitleValue(conversationTitle || '')
    isEditingTitle.current = true
    requestAnimationFrame(() => titleInputRef.current?.focus())
  }, [conversationTitle])

  const handleSubmitTitle = useCallback(() => {
    const trimmed = editTitleValue.trim()
    if (trimmed && trimmed !== conversationTitle && onRenameConversation) {
      void onRenameConversation(trimmed)
    }
    setShowEditTitle(false)
    isEditingTitle.current = false
  }, [editTitleValue, conversationTitle, onRenameConversation])

  const handleTitleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') {
        e.preventDefault()
        handleSubmitTitle()
      } else if (e.key === 'Escape') {
        setEditTitleValue(conversationTitle || '')
        setShowEditTitle(false)
        isEditingTitle.current = false
      }
    },
    [handleSubmitTitle, conversationTitle],
  )

  const normalizedDraft = draft.trimStart()
  const isSlashMode = normalizedDraft.startsWith('/')
  const slashBody = isSlashMode ? normalizedDraft.slice(1) : ''
  const hasCommandArgs = slashBody.includes(' ')

  const filteredSuggestions = useMemo(() => {
    if (!isSlashMode || hasCommandArgs) return []
    const commandQuery = slashBody.toLowerCase()
    if (!commandQuery) return CMD_SUGGESTIONS
    return CMD_SUGGESTIONS.filter(
      (suggestion) =>
        suggestion.cmd.slice(1).includes(commandQuery) ||
        suggestion.desc.toLowerCase().includes(commandQuery),
    )
  }, [hasCommandArgs, isSlashMode, slashBody])

  const showSuggestions = filteredSuggestions.length > 0
  const hasExactSuggestionMatch = showSuggestions
    ? filteredSuggestions.some((suggestion) => suggestion.cmd === normalizedDraft)
    : false

  useEffect(() => {
    if (!showSuggestions) {
      setActiveSuggestionIndex(0)
      return
    }
    setActiveSuggestionIndex((prev) => Math.min(prev, filteredSuggestions.length - 1))
  }, [filteredSuggestions.length, showSuggestions])

  useEffect(() => {
    const container = messagesEndRef.current?.parentElement
    if (!container) return

    // Solo hace auto-scroll si el usuario está cerca del final (margen 50px)
    const isNearBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight < 50

    if (!isNearBottom) return

    const node = messagesEndRef.current
    if (node && typeof node.scrollIntoView === 'function') {
      node.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [messages, isSending])

  const handleImageSelected = useCallback((file: File) => {
    setSelectedImage(file)
  }, [])

  const handleRemoveImage = useCallback(() => {
    setSelectedImage(null)
  }, [])

  const handleRemoveDocument = useCallback(() => {
    setSelectedDocument(null)
    setIsParsingDocument(false)
  }, [])

  const handleDocumentSelected = useCallback(
    (file: File) => {
      if (isSending || isParsingDocument) return
      // Si es imagen, rutear al flujo de imágenes
      if (file.type.startsWith('image/')) {
        handleImageSelected(file)
        return
      }
      setIsParsingDocument(true)
      setSelectedDocument(null)

      const filePath = (file as unknown as { path?: string }).path
      const parser = window.desktop?.documentParser

      if (!parser) {
        alert('El lector de documentos solo está disponible en la app de escritorio.')
        setIsParsingDocument(false)
        return
      }

      // Si tenemos ruta de archivo (seleccionado vía diálogo), usar parse directo
      if (filePath) {
        parser.parse(filePath, file.type).then((result) => {
          setIsParsingDocument(false)
          if (result.ok) {
            setSelectedDocument({ file, name: file.name, text: result.text })
          } else {
            alert((result as { ok: false; error: string }).error || 'No se pudo extraer texto del documento.')
          }
        }).catch((err: unknown) => {
          setIsParsingDocument(false)
          alert('Error al procesar el documento: ' + String(err))
        })
        return
      }

      // Drag-drop: leer el archivo como ArrayBuffer y enviar base64 al main process
      const reader = new FileReader()
      reader.onload = () => {
        const base64 = (reader.result as string).split(',')[1]
        if (!base64) {
          setIsParsingDocument(false)
          alert('No se pudo leer el archivo.')
          return
        }
        parser.parseFromData(base64, file.type).then((result) => {
          setIsParsingDocument(false)
          if (result.ok) {
            setSelectedDocument({ file, name: file.name, text: result.text })
          } else {
            alert((result as { ok: false; error: string }).error || 'No se pudo extraer texto del documento.')
          }
        }).catch((err: unknown) => {
          setIsParsingDocument(false)
          alert('Error al procesar el documento: ' + String(err))
        })
      }
      reader.onerror = () => {
        setIsParsingDocument(false)
        alert('Error al leer el archivo.')
      }
      reader.readAsDataURL(file)
    },
    [handleImageSelected, isParsingDocument, isSending],
  )

  const processIncomingFile = useCallback(
    (file: File | null) => {
      if (!file || isSending) return
      // Si es imagen, validar y mostrar preview
      if (file.type.startsWith('image/')) {
        const validationError = validateVisionImage(file)
        if (validationError) {
          alert(validationError)
          return
        }
        handleImageSelected(file)
        return
      }
      // Si es documento, parsear y extraer texto
      handleDocumentSelected(file)
    },
    [handleDocumentSelected, handleImageSelected, isSending],
  )

  const handleDragEnter = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    if (!hasFileDrag(event.dataTransfer)) return
    event.preventDefault()
    dragCounterRef.current += 1
    setIsDragActive(true)
  }, [])

  const handleDragOver = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    if (!hasFileDrag(event.dataTransfer)) return
    event.preventDefault()
  }, [])

  const handleDragLeave = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    if (!hasFileDrag(event.dataTransfer)) return
    event.preventDefault()
    dragCounterRef.current = Math.max(0, dragCounterRef.current - 1)
    if (dragCounterRef.current === 0) {
      setIsDragActive(false)
    }
  }, [])

  const handleDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      if (!hasFileDrag(event.dataTransfer)) return
      event.preventDefault()
      event.stopPropagation()
      dragCounterRef.current = 0
      setIsDragActive(false)

      const file = getFileFromDataTransfer(event.dataTransfer)
      processIncomingFile(file)
    },
    [processIncomingFile],
  )

  const handlePasteImage = useCallback(
    (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
      const file = getFileFromDataTransfer(event.clipboardData)
      if (!file) return
      event.preventDefault()
      processIncomingFile(file)
    },
    [processIncomingFile],
  )

  const handleSend = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed && !selectedImage && !selectedDocument) return
      if (isSending) return
      setDraft('')

      if (selectedImage) {
        try {
          await onSendImage(selectedImage, trimmed)
          setSelectedImage(null)
        } catch {
          // Mantener la imagen para reintentos, el banner ya mostrará el error.
        }
        return
      }

      if (selectedDocument) {
        const docHeader = `[Documento: ${selectedDocument.name}]\n\nContenido extraído:\n${selectedDocument.text}`
        const apiText = trimmed
          ? `${docHeader}\n\n---\nInstrucción del usuario: ${trimmed}`
          : docHeader
        const displayText = trimmed || 'Documento adjunto'
        const attachment = {
          name: selectedDocument.name,
          type: selectedDocument.file.type || mimeFromFilename(selectedDocument.name),
          size: selectedDocument.file.size,
        }
        setSelectedDocument(null)
        onSend(apiText, { displayText, attachment })
        return
      }

      if (trimmed && hasImageGenerationIntent(trimmed)) {
        try {
          await onGenerateImage(trimmed)
        } catch {
          // El banner ya mostrará el error.
        }
        return
      }

      onSend(trimmed)
    },
    [isSending, onGenerateImage, onSend, onSendImage, selectedDocument, selectedImage],
  )

  const handlePrepareImageGeneration = useCallback(() => {
    setDraft(IMAGE_GEN_DRAFT_PREFIX)
    requestAnimationFrame(() => textareaRef.current?.focus())
  }, [])

  const handleGenerateImage = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed || isSending) return
      setDraft('')
      try {
        await onGenerateImage(trimmed)
      } catch {
        // El banner ya mostrará el error.
      }
    },
    [isSending, onGenerateImage],
  )

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (showSuggestions && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
        e.preventDefault()
        const delta = e.key === 'ArrowDown' ? 1 : -1
        setActiveSuggestionIndex((prev) => {
          const next = prev + delta
          if (next < 0) return filteredSuggestions.length - 1
          if (next >= filteredSuggestions.length) return 0
          return next
        })
        return
      }

      if (e.key === 'Enter' && !e.shiftKey) {
        if (showSuggestions && !hasExactSuggestionMatch) {
          e.preventDefault()
          const selected = filteredSuggestions[activeSuggestionIndex] ?? filteredSuggestions[0]
          if (selected) {
            setDraft(`${selected.cmd} `)
            requestAnimationFrame(() => textareaRef.current?.focus())
          }
          return
        }

        e.preventDefault()
        handleSend(draft)
      }
    },
    [
      activeSuggestionIndex,
      draft,
      filteredSuggestions,
      handleSend,
      hasExactSuggestionMatch,
      showSuggestions,
    ],
  )

  const handleCmdClick = useCallback((cmd: string) => {
    setDraft(`${cmd} `)
    textareaRef.current?.focus()
  }, [])

  return (
    <div
      className={`dot-chat${isDragActive ? ' dot-chat--drag-active' : ''}`}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {isDragActive ? (
        <div className="dot-chat__drop-overlay" aria-hidden>
          <span>{DROP_OVERLAY_LABEL}</span>
        </div>
      ) : null}
      <div className="dot-chat__toolbar">
        <div className="dot-chat__toolbar-title-row">
          {conversationChannel === 'whatsapp' ? (
            <span className="dot-chat__channel-badge dot-chat__channel-badge--whatsapp">WhatsApp</span>
          ) : null}
          {showEditTitle ? (
            <input
              ref={titleInputRef}
              className="dot-chat__title-input"
              value={editTitleValue}
              onChange={(e) => setEditTitleValue(e.target.value)}
              onBlur={handleSubmitTitle}
              onKeyDown={handleTitleKeyDown}
              maxLength={200}
              onClick={(e) => e.stopPropagation()}
            />
          ) : (
            <h3
              className="dot-chat__toolbar-title dot-chat__toolbar-title--editable"
              onClick={handleStartEditTitle}
              title="Clic para renombrar"
            >
              {conversationTitle || 'Chat'}
            </h3>
          )}
        </div>
        <div className="dot-chat__export-actions">
          {onNewChat ? (
            <button
              type="button"
              className="dot-chat__new-chat-btn"
              onClick={onNewChat}
              disabled={isSending}
              title="Nuevo chat (Ctrl+N)"
            >
              + Nuevo chat
            </button>
          ) : null}
          {availableModels.length > 0 ? (
            <div className="dot-chat__model-select-wrapper">
              <ModelSelector
                currentModel={preferredModel || availableModels.find(m => m.is_default)?.id || ''}
                availableModels={availableModels}
                onSelect={onPreferredModelChange || (() => {})}
              />
            </div>
          ) : null}
          <button
            type="button"
            className="dot-chat__export-btn"
            onClick={() => onExportConversation?.('docx')}
            disabled={!canExportConversation || isExportingConversation || !onExportConversation}
          >
            {isExportingConversation && exportingFormat === 'docx' ? 'Exportando Word…' : 'Exportar Word'}
          </button>
          <button
            type="button"
            className="dot-chat__export-btn"
            onClick={() => onExportConversation?.('pdf')}
            disabled={!canExportConversation || isExportingConversation || !onExportConversation}
          >
            {isExportingConversation && exportingFormat === 'pdf' ? 'Exportando PDF…' : 'Exportar PDF'}
          </button>
        </div>
      </div>

      {lastError ? (
        <div className="dot-chat__error-banner" role="alert">
          <span>{lastError.message}</span>
          <button type="button" className="dot-chat__error-dismiss" onClick={onClearError}>
            ×
          </button>
        </div>
      ) : null}

      {showSuggestions ? (
        <div className="dot-chat__cmd-suggestions">
          <p className="dot-chat__cmd-suggestions-title">Comandos disponibles</p>
          <div className="dot-chat__cmd-suggestions-list">
            {filteredSuggestions.map((s, index) => (
              <button
                key={s.cmd}
                type="button"
                className={`dot-chat__cmd-chip ${index === activeSuggestionIndex ? 'dot-chat__cmd-chip--active' : ''}`}
                onClick={() => handleCmdClick(s.cmd)}
                onMouseEnter={() => setActiveSuggestionIndex(index)}
                title={s.desc}
                aria-selected={index === activeSuggestionIndex}
              >
                {s.cmd} — {s.desc}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div className="dot-chat__messages" role="log" aria-live="polite">
        {messages.map((m) => (
          <ChatMessageBubble
            key={m.id}
            message={m}
            voiceTtsAvailable={voiceTtsAvailable}
            ttsLoading={ttsLoadingMessageId === m.id}
            onTextToSpeech={onTextToSpeech}
            onOpenGoogleIntegrations={onOpenGoogleIntegrations}
            onTranslateText={onTranslateText}
            onSummarizeText={onSummarizeText}
          />
        ))}
        <div ref={messagesEndRef} aria-hidden />
      </div>

      {messages.length === 0 && !isParsingDocument ? <QuickTips /> : null}

      {isParsingDocument ? (
        <div className="dot-chat__attachment-preview" role="status" aria-label="Procesando documento">
          <div className="dot-chat__attachment-preview-thumb-placeholder">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden>
              <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.5" opacity="0.3" />
              <path d="M12 6v6l4 2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="dot-chat__attachment-preview-info">
            <span className="dot-chat__attachment-preview-name">⏳ Extrayendo texto del documento…</span>
          </div>
        </div>
      ) : selectedDocument ? (
        <AttachmentPreview file={selectedDocument.file} onRemove={handleRemoveDocument} />
      ) : null}

      {selectedImage ? (
        <AttachmentPreview file={selectedImage} onRemove={handleRemoveImage} />
      ) : null}

      <ChatComposer
        draft={draft}
        isSending={isSending}
        textareaRef={textareaRef}
        getAccessToken={getAccessToken}
        onDraftChange={setDraft}
        onKeyDown={handleKeyDown}
        onSend={handleSend}
        onImageSelected={handleImageSelected}
        onDocumentSelected={handleDocumentSelected}
        onGenerateImage={handleGenerateImage}
        onPrepareImageGeneration={handlePrepareImageGeneration}
        onPasteImage={handlePasteImage}
        hasImageSelected={Boolean(selectedImage)}
        hasDocumentSelected={Boolean(selectedDocument)}
        whatsappMode={whatsappMode}
        onToggleWhatsappMode={onToggleWhatsappMode}
        whatsappModeAvailable={whatsappModeAvailable}
        imageGenEnabled={imageGenEnabled}
        reasoningEnabled={reasoningEnabled}
        reasoningLevel={reasoningLevel}
        onReasoningEnabledChange={onReasoningEnabledChange}
        onReasoningLevelChange={onReasoningLevelChange}
        dotSpeaksEnabled={dotSpeaksEnabled}
        onToggleDotSpeaks={onToggleDotSpeaks}
        voiceTtsAvailable={voiceTtsAvailable}
        voiceSttAvailable={voiceSttAvailable}
        onOpenAppSettings={onOpenAppSettings}
        ttsPlaying={ttsPlaying}
        talkMode={talkMode}
        onToggleTalkMode={onToggleTalkMode}
        wakeWordState={wakeWordState}
        onStartWakeWord={onStartWakeWord}
        onStopWakeWord={onStopWakeWord}
        inputBlocked={usageBlocked}
        inputBlockedMessage={usageBlockedMessage}
      />
    </div>
  )
}
