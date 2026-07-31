import { useCallback } from 'react'

import type { UseChatResult } from '@/lib/chat/useChat'
import type { AgendaTodayResponse } from '@/features/dashboard/model/types'
import { apiFetchAuthed } from '@/lib/api/client'

export type UseAgendaOptions = {
  getAccessToken: () => Promise<string | null>
  chat: UseChatResult
}

export function useAgenda({ getAccessToken, chat }: UseAgendaOptions) {
  const fetchAgendaToday = useCallback(() => {
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
  }, [getAccessToken, chat])

  return { fetchAgendaToday }
}
