import { describe, expect, it } from 'vitest'

import type { ChatMessage } from '@/lib/chat/types'
import { buildChatExportDocument } from './chat-export'

describe('buildChatExportDocument', () => {
  it('formatea la conversación con metadatos y mensajes', () => {
    const messages: ChatMessage[] = [
      {
        id: '1',
        role: 'user',
        text: 'Hola DOTa',
        createdAt: '2030-01-01T10:00:00.000Z',
        status: 'sent',
      },
      {
        id: '2',
        role: 'assistant',
        text: 'Hola, ¿en qué te ayudo?',
        createdAt: '2030-01-01T10:00:10.000Z',
        status: 'sent',
      },
    ]

    const result = buildChatExportDocument(
      messages,
      'Felix',
      new Date('2030-01-02T08:30:00.000Z'),
    )

    expect(result.title).toContain('Conversación DOT 2030-01-02')
    expect(result.content).toContain('# Conversación DOT IA')
    expect(result.content).toContain('Usuario: Felix')
    expect(result.content).toContain('### 1. Felix')
    expect(result.content).toContain('### 2. DOTa')
    expect(result.content).toContain('Hola, ¿en qué te ayudo?')
  })

  it('marca mensajes en error y maneja chat vacío', () => {
    const oneError: ChatMessage[] = [
      {
        id: '1',
        role: 'user',
        text: '',
        createdAt: 'invalid-date',
        status: 'error',
      },
    ]

    const resultWithError = buildChatExportDocument(oneError, '', new Date('2030-01-02T08:30:00.000Z'))
    expect(resultWithError.content).toContain('[no enviado]')
    expect(resultWithError.content).toContain('(mensaje vacío)')
    expect(resultWithError.content).toContain('Usuario: Usuario')

    const empty = buildChatExportDocument([], 'Ana', new Date('2030-01-02T08:30:00.000Z'))
    expect(empty.content).toContain('Sin mensajes disponibles para exportar')
  })
})
