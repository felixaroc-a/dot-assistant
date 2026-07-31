import type { ChatMessage } from '@/lib/chat/types'

function safeDatePart(value: number): string {
  return String(value).padStart(2, '0')
}

function toExportTimestamp(date: Date): string {
  return `${date.getFullYear()}-${safeDatePart(date.getMonth() + 1)}-${safeDatePart(date.getDate())} ${safeDatePart(date.getHours())}:${safeDatePart(date.getMinutes())}`
}

export function buildChatExportDocument(
  messages: ChatMessage[],
  userDisplayName: string,
  now: Date = new Date(),
): { title: string; content: string } {
  const normalizedName = userDisplayName.trim() || 'Usuario'
  const dateLabel = toExportTimestamp(now)
  const title = `Conversación DOT ${now.getFullYear()}-${safeDatePart(now.getMonth() + 1)}-${safeDatePart(now.getDate())}`

  const renderedMessages =
    messages.length > 0
      ? messages
          .map((msg, index) => {
            const roleLabel = msg.role === 'assistant' ? 'DOT' : normalizedName
            const parsedDate = new Date(msg.createdAt)
            const ts = Number.isNaN(parsedDate.getTime())
              ? ''
              : `${safeDatePart(parsedDate.getHours())}:${safeDatePart(parsedDate.getMinutes())}`
            const status = msg.status === 'error' ? ' [no enviado]' : ''
            return `### ${index + 1}. ${roleLabel}${status}\n${ts ? `Hora: ${ts}\n` : ''}${msg.text.trim() || '(mensaje vacío)'}`
          })
          .join('\n\n')
      : '_Sin mensajes disponibles para exportar._'

  const content =
    `# Conversación DOT\n\n` +
    `Generado: ${dateLabel}\n` +
    `Usuario: ${normalizedName}\n\n` +
    `## Intercambios\n\n` +
    `${renderedMessages}\n`

  return { title, content }
}
