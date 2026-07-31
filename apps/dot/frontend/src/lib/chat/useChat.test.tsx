import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  sendMessageStreamMock: vi.fn(),
  sendMessageMock: vi.fn(),
  autoTitleConversationMock: vi.fn().mockResolvedValue(undefined),
  getConversationHistoryMock: vi.fn(),
  toChatErrorMock: vi.fn((error: unknown) => ({
    code: 'unknown' as const,
    message: error instanceof Error ? error.message : 'error',
  })),
}))

vi.mock('./client', () => ({
  sendMessage: mocks.sendMessageMock,
  sendMessageStream: mocks.sendMessageStreamMock,
  autoTitleConversation: mocks.autoTitleConversationMock,
  getConversationHistory: mocks.getConversationHistoryMock,
  toChatError: mocks.toChatErrorMock,
}))

import { useChat } from './useChat'

describe('useChat', () => {
  beforeEach(() => {
    mocks.sendMessageStreamMock.mockReset()
    mocks.sendMessageMock.mockReset()
    mocks.autoTitleConversationMock.mockReset()
    mocks.autoTitleConversationMock.mockResolvedValue(undefined)
    mocks.getConversationHistoryMock.mockReset()
    mocks.toChatErrorMock.mockClear()
  })

  it('evita envio duplicado concurrente mientras está enviando', async () => {
    mocks.sendMessageStreamMock.mockImplementation(
      async (
        _body: unknown,
        _accessToken: unknown,
        handlers: { onDone?: (conversationId: string) => void },
      ) => {
        await Promise.resolve()
        handlers.onDone?.('conv-1')
      },
    )

    const getAccessToken = vi.fn().mockResolvedValue('jwt-token')
    const { result } = renderHook(() =>
      useChat({ getAccessToken }),
    )

    await act(async () => {
      const first = result.current.send('hola 1')
      const second = result.current.send('hola 2')
      await Promise.all([first, second])
    })

    expect(getAccessToken).toHaveBeenCalled()
    expect(mocks.sendMessageStreamMock).toHaveBeenCalledTimes(1)
    expect(result.current.messages.filter((m) => m.role === 'user')).toHaveLength(1)
  })

  it('marca el mensaje assistant como error ante fallo de stream', async () => {
    mocks.sendMessageStreamMock.mockImplementation(
      async (
        _body: unknown,
        _accessToken: unknown,
        handlers: {
          onToken?: (token: string) => void
          onError?: (error: string) => void
        },
      ) => {
        handlers.onToken?.('Respuesta parcial')
        handlers.onError?.('fallo de stream')
      },
    )

    const { result } = renderHook(() =>
      useChat({
        getAccessToken: async () => 'jwt-token',
      }),
    )

    await act(async () => {
      await result.current.send('mensaje de prueba')
    })

    const assistant = result.current.messages[result.current.messages.length - 1]
    expect(assistant.role).toBe('assistant')
    expect(assistant.status).toBe('error')
    expect(assistant.text).toBe('Respuesta parcial')
    expect(result.current.lastError?.message).toBe('fallo de stream')
    expect(result.current.isSending).toBe(false)
  })

  it('actualiza conversationId tras recibir el id del backend', async () => {
    mocks.sendMessageStreamMock.mockImplementation(
      async (
        _body: unknown,
        _accessToken: unknown,
        handlers: { onDone?: (conversationId: string) => void },
      ) => {
        handlers.onDone?.('conv-new')
      },
    )

    const onConversationIdChange = vi.fn()
    const { result } = renderHook(() =>
      useChat({
        getAccessToken: async () => 'jwt-token',
        onConversationIdChange,
      }),
    )

    await act(async () => {
      await result.current.send('primer mensaje')
    })

    expect(result.current.conversationId).toBe('conv-new')
    expect(onConversationIdChange).toHaveBeenCalledWith('conv-new')
  })

  it('muestra displayText/attachment en UI y envía texto completo al API', async () => {
    mocks.sendMessageStreamMock.mockImplementation(
      async (
        _body: unknown,
        _accessToken: unknown,
        handlers: { onDone?: (conversationId: string) => void },
      ) => {
        handlers.onDone?.('conv-doc')
      },
    )

    const { result } = renderHook(() =>
      useChat({ getAccessToken: async () => 'jwt-token' }),
    )

    const apiText =
      '[Documento: a.pdf]\n\nContenido extraído:\nbody\n\n---\nInstrucción del usuario: resume'
    await act(async () => {
      await result.current.send(apiText, {
        displayText: 'resume',
        attachment: { name: 'a.pdf', type: 'application/pdf', size: 12 },
      })
    })

    const user = result.current.messages.find((m) => m.role === 'user')
    expect(user?.text).toBe('resume')
    expect(user?.attachment?.name).toBe('a.pdf')
    expect(mocks.sendMessageStreamMock).toHaveBeenCalledWith(
      expect.objectContaining({ text: apiText }),
      'jwt-token',
      expect.objectContaining({
        onToken: expect.any(Function),
        onDone: expect.any(Function),
        onError: expect.any(Function),
      }),
    )
  })

  it('carga historial al cambiar de conversacion', async () => {
    const history = [
      {
        id: 'm1',
        role: 'user' as const,
        text: 'Hola',
        createdAt: '2026-01-01T00:00:00.000Z',
        status: 'sent' as const,
      },
    ]
    mocks.getConversationHistoryMock.mockResolvedValue({ messages: history })

    const { result } = renderHook(() =>
      useChat({ getAccessToken: async () => 'jwt-token' }),
    )

    await act(async () => {
      await result.current.loadConversation('conv-hist')
    })

    expect(mocks.getConversationHistoryMock).toHaveBeenCalledWith('conv-hist', 'jwt-token')
    expect(result.current.messages).toEqual(history)
    expect(result.current.conversationId).toBe('conv-hist')
  })

  it('auto-titula tras el primer intercambio y refresca la lista', async () => {
    mocks.sendMessageStreamMock.mockImplementation(
      async (
        _body: unknown,
        _accessToken: unknown,
        handlers: { onDone?: (conversationId: string) => void },
      ) => {
        handlers.onDone?.('conv-title')
      },
    )

    const onExchangeComplete = vi.fn()
    const { result } = renderHook(() =>
      useChat({
        getAccessToken: async () => 'jwt-token',
        onExchangeComplete,
      }),
    )

    await act(async () => {
      await result.current.send('Mi primera pregunta sobre Python')
    })

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })

    expect(mocks.autoTitleConversationMock).toHaveBeenCalledWith(
      'conv-title',
      'Mi primera pregunta sobre Python',
      'jwt-token',
    )
    expect(onExchangeComplete).toHaveBeenCalled()
  })
})
