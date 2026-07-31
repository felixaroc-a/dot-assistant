import { useCallback, useEffect, useRef, useState } from 'react'

import { translateError } from '@/lib/error-messages'
import type { ChatAttachment, ChatMessage, ChatError, SendMessageOptions } from './types'
import { sendMessage, sendMessageStream, toChatError, getConversationHistory, autoTitleConversation } from './client'
import { humanizeLocalToolJsonIfPresent } from '@/features/dashboard/lib/parse-local-tool-action'
import { analyzeImage } from '@/lib/api/vision'
import { generateImages } from '@/lib/api/imageGen'
import { extractImagePrompt } from '@/features/dashboard/components/chat/imageGenerationIntent'
import { artifactsToGeneratedImages } from '@/lib/chat/chatArtifacts'

const DEFAULT_VISION_PROMPT = 'Analiza esta imagen y describe lo importante.'

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        resolve(reader.result)
      } else {
        reject(new Error('No se pudo leer la imagen.'))
      }
    }
    reader.onerror = () => {
      reject(reader.error ?? new Error('Error al leer la imagen.'))
    }
    reader.readAsDataURL(file)
  })
}

export type UseChatOptions = {
  getAccessToken: () => Promise<string | null>
  /** Si es true, intenta usar streaming SSE en lugar de envio tradicional */
  stream?: boolean
  /** ID de conversación inicial para cargar al montar */
  initialConversationId?: string
  /** Preferencia de razonamiento por defecto (desde perfil) */
  defaultReasoningEnabled?: boolean
  defaultReasoningLevel?: 'low' | 'medium' | 'high' | 'auto'
  onError?: (error: ChatError) => void
  onAiActivityComplete?: () => void
  /** Se invoca cuando el backend asigna o confirma un ID de conversación */
  onConversationIdChange?: (id: string) => void
  /** Se invoca tras un intercambio exitoso (para refrescar lista/títulos) */
  onExchangeComplete?: () => void
}

export type UseChatResult = {
  messages: ChatMessage[]
  send: (text: string, options?: SendMessageOptions) => Promise<void>
  sendVisionImage: (file: File, prompt: string) => Promise<void>
  sendImageGeneration: (text: string) => Promise<void>
  pushLocalExchange: (userText: string, assistantText: string) => void
  updateMessage: (id: string, updates: Partial<ChatMessage>) => void
  clear: () => void
  isSending: boolean
  lastError: ChatError | null
  clearError: () => void
  conversationId: string | undefined
  loadConversation: (id: string) => Promise<ChatMessage[] | undefined>
}

