/**
 * Tipos compartidos del modulo ChatCore (independiente de tools complejas).
 */

export type ChatAttachment = {
  name: string
  type: string
  size: number
  /** Contenido en base64 (solo para el mensaje entrante/saliente) */
  data?: string
}

/** Opciones de presentación al enviar; el texto de API puede diferir del visible. */
export type SendMessageOptions = {
  /** Texto mostrado en la burbuja (si no se pasa, se usa el texto enviado al API) */
  displayText?: string
  /** Chip/preview de adjunto en la UI */
  attachment?: ChatAttachment
  /** Override puntual del modo razonamiento */
  reasoning_enabled?: boolean
  reasoning_level?: 'low' | 'medium' | 'high' | 'auto'
  /** Modelo preferido para esta solicitud */
  preferred_model?: string
}

/** Plan de razonamiento visible (resumen, sin chain-of-thought crudo). */
export type ReasoningPlan = {
  summary: string
  steps: string[]
  level: string
}

export type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  text: string
  /** Timestamp ISO */
  createdAt: string
  /** Estado de la respuesta */
  status?: 'sending' | 'sent' | 'error'
  /** Archivo adjunto opcional */
  attachment?: ChatAttachment
  /** Imágenes generadas por IA (respuesta del asistente) */
  generatedImages?: ChatAttachment[]
  /** Plan colapsable del modo razonamiento */
  reasoningPlan?: ReasoningPlan
  /** Fase activa mientras planifica */
  reasoningPhase?: 'analyzing' | 'planning' | 'executing'
  /** Sesión con razonamiento activado (UI optimista) */
  reasoningActive?: boolean
  reasoningLevel?: string
  reasoningToolActivity?: string
  /** Hint sutil cuando DOT usa memoria persistente para responder */
  memoryRecall?: string
}

export type ChatConversation = {
  id: string
  title: string
  messages: ChatMessage[]
  createdAt: string
  updatedAt: string
}

export type SendMessageResult = {
  message: ChatMessage
  conversationId: string
  memoryRecall?: string
}

export type ChatError = {
  code:
    | 'network'
    | 'provider_unavailable'
    | 'subscription_expired'
    | 'rate_limited'
    | 'usage_limit_exceeded'
    | 'unknown'
  message: string
}
