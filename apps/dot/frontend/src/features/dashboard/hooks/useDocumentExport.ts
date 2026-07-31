import { useCallback } from 'react'

import { buildChatExportDocument } from '@/features/dashboard/lib/chat-export'
import type { UseChatResult } from '@/lib/chat/useChat'
import type { DocumentGeneratorState } from '@/lib/documents/useDocumentGenerator'

export type UseDocumentExportOptions = {
  chat: UseChatResult
  docGen: DocumentGeneratorState & {
    generate: (req: { document_type: string; title: string; content: string }) => Promise<{ filename: string; path: string }>
  }
  userDisplayName: string
  onExportStart: (format: 'docx' | 'pdf') => void
  onExportEnd: () => void
  onExported?: (file: { filename: string; path: string }) => void
}

export function useDocumentExport({
  chat,
  docGen,
  userDisplayName,
  onExportStart,
  onExportEnd,
  onExported,
}: UseDocumentExportOptions) {
  const handleExportConversation = useCallback(
    (format: 'docx' | 'pdf') => {
      if (chat.messages.length === 0 || docGen.isGenerating) return
      const exportDoc = buildChatExportDocument(chat.messages, userDisplayName)
      onExportStart(format)

      void docGen
        .generate({
          document_type: format,
          title: exportDoc.title,
          content: exportDoc.content,
        })
        .then((res) => {
          onExported?.(res)
          chat.pushLocalExchange(
            '',
            `Conversación exportada en ${format.toUpperCase()}: ${res.filename} en ${res.path}`,
          )
        })
        .catch(() => {
          chat.pushLocalExchange(
            '',
            `No pude exportar la conversación en ${format.toUpperCase()}. Revisa backend o permisos de escritura.`,
          )
        })
        .finally(() => {
          onExportEnd()
        })
    },
    [chat, docGen, userDisplayName, onExportStart, onExportEnd, onExported],
  )

  return { handleExportConversation }
}
