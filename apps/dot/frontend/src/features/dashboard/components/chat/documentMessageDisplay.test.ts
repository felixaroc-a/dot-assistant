import { describe, expect, it } from 'vitest'

import type { ChatMessage } from '@/lib/chat/types'
import { resolveUserMessageDisplay } from './documentMessageDisplay'

function userMsg(text: string, attachment?: ChatMessage['attachment']): ChatMessage {
  return {
    id: '1',
    role: 'user',
    text,
    createdAt: new Date().toISOString(),
    ...(attachment ? { attachment } : {}),
  }
}

describe('resolveUserMessageDisplay', () => {
  it('deja intactos mensajes sin muro de documento', () => {
    const result = resolveUserMessageDisplay(userMsg('hola'))
    expect(result).toEqual({ text: 'hola', attachment: undefined })
  })

  it('respeta display corto ya presente con attachment', () => {
    const attachment = { name: 'a.pdf', type: 'application/pdf', size: 10 }
    const result = resolveUserMessageDisplay(userMsg('hazme un resumen', attachment))
    expect(result.text).toBe('hazme un resumen')
    expect(result.attachment).toEqual(attachment)
  })

  it('compacta historial antiguo con Contenido extraído', () => {
    const blob =
      '[Documento: el principito.pdf]\n\nContenido extraído:\nEl Principito Por Antoine...\n[Texto truncado]\n\n---\nInstrucción del usuario: hazme un resumen'
    const result = resolveUserMessageDisplay(userMsg(blob))
    expect(result.text).toBe('hazme un resumen')
    expect(result.attachment?.name).toBe('el principito.pdf')
    expect(result.attachment?.type).toBe('application/pdf')
  })
})
