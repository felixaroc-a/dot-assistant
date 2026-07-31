import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  CHAT_STREAM_ABSOLUTE_TIMEOUT_MS,
  CHAT_STREAM_IDLE_TIMEOUT_MS,
  sendMessageStream,
  toChatError,
} from './client'

vi.mock('@/lib/api/base-url', () => ({
  getApiBaseUrl: vi.fn(() => 'http://127.0.0.1:8000'),
}))

function buildSseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk))
      }
      controller.close()
    },
  })
  return new Response(stream, { status: 200 })
}

describe('sendMessageStream', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('usa idle largo y techo absoluto (no abort fijo a 120s)', () => {
    expect(CHAT_STREAM_IDLE_TIMEOUT_MS).toBeGreaterThanOrEqual(180_000)
    expect(CHAT_STREAM_ABSOLUTE_TIMEOUT_MS).toBeGreaterThanOrEqual(900_000)
  })

  it('dispara onDone al cerrar stream sin evento done', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        buildSseResponse([
          'data: {"token":"Hola","conversation_id":"conv-123"}\n\n',
        ]),
      )
    vi.stubGlobal('fetch', fetchMock)

    const onToken = vi.fn()
    const onDone = vi.fn()
    const onError = vi.fn()

    await sendMessageStream(
      { text: 'hola' },
      'token',
      {
        onToken,
        onDone,
        onError,
      },
    )

    expect(onToken).toHaveBeenCalledWith('Hola')
    expect(onDone).toHaveBeenCalledTimes(1)
    expect(onDone).toHaveBeenCalledWith('conv-123')
    expect(onError).not.toHaveBeenCalled()
  })

  it('no duplica onDone cuando llega evento done', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        buildSseResponse([
          'data: {"token":"A","conversation_id":"conv-777"}\n',
          'data: {"done":true,"conversation_id":"conv-777"}\n\n',
        ]),
      )
    vi.stubGlobal('fetch', fetchMock)

    const onDone = vi.fn()

    await sendMessageStream(
      { text: 'hola' },
      'token',
      {
        onToken: vi.fn(),
        onDone,
        onError: vi.fn(),
      },
    )

    expect(onDone).toHaveBeenCalledTimes(1)
    expect(onDone).toHaveBeenCalledWith('conv-777')
  })

  it('reinicia idle con heartbeats y no aborta a los 120s', async () => {
    vi.useFakeTimers()
    const encoder = new TextEncoder()
    let pullCount = 0
    const stream = new ReadableStream<Uint8Array>({
      async pull(controller) {
        pullCount += 1
        if (pullCount === 1) {
          controller.enqueue(encoder.encode('data: {"type":"heartbeat","t":1}\n\n'))
          return
        }
        if (pullCount === 2) {
          // Simula trabajo largo: el cliente ya pasó 120s wall-clock
          await vi.advanceTimersByTimeAsync(130_000)
          controller.enqueue(
            encoder.encode(
              'data: {"token":"ok","conversation_id":"c1"}\n\ndata: {"done":true,"conversation_id":"c1"}\n\n',
            ),
          )
          controller.close()
        }
      },
    })
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue(new Response(stream, { status: 200 })),
    )

    const onError = vi.fn()
    const onDone = vi.fn()
    const onToken = vi.fn()

    const pending = sendMessageStream(
      { text: 'informe profundo' },
      'token',
      { onToken, onDone, onError },
    )

    await vi.runAllTimersAsync()
    await pending

    expect(onError).not.toHaveBeenCalled()
    expect(onToken).toHaveBeenCalledWith('ok')
    expect(onDone).toHaveBeenCalledWith('c1')
  })
})

describe('toChatError', () => {
  it('mapea Failed to fetch contra API local como backend inalcanzable', () => {
    const error = toChatError(new TypeError('Failed to fetch'))

    expect(error.code).toBe('network')
    expect(error.message).toContain('conectar con el servicio')
    expect(error.message).not.toMatch(/npm/i)
  })
})
