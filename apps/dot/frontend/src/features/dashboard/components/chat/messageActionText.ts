import type { ChatMessage } from '@/lib/chat/types'

import { resolveUserMessageDisplay } from './documentMessageDisplay'

const DOC_CONTENT_RE =
  /^\[Documento: [^\]]+\]\n\nContenido extraído:\n([\s\S]*?)(?:\n\n---\n|$)/

/** Longitud mínima para mostrar «Resumir» en un clic. */
export const MIN_SUMMARIZE_LENGTH = 120

const SPANISH_HINT =
  /[áéíóúñü¿¡]|\b(el|la|los|las|de|que|en|un|una|es|por|con|para|como|pero|más|muy|este|esta|también)\b/i

/** Idioma destino por defecto según heurística del texto. */
export function defaultTranslateTarget(text: string): string {
  return SPANISH_HINT.test(text) ? 'inglés' : 'español'
}

/** Texto utilizable para traducir o resumir desde un mensaje del chat. */
export function extractMessageActionText(message: ChatMessage): string | null {
  const raw = message.text.replace(/--MEMORY[\s\S]*?(?:\}--|$)/g, '').trim()
  if (!raw || raw.startsWith('⏳')) return null

  const docMatch = raw.match(DOC_CONTENT_RE)
  if (docMatch?.[1]?.trim()) {
    return docMatch[1].trim()
  }

  if (message.role === 'user') {
    const display = resolveUserMessageDisplay(message)
    const text = display.text.trim()
    if (text && text !== 'Documento adjunto') return text
    return null
  }

  return raw
}
