import type { ChatAttachment, ChatMessage } from '@/lib/chat/types'

const DOC_BLOB_PREFIX = /^\[Documento: ([^\]]+)\]\n\nContenido extraído:\n/

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

/**
 * Compacta mensajes antiguos que guardaron el muro de texto del PDF en `text`.
 * Los mensajes nuevos ya traen display corto + attachment.
 */
export function resolveUserMessageDisplay(message: ChatMessage): {
  text: string
  attachment?: ChatAttachment
} {
  const cleaned = message.text.replace(/--MEMORY[\s\S]*?(?:\}--|$)/g, '')

  if (message.attachment || !DOC_BLOB_PREFIX.test(cleaned)) {
    return { text: cleaned, attachment: message.attachment }
  }

  const nameMatch = cleaned.match(/^\[Documento: ([^\]]+)\]/)
  const name = nameMatch?.[1]?.trim() || 'documento'
  const instructionMatch = cleaned.match(/\n---\nInstrucción del usuario:\s*([\s\S]*)$/)
  const displayText = instructionMatch?.[1]?.trim() || 'Documento adjunto'

  return {
    text: displayText,
    attachment: {
      name,
      type: mimeFromFilename(name),
      size: 0,
    },
  }
}
