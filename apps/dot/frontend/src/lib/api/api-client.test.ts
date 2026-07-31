import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from './api-client'
import type { NotifiableError } from './api-client'

/** Mock global fetch */
const fetchMock = vi.fn()
vi.stubGlobal('fetch', fetchMock)

const fnErrorHandler = () => vi.fn() as unknown as (error: NotifiableError) => void

function mockResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 429 ? 'Too Many Requests' : status === 500 ? 'Internal Server Error' : 'OK',
    text: () => Promise.resolve(JSON.stringify(body)),
    headers: new Headers(),
  }
}

describe('ApiClient', () => {
  let errorHandler: (error: NotifiableError) => void

  beforeEach(() => {
    errorHandler = fnErrorHandler()
    apiClient.onError(errorHandler)
  })

  afterEach(() => {
    fetchMock.mockReset()
  })

  describe('get', () => {
    it('realiza GET y retorna el body parseado', async () => {
      fetchMock.mockResolvedValue(mockResponse(200, { data: 'ok' }))
      const result = await apiClient.get<{ data: string }>('/test')
      expect(result).toEqual({ data: 'ok' })
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/test'),
        expect.objectContaining({ method: 'GET' }),
      )
    })

    it('lanza ApiError en 404 sin notificar (es error de cliente recuperable)', async () => {
      fetchMock.mockResolvedValue(mockResponse(404, { detail: 'Not found' }))
      await expect(apiClient.get('/not-found')).rejects.toThrow()
      expect(errorHandler).toHaveBeenCalledWith(
        expect.objectContaining({ status: 404, context: '/not-found' }),
      )
    })

    it('notifica error en 500', async () => {
      fetchMock.mockResolvedValue(mockResponse(500, { detail: 'Server error' }))
      await expect(apiClient.get('/error')).rejects.toThrow()
      expect(errorHandler).toHaveBeenCalledWith(
        expect.objectContaining({ status: 500, message: 'Server error' }),
      )
    })
  })

  describe('post', () => {
    it('serializa body como JSON y envia POST', async () => {
      fetchMock.mockResolvedValue(mockResponse(200, { id: 1 }))
      const result = await apiClient.post('/items', { name: 'test' })
      expect(result).toEqual({ id: 1 })
      const callArgs = fetchMock.mock.calls[0][1]
      expect(callArgs.method).toBe('POST')
      expect(callArgs.body).toBe(JSON.stringify({ name: 'test' }))
    })

    it('no envia body si no se provee', async () => {
      fetchMock.mockResolvedValue(mockResponse(200, { ok: true }))
      await apiClient.post('/items')
      const callArgs = fetchMock.mock.calls[0][1]
      expect(callArgs.body).toBeUndefined()
    })
  })

  describe('patch', () => {
    it('serializa body como JSON y envia PATCH', async () => {
      fetchMock.mockResolvedValue(mockResponse(200, { updated: true }))
      const result = await apiClient.patch('/items/1', { name: 'updated' })
      expect(result).toEqual({ updated: true })
      const callArgs = fetchMock.mock.calls[0][1]
      expect(callArgs.method).toBe('PATCH')
    })
  })

  describe('del', () => {
    it('envia DELETE sin body', async () => {
      fetchMock.mockResolvedValue(mockResponse(200, { deleted: true }))
      const result = await apiClient.del('/items/1')
      expect(result).toEqual({ deleted: true })
      expect(fetchMock.mock.calls[0][1].method).toBe('DELETE')
    })
  })

  describe('auto-refresh en 401', () => {
    it('reintenta con nuevo token si getAccessToken lo refresca', async () => {
      let tokenCallCount = 0
      const getAccessToken = vi.fn().mockImplementation(async () => {
        tokenCallCount++
        if (tokenCallCount === 1) return 'expired-token'
        return 'fresh-token'
      })

      // Primer llamado: 401
      fetchMock.mockResolvedValueOnce(mockResponse(401, { detail: 'Token expired' }))
      // Segundo llamado: exito con token nuevo
      fetchMock.mockResolvedValueOnce(mockResponse(200, { data: 'ok' }))

      const result = await apiClient.get('/protected', getAccessToken)
      expect(result).toEqual({ data: 'ok' })
      // 3 llamadas: 1ra token inicial, 2da en catch tras 401, 3ra al recursar request()
      expect(getAccessToken).toHaveBeenCalledTimes(3)
    })

    it('no reintenta si getAccessToken devuelve el mismo token', async () => {
      const getAccessToken = vi.fn().mockResolvedValue('same-token')

      fetchMock.mockResolvedValue(mockResponse(401, { detail: 'Unauthorized' }))

      await expect(apiClient.get('/protected', getAccessToken)).rejects.toThrow()
      expect(fetchMock).toHaveBeenCalledTimes(1) // solo 1 intento, no reintenta
    })
  })

  describe('error handlers', () => {
    it('notifica a multiples handlers registrados', async () => {
      const handlerA = fnErrorHandler()
      const handlerB = fnErrorHandler()

      const unsubA = apiClient.onError(handlerA)
      apiClient.onError(handlerB)

      fetchMock.mockResolvedValue(mockResponse(500, { detail: 'Server error' }))
      await expect(apiClient.get('/test')).rejects.toThrow()

      expect(handlerA).toHaveBeenCalledOnce()
      expect(handlerB).toHaveBeenCalledOnce()

      // Desuscribir handlerA
      unsubA()
      fetchMock.mockResolvedValue(mockResponse(500, { detail: 'Another error' }))
      await expect(apiClient.get('/test2')).rejects.toThrow()

      expect(handlerA).toHaveBeenCalledTimes(1) // unchanged
      expect(handlerB).toHaveBeenCalledTimes(2) // +1
    })
  })
})