export function useChat({
  getAccessToken,
  stream = true,
  initialConversationId,
  defaultReasoningEnabled = false,
  defaultReasoningLevel = 'auto',
  onError,
  onAiActivityComplete,
  onConversationIdChange,
  onExchangeComplete,
}: UseChatOptions): UseChatResult {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isSending, setIsSending] = useState(false)
  const [lastError, setLastError] = useState<ChatError | null>(null)
  const conversationIdRef = useRef<string | undefined>(initialConversationId)
  const [conversationId, setConversationId] = useState<string | undefined>(initialConversationId)
  const isSendingRef = useRef(false)
  const autoTitledRef = useRef<Set<string>>(new Set())

  useEffect(() => {
    isSendingRef.current = isSending
  }, [isSending])

  const clearError = useCallback(() => setLastError(null), [])

  const send = useCallback(
    async (text: string, options?: SendMessageOptions) => {
      if (!text.trim() || isSendingRef.current) return
      isSendingRef.current = true
      setLastError(null)
      setIsSending(true)

      const apiText = text.trim()
      const displayText = (options?.displayText ?? apiText).trim() || apiText

      const userMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'user',
        text: displayText,
        createdAt: new Date().toISOString(),
        status: 'sent',
        ...(options?.attachment ? { attachment: options.attachment } : {}),
      }

      const reasoningEnabled = options?.reasoning_enabled ?? defaultReasoningEnabled
      const reasoningLevel = options?.reasoning_level ?? defaultReasoningLevel

      const assistantMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'assistant',
        text: '',
        createdAt: new Date().toISOString(),
        status: 'sending',
        reasoningActive: reasoningEnabled,
        reasoningPhase: reasoningEnabled ? 'analyzing' : undefined,
        reasoningLevel: reasoningEnabled ? reasoningLevel : undefined,
      }

      setMessages((prev) => [...prev, userMsg, assistantMsg])

      try {
        const token = await getAccessToken()

        if (stream) {
          let fullResponse = ''
          let streamError = ''
          const streamDone = new Promise<void>((resolve) => {
            sendMessageStream(
              {
                conversation_id: conversationIdRef.current,
                text: apiText,
                reasoning_enabled: reasoningEnabled,
                reasoning_level: reasoningLevel,
              },
              token,
              {
                onToken: (tokenText) => {
                  fullResponse += tokenText
                  fullResponse = fullResponse.replace(/--MEMORY_UPDATE[\s\S]*?\}--/g, '')
                  setMessages((prev) => {
                    const copy = [...prev]
                    const last = copy[copy.length - 1]
                    if (last?.role === 'assistant') {
                      copy[copy.length - 1] = {
                        ...last,
                        text: fullResponse,
                        reasoningPhase: last.reasoningActive ? 'executing' : undefined,
                      }
                    }
                    return copy
                  })
                },
                onDone: (convId) => {
                  if (convId) {
                    conversationIdRef.current = convId
                    setConversationId(convId)
                    onConversationIdChange?.(convId)
                  }
                  if (streamError) return
                  setMessages((prev) => {
                    const copy = [...prev]
                    const last = copy[copy.length - 1]
                    if (last?.role === 'assistant') {
                      copy[copy.length - 1] = {
                        ...last,
                        status: 'sent',
                        reasoningPhase: undefined,
                        reasoningActive: false,
                        reasoningToolActivity: undefined,
                      }
                    }
                    return copy
                  })
                  resolve()
                },
                onError: (error) => {
                  streamError = error
                  resolve()
                },
                onReplaceMessage: (replaced) => {
                  fullResponse = humanizeLocalToolJsonIfPresent(replaced)
                  setMessages((prev) => {
                    const copy = [...prev]
                    const last = copy[copy.length - 1]
                    if (last?.role === 'assistant') {
                      copy[copy.length - 1] = {
                        ...last,
                        text: fullResponse,
                        reasoningPhase: last.reasoningActive ? 'executing' : undefined,
                      }
                    }
                    return copy
                  })
                },
                onReasoningProgress: (phase, level) => {
                  setMessages((prev) => {
                    const copy = [...prev]
                    const last = copy[copy.length - 1]
                    if (last?.role === 'assistant') {
                      copy[copy.length - 1] = {
                        ...last,
                        reasoningActive: true,
                        reasoningPhase: phase,
                        reasoningLevel: level || last.reasoningLevel,
                      }
                    }
                    return copy
                  })
                },
                onReasoningPlan: (plan) => {
                  setMessages((prev) => {
                    const copy = [...prev]
                    const last = copy[copy.length - 1]
                    if (last?.role === 'assistant') {
                      copy[copy.length - 1] = {
                        ...last,
                        reasoningActive: true,
                        reasoningPlan: plan,
                        reasoningPhase: 'executing',
                        reasoningLevel: plan.level || last.reasoningLevel,
                      }
                    }
                    return copy
                  })
                },
                onToolProgress: (event) => {
                  const preview = event.preview ? ` — ${event.preview}` : ''
                  setMessages((prev) => {
                    const copy = [...prev]
                    const last = copy[copy.length - 1]
                    if (last?.role === 'assistant') {
                      copy[copy.length - 1] = {
                        ...last,
                        reasoningActive: true,
                        reasoningPhase: 'executing',
                        reasoningToolActivity: `${event.tool}${preview}`,
                      }
                    }
                    return copy
                  })
                },
                onMemoryRecall: (recallText) => {
                  setMessages((prev) => {
                    const copy = [...prev]
                    const last = copy[copy.length - 1]
                    if (last?.role === 'assistant') {
                      copy[copy.length - 1] = {
                        ...last,
                        memoryRecall: recallText,
                      }
                    }
                    return copy
                  })
                },
                onArtifacts: (items) => {
                  const generatedImages = artifactsToGeneratedImages(items)
                  if (!generatedImages.length) return
                  setMessages((prev) => {
                    const copy = [...prev]
                    const last = copy[copy.length - 1]
                    if (last?.role === 'assistant') {
                      copy[copy.length - 1] = {
                        ...last,
                        generatedImages,
                      }
                    }
                    return copy
                  })
                },
              },
            )
          })

          await streamDone

          // CH07: Auto-titulado LLM tras primer intercambio
          const currentConvId = conversationIdRef.current
          if (currentConvId && !autoTitledRef.current.has(currentConvId)) {
            autoTitledRef.current.add(currentConvId)
            void (async () => {
              try {
                const tok = await getAccessToken()
                if (tok) {
                  await autoTitleConversation(currentConvId, apiText, tok)
                  onExchangeComplete?.()
                }
              } catch {
                // Silencio: el título truncado es suficiente fallback
              }
            })()
          }

          // Cinturón: si quedó JSON local_tool en pantalla, humanizar (backend ya ejecutó)
          fullResponse = humanizeLocalToolJsonIfPresent(fullResponse)
          setMessages((prev) => {
            const copy = [...prev]
            const last = copy[copy.length - 1]
            if (last?.role === 'assistant' && last.text !== fullResponse) {
              copy[copy.length - 1] = { ...last, text: fullResponse }
            }
            return copy
          })

          if (streamError) {
            const chatError: ChatError = {
              code: 'unknown',
              message: streamError,
            }
            setLastError(chatError)
            onError?.(chatError)
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMsg.id
                  ? {
                      ...m,
                      status: 'error' as const,
                      text: fullResponse || streamError,
                    }
                  : m,
              ),
            )
          } else {
            onExchangeComplete?.()
          }
        } else {
          const result = await sendMessage(
            {
              conversation_id: conversationIdRef.current,
              text: apiText,
              reasoning_enabled: options?.reasoning_enabled ?? defaultReasoningEnabled,
              reasoning_level: options?.reasoning_level ?? defaultReasoningLevel,
            },
            token,
          )
          conversationIdRef.current = result.conversationId
          setConversationId(result.conversationId)
          onConversationIdChange?.(result.conversationId)

          setMessages((prev) => {
            const copy = [...prev]
            const last = copy[copy.length - 1]
            if (last?.role === 'assistant') {
              copy[copy.length - 1] = {
                ...last,
                text: result.message.text,
                status: 'sent',
                memoryRecall: result.memoryRecall,
              }
            } else {
              copy.push(result.message)
            }
            return copy
          })
          onExchangeComplete?.()
        }
      } catch (e) {
        const chatError = toChatError(e)
        setLastError(chatError)
        onError?.(chatError)

        setMessages((prev) =>
          prev.map((m) =>
            m.id === userMsg.id
              ? { ...m, status: 'error' as const }
              : m.id === assistantMsg.id && !m.text
                ? { ...m, status: 'error' as const, text: chatError.message }
                : m,
          ),
        )
      } finally {
        isSendingRef.current = false
        setIsSending(false)
        onAiActivityComplete?.()
      }
    },
    [
      defaultReasoningEnabled,
      defaultReasoningLevel,
      getAccessToken,
      onAiActivityComplete,
      onConversationIdChange,
      onExchangeComplete,
      onError,
      stream,
    ],
  )

  const sendVisionImage = useCallback(
    async (file: File, promptText: string) => {
      if (isSendingRef.current) return
      isSendingRef.current = true
      setLastError(null)
      setIsSending(true)

      const prompt = promptText.trim() || DEFAULT_VISION_PROMPT
      const displayText = promptText.trim() ? promptText.trim() : 'Imagen adjunta'

      const attachmentPayload: ChatAttachment = {
        name: file.name,
        type: file.type || 'image/jpeg',
        size: file.size,
        data: await fileToDataUrl(file),
      }

      const userMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'user',
        text: displayText,
        createdAt: new Date().toISOString(),
        status: 'sent',
        attachment: attachmentPayload,
      }

      const assistantMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'assistant',
        text: '',
        createdAt: new Date().toISOString(),
        status: 'sending',
      }

      setMessages((prev) => [...prev, userMsg, assistantMsg])

      try {
        const token = await getAccessToken()
        const result = await analyzeImage(file, prompt, token)
        const assistantText = result.result ?? ''

        setMessages((prev) =>
          prev.map((message) =>
            message.id === assistantMsg.id
              ? { ...message, text: assistantText, status: 'sent' }
              : message,
          ),
        )

        if (assistantText.includes('Vision no disponible')) {
          const visionError: ChatError = {
            code: 'provider_unavailable',
            message: assistantText,
          }
          setLastError(visionError)
          onError?.(visionError)
        }
      } catch (e) {
        const chatError = toChatError(e)
        setLastError(chatError)
        onError?.(chatError)

        setMessages((prev) =>
          prev.map((message) =>
            message.id === userMsg.id
              ? { ...message, status: 'error' as const }
              : message.id === assistantMsg.id
                ? { ...message, status: 'error' as const, text: chatError.message }
                : message,
          ),
        )
        throw chatError
      } finally {
        isSendingRef.current = false
        setIsSending(false)
        onAiActivityComplete?.()
      }
    },
    [getAccessToken, onAiActivityComplete, onError],
  )

  const sendImageGeneration = useCallback(
    async (text: string) => {
      const prompt = extractImagePrompt(text)
      if (!prompt.trim() || isSendingRef.current) return
      isSendingRef.current = true
      setLastError(null)
      setIsSending(true)

      const userMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'user',
        text: text.trim(),
        createdAt: new Date().toISOString(),
        status: 'sent',
      }

      const assistantMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'assistant',
        text: '',
        createdAt: new Date().toISOString(),
        status: 'sending',
      }

      setMessages((prev) => [...prev, userMsg, assistantMsg])

      try {
        const result = await generateImages({ prompt }, getAccessToken)
        const generatedImages: ChatAttachment[] = result.images.map((image, index) => ({
          name: `imagen-generada-${index + 1}.png`,
          type: image.mime_type,
          size: Math.ceil((image.data_base64.length * 3) / 4),
          data: `data:${image.mime_type};base64,${image.data_base64}`,
        }))
        const assistantText =
          result.count > 1
            ? `Generé ${result.count} imágenes para: ${result.prompt_used}`
            : `Imagen generada: ${result.prompt_used}`

        setMessages((prev) =>
          prev.map((message) =>
            message.id === assistantMsg.id
              ? {
                  ...message,
                  text: assistantText,
                  status: 'sent',
                  generatedImages,
                }
              : message,
          ),
        )
      } catch (e) {
        const chatError = toChatError(e)
        setLastError(chatError)
        onError?.(chatError)

        setMessages((prev) =>
          prev.map((message) =>
            message.id === userMsg.id
              ? { ...message, status: 'error' as const }
              : message.id === assistantMsg.id
                ? { ...message, status: 'error' as const, text: chatError.message }
                : message,
          ),
        )
        throw chatError
      } finally {
        isSendingRef.current = false
        setIsSending(false)
        onAiActivityComplete?.()
      }
    },
    [getAccessToken, onAiActivityComplete, onError],
  )

  const pushLocalExchange = useCallback((userText: string, assistantText: string) => {
    const now = new Date().toISOString()
    setMessages((prev) => {
      const next = [...prev]
      if (userText.trim()) {
        next.push({
          id: crypto.randomUUID(),
          role: 'user',
          text: userText.trim(),
          createdAt: now,
          status: 'sent',
        })
      }
      next.push({
        id: crypto.randomUUID(),
        role: 'assistant',
        text: assistantText,
        createdAt: now,
        status: 'sent',
      })
      return next
    })
  }, [])

  const updateMessage = useCallback((id: string, updates: Partial<ChatMessage>) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, ...updates } : m)),
    )
  }, [])

  const clear = useCallback(() => {
    setMessages([])
    conversationIdRef.current = undefined
    setConversationId(undefined)
    setLastError(null)
  }, [])

  const loadConversation = useCallback(
    async (id: string) => {
      if (!id) return
      const token = await getAccessToken()
      try {
        const { messages: historyMessages } = await getConversationHistory(id, token)
        setMessages(historyMessages)
        conversationIdRef.current = id
        setConversationId(id)
        setLastError(null)
        return historyMessages
      } catch (e) {
        const err = e as Error
        setLastError({ code: 'unknown', message: translateError(err, 'No se pudo cargar la conversación.') })
      }
    },
    [getAccessToken],
  )

  return {
    messages,
    send,
    sendVisionImage,
    sendImageGeneration,
    pushLocalExchange,
    updateMessage,
    clear,
    loadConversation,
    isSending,
    lastError,
    clearError,
    conversationId,
  }
}
