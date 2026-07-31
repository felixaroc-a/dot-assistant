import { useCallback } from 'react'

import type { UseChatResult } from '@/lib/chat/useChat'
import type { SendMessageOptions } from '@/lib/chat/types'
import type { AgendaTodayResponse, ReminderCreateResponse, SummarizeResponse, TranslateResponse } from '@/features/dashboard/model/types'
import type { DocumentType } from '@/lib/api/documents'
import type { DocumentGeneratorState } from '@/lib/documents/useDocumentGenerator'
import { defaultTranslateTarget } from '@/features/dashboard/components/chat/messageActionText'
import { parseSlashCommand } from '@/features/dashboard/lib/slash-commands'
import {
  extractImagePrompt,
  hasImageGenerationIntent,
} from '@/features/dashboard/components/chat/imageGenerationIntent'
import { apiFetchAuthed } from '@/lib/api/client'

export type UseSlashCommandsOptions = {
  getAccessToken: () => Promise<string | null>
  chat: UseChatResult
  docGen: DocumentGeneratorState & {
    generate: (req: { document_type: DocumentType; title: string; content: string }) => Promise<{ filename: string; path: string }>
  }
}

export function useSlashCommands({ getAccessToken, chat, docGen }: UseSlashCommandsOptions) {
  const translateText = useCallback(
    (text: string, targetLang?: string) => {
      const trimmed = text.trim()
      if (!trimmed) return Promise.resolve()

      const resolvedTarget = (targetLang ?? defaultTranslateTarget(trimmed)).trim()
      chat.pushLocalExchange('', `Traduciendo al ${resolvedTarget}…`)

      return apiFetchAuthed<TranslateResponse>(
        '/v1/chat/translate',
        {
          method: 'POST',
          body: JSON.stringify({
            text: trimmed,
            target_lang: resolvedTarget,
          }),
        },
        getAccessToken,
      )
        .then((res) => {
          const providerLabel = res.provider === 'google_translate' ? 'Google Translate' : 'DeepSeek'
          chat.pushLocalExchange('', `${res.translated_text}\n\n(Traducido por ${providerLabel})`)
        })
        .catch(() => {
          chat.pushLocalExchange(
            '',
            'No pude completar la traducción. Revisa la configuración de GOOGLE_TRANSLATE_API_KEY o DEEPSEEK_API_KEY.',
          )
        })
    },
    [chat, getAccessToken],
  )

  const summarizeText = useCallback(
    (text: string) => {
      const trimmed = text.trim()
      if (!trimmed) return Promise.resolve()

      chat.pushLocalExchange('', 'Resumiendo…')

      return apiFetchAuthed<SummarizeResponse>(
        '/v1/chat/summarize',
        {
          method: 'POST',
          body: JSON.stringify({
            content: trimmed,
          }),
        },
        getAccessToken,
      )
        .then((res) => {
          const sourceLabelMap: Record<string, string> = {
            text: 'texto',
            url: 'URL',
            pdf_url: 'PDF remoto',
          }
          const sourceLabel = sourceLabelMap[res.source_type] ?? res.source_type
          chat.pushLocalExchange(
            '',
            `${res.summary}\n\n(Resumen generado desde ${sourceLabel}${res.chunks > 1 ? `, ${res.chunks} bloques` : ''})`,
          )
        })
        .catch(() => {
          chat.pushLocalExchange(
            '',
            'No pude resumir el contenido. Verifica la URL/PDF o la configuración de DEEPSEEK_API_KEY.',
          )
        })
    },
    [chat, getAccessToken],
  )

  const handleSend = useCallback(
    (text: string, options?: SendMessageOptions) => {
      // Documentos / payloads con display separado no pasan por slash commands
      if (options?.attachment || options?.displayText != null) {
        void chat.send(text, options)
        return
      }

      if (hasImageGenerationIntent(text)) {
        void chat.sendImageGeneration(extractImagePrompt(text))
        return
      }

      const cmd = parseSlashCommand(text)
      if (cmd.handled) {
        chat.pushLocalExchange(text, cmd.reply)
        if (cmd.agendaRequest === 'today') {
          void apiFetchAuthed<AgendaTodayResponse>(
            '/v1/chat/agenda/today',
            { method: 'GET' },
            getAccessToken,
          )
            .then((res) => {
              if (!res.linked) {
                chat.pushLocalExchange('', res.message)
                return
              }
              if (!res.events.length) {
                chat.pushLocalExchange('', res.message || 'Hoy no tienes eventos en Google Calendar.')
                return
              }
              chat.pushLocalExchange('', res.message)
            })
            .catch(() => {
              chat.pushLocalExchange(
                '',
                'No pude consultar tu agenda ahora. Revisa tu sesión o la conexión con Google Calendar.',
              )
            })
        }
        if (cmd.reminderRequest) {
          void apiFetchAuthed<ReminderCreateResponse>(
            '/v1/chat/reminders',
            {
              method: 'POST',
              body: JSON.stringify({
                text: cmd.reminderRequest.text,
                due_at: cmd.reminderRequest.dueAtIso,
              }),
            },
            getAccessToken,
          )
            .then((res) => {
              chat.pushLocalExchange('', res.message)
              const scheduleFallback = window.desktop?.createReminderTask
              if (typeof scheduleFallback === 'function') {
                void scheduleFallback({
                  id: res.id,
                  text: cmd.reminderRequest.text,
                  dueAtIso: res.due_at,
                }).then((taskResult) => {
                  if (!taskResult?.ok && taskResult?.error !== 'unsupported_platform') {
                    chat.pushLocalExchange(
                      '',
                      'Recordatorio guardado, pero no pude crear el fallback de Windows Task Scheduler.',
                    )
                  }
                })
              }
            })
            .catch(() => {
              chat.pushLocalExchange(
                '',
                'No pude guardar el recordatorio. Revisa tu sesión o la conexión con el backend.',
              )
            })
        }
        if (cmd.translationRequest) {
          void translateText(cmd.translationRequest.text, cmd.translationRequest.targetLanguage)
        }
        if (cmd.summaryRequest) {
          void summarizeText(cmd.summaryRequest.source)
        }
        if (cmd.documentRequest) {
          void docGen
            .generate({
              document_type: (cmd.documentRequest.documentType ?? 'docx') as DocumentType,
              title: cmd.documentRequest.title,
              content: cmd.documentRequest.content,
            })
            .then((res) => {
              chat.pushLocalExchange(
                '',
                `Documento generado automáticamente: ${res.filename} en ${res.path}`,
              )
            })
            .catch(() => {
              chat.pushLocalExchange('', 'No pude generar el documento. Revisa tu sesión o el backend.')
            })
        }
        if (cmd.webSearchQuery) {
          void chat.send(cmd.webSearchQuery)
        }
        if (cmd.sendToChat) {
          void chat.send(cmd.sendToChat)
        }
        return
      }
      void chat.send(text)
    },
    [chat, docGen, getAccessToken, summarizeText, translateText],
  )

  return { handleSend, translateText, summarizeText }
}
