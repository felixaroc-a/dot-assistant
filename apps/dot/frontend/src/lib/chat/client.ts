/**
 * API client del modulo ChatCore.
 * Encapsula la comunicacion con el backend para enviar/recibir mensajes.
 * En Fase 2+ esto se conectara al adaptador OpenClaw.
 */
import { ApiError } from '@/lib/api/http'
import { getApiBaseUrl } from '@/lib/api/base-url'
import { apiFetchJson } from '@/lib/api/http'
import {
  IMAGE_GENERATION_UNAVAILABLE_MESSAGE,
  LOCAL_BACKEND_UNREACHABLE_MESSAGE,
  NETWORK_ERROR_MESSAGE,
  translateApiError,
  translateError,
  translateErrorMessage,
} from '@/lib/error-messages'
import { USAGE_LIMIT_BLOCKED_MESSAGE } from '@/lib/usage-messages'
import type { ChatMessage, SendMessageResult, ChatError, ReasoningPlan } from './types'

function isFetchNetworkFailure(error: Error): boolean {
  const message = error.message.toLowerCase()
  return (
    message.includes('failed to fetch') ||
    message.includes('networkerror') ||
    message.includes('load failed') ||
    message.includes('network request failed')
  )
}

function isLocalApiBaseUrl(): boolean {
  try {
    const base = getApiBaseUrl()
    return /^(https?:\/\/)?(127\.0\.0\.1|localhost)(:\d+)?/i.test(base)
  } catch {
    return false
  }
}

function mapFetchNetworkError(_error: Error): string {
  if (isLocalApiBaseUrl()) {
    return LOCAL_BACKEND_UNREACHABLE_MESSAGE
  }
  return NETWORK_ERROR_MESSAGE
}

export type SendMessageRequest = {
  conversation_id?: string
  text: string
  reasoning_enabled?: boolean
  reasoning_level?: 'low' | 'medium' | 'high' | 'auto'
  preferred_model?: string
}

export type SendMessageResponse = {
  message: ChatMessage
  conversation_id: string
  memory_recall?: string | null
}

export type ConversationSummary = {
  id: string
  title: string
  provider: string
  channel: string
  message_count: number
  created_at: string
  updated_at: string
  archived?: boolean
}

export type ConversationListResponse = {
  conversations: ConversationSummary[]
}

export type HistoryResponse = {
  conversation_id: string
  messages: ChatMessage[]
}

/**
 * Envia un mensaje al backend y obtiene respuesta del asistente.
 */
export async function sendMessage(
  body: SendMessageRequest,
  accessToken: string | null,
): Promise<SendMessageResult> {
  const res = await apiFetchJson<SendMessageResponse>(
    '/v1/chat/send',
    {
      method: 'POST',
      body: JSON.stringify(body),
    },
    accessToken,
  )
  return {
    message: res.message,
    conversationId: res.conversation_id,
    memoryRecall: res.memory_recall ?? undefined,
  }
}

export type StreamEventHandlers = {
  onToken?: (token: string) => void
  onDone?: (conversationId: string) => void
  onError?: (error: string) => void
  onReplaceMessage?: (text: string) => void
  onReasoningProgress?: (phase: 'analyzing' | 'planning' | 'executing', level?: string) => void
  onReasoningPlan?: (plan: ReasoningPlan) => void
  onToolProgress?: (event: { step: number; tool: string; preview: string; ok: boolean }) => void
  onMemoryRecall?: (text: string) => void
  onArtifacts?: (items: unknown[]) => void
}

/**
 * Envia un mensaje al backend con streaming SSE.
 * Los tokens se entregan via callback onToken.
 * Al completar se llama onDone con el conversation_id.
 *
 * Timeout: idle (sin datos SSE) vs techo absoluto.
 * Las tareas multi-tool pueden superar 2 min; no cortamos si el servidor sigue vivo.
 */
export const CHAT_STREAM_IDLE_TIMEOUT_MS = 180_000 // 3 min sin ningún evento SSE
export const CHAT_STREAM_ABSOLUTE_TIMEOUT_MS = 900_000 // 15 min techo de seguridad

export async function sendMessageStream(
  body: SendMessageRequest,
  accessToken: string | null,
  handlers: StreamEventHandlers,
): Promise<void> {
  const {
    onToken,
    onDone,
    onError,
    onReplaceMessage,
    onReasoningProgress,
    onReasoningPlan,
    onToolProgress,
    onMemoryRecall,
    onArtifacts,
  } = handlers
  const base = getApiBaseUrl()
  const url = `${base}/v1/chat/send/stream`

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`

  const controller = new AbortController()
  let abortReason: 'idle' | 'absolute' | null = null
  let idleTimer: ReturnType<typeof setTimeout> | null = null
  const startedAt = Date.now()

  const clearIdle = () => {
    if (idleTimer !== null) {
      clearTimeout(idleTimer)
      idleTimer = null
    }
  }

  const armIdle = () => {
    clearIdle()
    idleTimer = setTimeout(() => {
      abortReason = 'idle'
      controller.abort()
    }, CHAT_STREAM_IDLE_TIMEOUT_MS)
  }

  const absoluteTimer = setTimeout(() => {
    abortReason = 'absolute'
    controller.abort()
  }, CHAT_STREAM_ABSOLUTE_TIMEOUT_MS)

  armIdle()

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal: controller.signal,
    })

    if (!response.ok) {
      const text = await response.text().catch(() => '')
      onError?.(translateErrorMessage(text || `HTTP ${response.status}`))
      return
    }

    const reader = response.body?.getReader()
    if (!reader) {
      onError?.(translateErrorMessage('No response body'))
      return
    }

    const decoder = new TextDecoder()
    let buffer = ''
    let lastConversationId = body.conversation_id ?? ''
    let doneEmitted = false

    const emitDoneIfNeeded = () => {
      if (doneEmitted) return
      doneEmitted = true
      onDone?.(lastConversationId)
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        emitDoneIfNeeded()
        break
      }

      // Cualquier byte SSE reinicia el idle (agente largo + informe).
      armIdle()

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6))
            if (typeof data.conversation_id === 'string' && data.conversation_id.trim()) {
              lastConversationId = data.conversation_id
            }
            if (data.type === 'artifacts' && Array.isArray(data.items)) {
              onArtifacts?.(data.items)
            } else if (data.type === 'reasoning_progress' && data.phase) {
              onReasoningProgress?.(data.phase, data.level)
            } else if (data.type === 'reasoning_plan') {
              onReasoningPlan?.({
                summary: String(data.summary || ''),
                steps: Array.isArray(data.steps) ? data.steps.map(String) : [],
                level: String(data.level || 'medium'),
              })
            } else if (data.type === 'tool_progress') {
              onToolProgress?.({
                step: Number(data.step || 0),
                tool: String(data.tool || ''),
                preview: String(data.preview || ''),
                ok: Boolean(data.ok),
              })
            } else if (data.type === 'memory_recall' && data.text) {
              onMemoryRecall?.(String(data.text))
            } else if (data.type === 'heartbeat') {
              // keep-alive: solo reinicia idle (ya hecho arriba)
            } else if (data.token) {
              onToken?.(data.token)
            } else if (typeof data.replace_message === 'string') {
              onReplaceMessage?.(data.replace_message)
            } else if (data.done) {
              if (typeof data.memory_recall === 'string' && data.memory_recall.length > 0) {
                onMemoryRecall?.(data.memory_recall)
              }
              if (typeof data.final_text === 'string' && data.final_text.length > 0) {
                onReplaceMessage?.(data.final_text)
              }
              emitDoneIfNeeded()
            } else if (data.error) {
              onError?.(translateErrorMessage(String(data.error)))
            }
          } catch {
            // Ignorar parse errors
          }
        }
      }
    }
  } catch (e) {
    const err = e as Error
    if (err.name === 'AbortError') {
      const elapsedSec = Math.round((Date.now() - startedAt) / 1000)
      if (abortReason === 'absolute') {
        onError?.(
          `Timeout: la tarea superó el límite máximo (${Math.round(CHAT_STREAM_ABSOLUTE_TIMEOUT_MS / 60000)} min).`,
        )
      } else {
        onError?.(
          `Timeout: el servidor dejó de responder (${elapsedSec}s sin actividad).`,
        )
      }
    } else if (isFetchNetworkFailure(err)) {
      onError?.(mapFetchNetworkError(err))
    } else {
      onError?.(translateError(err, 'No pude enviar tu mensaje. Intenta de nuevo.'))
    }
  } finally {
    clearIdle()
    clearTimeout(absoluteTimer)
  }
}

/**
 * Obtiene historial paginado de una conversacion desde BD (B01).
 */
export async function getConversationHistory(
  conversationId: string,
  accessToken: string | null,
  page: number = 1,
  pageSize: number = 50,
): Promise<{ messages: ChatMessage[]; total: number }> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  const res = await apiFetchJson<HistoryResponse & { total: number }>(
    `/v1/chat/conversations/${encodeURIComponent(conversationId)}/history?${params}`,
    { method: 'GET' },
    accessToken,
  )
  return { messages: res.messages, total: res.total ?? res.messages.length }
}

/**
 * Obtiene la lista de conversaciones activas del usuario (B01).
 */
export async function getConversations(
  accessToken: string | null,
  query?: string,
): Promise<ConversationSummary[]> {
  const params = new URLSearchParams()
  const q = query?.trim()
  if (q) {
    params.set('q', q)
    params.set('search_messages', 'true')
  }
  const suffix = params.toString() ? `?${params.toString()}` : ''
  const res = await apiFetchJson<ConversationListResponse>(
    `/v1/chat/conversations${suffix}`,
    { method: 'GET' },
    accessToken,
  )
  return res.conversations
}

/**
 * Obtiene conversaciones archivadas del usuario (CH04b).
 */
export async function getArchivedConversations(
  accessToken: string | null,
  query?: string,
): Promise<ConversationSummary[]> {
  const params = new URLSearchParams({ include_archived: 'true' })
  const q = query?.trim()
  if (q) {
    params.set('q', q)
    params.set('search_messages', 'true')
  }
  const res = await apiFetchJson<ConversationListResponse>(
    `/v1/chat/conversations?${params.toString()}`,
    { method: 'GET' },
    accessToken,
  )
  return res.conversations
}

/**
 * Crea una nueva conversación vacía (B01).
 */
export async function createConversation(
  title: string | undefined,
  accessToken: string | null,
  channel: string = 'pc',
): Promise<ConversationSummary> {
  const body: Record<string, string> = { channel }
  if (title) body.title = title
  return apiFetchJson<ConversationSummary>(
    '/v1/chat/conversations',
    { method: 'POST', body: JSON.stringify(body) },
    accessToken,
  )
}

/**
 * Renombra una conversación existente (B01).
 */
export async function renameConversation(
  id: string,
  title: string,
  accessToken: string | null,
): Promise<ConversationSummary> {
  return apiFetchJson<ConversationSummary>(
    `/v1/chat/conversations/${encodeURIComponent(id)}`,
    { method: 'PATCH', body: JSON.stringify({ title }) },
    accessToken,
  )
}

/**
 * Soft-delete: archiva conversación, preserva mensajes (B01).
 */
export async function deleteConversation(
  id: string,
  accessToken: string | null,
): Promise<{ ok: boolean }> {
  return apiFetchJson<{ ok: boolean }>(
    `/v1/chat/conversations/${encodeURIComponent(id)}`,
    { method: 'DELETE' },
    accessToken,
  )
}

/**
 * CH07: Genera un título automático vía LLM para una conversación.
 */
export async function autoTitleConversation(
  id: string,
  userText: string,
  accessToken: string | null,
): Promise<{ id: string; title: string }> {
  return apiFetchJson<{ id: string; title: string }>(
    `/v1/chat/conversations/${encodeURIComponent(id)}/auto-title`,
    { method: 'POST', body: JSON.stringify({ user_text: userText }) },
    accessToken,
  )
}

/**
 * CH04b: Restaura una conversación archivada.
 */
export async function unarchiveConversation(
  id: string,
  accessToken: string | null,
): Promise<{ id: string; title: string; ok: boolean }> {
  return apiFetchJson<{ id: string; title: string; ok: boolean }>(
    `/v1/chat/conversations/${encodeURIComponent(id)}/unarchive`,
    { method: 'POST' },
    accessToken,
  )
}

/**
 * CH06: Busca en el contenido de mensajes de todas las conversaciones.
 */
export async function searchMessages(
  query: string,
  accessToken: string | null,
): Promise<{ results: Array<{
  conversation_id: string
  conversation_title: string
  message_id: string
  role: string
  snippet: string
  created_at: string
}>; query: string }> {
  const params = new URLSearchParams({ q: query })
  return apiFetchJson(
    `/v1/chat/conversations/search/messages?${params}`,
    { method: 'GET' },
    accessToken,
  )
}

/**
 * Traduce un error de API a ChatError tipado para la UI.
 */
export function toChatError(e: unknown): ChatError {
  if (e instanceof ApiError) {
    if (e.status === 402) {
      return {
        code: 'usage_limit_exceeded',
        message: translateApiError(e, USAGE_LIMIT_BLOCKED_MESSAGE),
      }
    }
    if (e.status === 429) {
      return {
        code: 'rate_limited',
        message: translateApiError(
          e,
          'Demasiadas solicitudes. Espera un momento e intenta de nuevo.',
        ),
      }
    }
    if (e.status === 403) {
      return {
        code: 'subscription_expired',
        message: translateApiError(e, 'Tu suscripción venció. Renueva en la tienda más cercana.'),
      }
    }
    if (e.status === 503) {
      const message = translateApiError(e, IMAGE_GENERATION_UNAVAILABLE_MESSAGE)
      if (
        message === IMAGE_GENERATION_UNAVAILABLE_MESSAGE ||
        e.message.toLowerCase().includes('image_generation_unavailable') ||
        e.message.toLowerCase().includes('generación de imágenes')
      ) {
        return {
          code: 'image_generation_unavailable',
          message: IMAGE_GENERATION_UNAVAILABLE_MESSAGE,
        }
      }
    }
    return {
      code: 'unknown',
      message: translateApiError(e),
    }
  }

  if (e && typeof e === 'object' && 'status' in e) {
    const status = Number((e as { status: unknown }).status)
    if (status === 429) {
      return { code: 'rate_limited', message: 'Demasiadas solicitudes. Espera un momento.' }
    }
    if (status === 403) {
      return { code: 'subscription_expired', message: 'Tu suscripción venció.' }
    }
  }
  if (e instanceof Error) {
    if (isFetchNetworkFailure(e)) {
      return { code: 'network', message: mapFetchNetworkError(e) }
    }
    return {
      code: 'unknown',
      message: translateError(e, 'No pude enviar tu mensaje. Intenta de nuevo.'),
    }
  }
  return { code: 'unknown', message: 'No pude enviar tu mensaje. Intenta de nuevo.' }
}
