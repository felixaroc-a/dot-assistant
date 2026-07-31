import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  loginWithCedula,
  logoutOnServer,
  refreshAccessToken,
} from './auth-login'
import { ApiError } from './http'

const fetchMock = vi.fn()
vi.stubGlobal('fetch', fetchMock)

function mockResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 401 ? 'Unauthorized' : status === 403 ? 'Forbidden' : 'OK',
    text: () => Promise.resolve(body === undefined ? '' : JSON.stringify(body)),
    headers: new Headers(),
  }
}

const loginSuccessBody = {
  access_token: 'access-abc',
  refresh_token: 'refresh-xyz',
  token_type: 'bearer',
  expires_in: 3600,
  cliente: {
    cliente_id: 'uuid-1',
    cedula: '1234567890',
    plan: 'mensual',
    fecha_vencimiento: '2026-12-31',
    correo: 'test@example.com',
  },
}

describe('auth-login API', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8000')
  })

  afterEach(() => {
    fetchMock.mockReset()
  })

  describe('loginWithCedula', () => {
    it('POST /v1/auth/login con cedula trim y sin hardware_serial', async () => {
      fetchMock.mockResolvedValue(mockResponse(200, loginSuccessBody))

      const result = await loginWithCedula('  1234567890  ', 'secret')

      expect(result).toEqual(loginSuccessBody)
      expect(fetchMock).toHaveBeenCalledOnce()
      const [url, init] = fetchMock.mock.calls[0]
      expect(url).toBe('http://127.0.0.1:8000/v1/auth/login')
      expect(init.method).toBe('POST')
      expect(init.body).toBe(
        JSON.stringify({ cedula: '1234567890', password: 'secret' }),
      )
      const headers = init.headers as Headers
      expect(headers.get('Authorization')).toBeNull()
      expect(headers.get('Content-Type')).toBe('application/json')
    })

    it('incluye hardware_serial cuando se provee', async () => {
      fetchMock.mockResolvedValue(mockResponse(200, loginSuccessBody))

      await loginWithCedula('1234567890', 'secret', '  USB-SERIAL-1  ')

      const init = fetchMock.mock.calls[0][1]
      expect(init.body).toBe(
        JSON.stringify({
          cedula: '1234567890',
          password: 'secret',
          hardware_serial: 'USB-SERIAL-1',
        }),
      )
    })

    it('propaga 401 credenciales inválidas', async () => {
      fetchMock.mockResolvedValue(
        mockResponse(401, { detail: 'credenciales_invalidas' }),
      )

      await expect(loginWithCedula('1234567890', 'wrong')).rejects.toSatisfy(
        (err: unknown) =>
          err instanceof ApiError &&
          err.status === 401 &&
          err.message === 'credenciales_invalidas',
      )
    })

    it('propaga 403 subscription_expired', async () => {
      fetchMock.mockResolvedValue(
        mockResponse(403, { detail: 'subscription_expired' }),
      )

      await expect(loginWithCedula('1234567890', 'secret')).rejects.toSatisfy(
        (err: unknown) =>
          err instanceof ApiError &&
          err.status === 403 &&
          err.message === 'subscription_expired',
      )
    })
  })

  describe('refreshAccessToken', () => {
    it('POST /v1/auth/refresh con refresh_token', async () => {
      fetchMock.mockResolvedValue(
        mockResponse(200, {
          access_token: 'new-access',
          refresh_token: 'new-refresh',
          expires_in: 3600,
          token_type: 'bearer',
        }),
      )

      const result = await refreshAccessToken('old-refresh')

      expect(result.access_token).toBe('new-access')
      expect(result.refresh_token).toBe('new-refresh')
      const [url, init] = fetchMock.mock.calls[0]
      expect(url).toBe('http://127.0.0.1:8000/v1/auth/refresh')
      expect(init.method).toBe('POST')
      expect(init.body).toBe(JSON.stringify({ refresh_token: 'old-refresh' }))
    })
  })

  describe('logoutOnServer', () => {
    it('POST /v1/auth/logout con Bearer y refresh_token', async () => {
      fetchMock.mockResolvedValue(mockResponse(204, undefined))

      await logoutOnServer('access-token', 'refresh-token')

      const [url, init] = fetchMock.mock.calls[0]
      expect(url).toBe('http://127.0.0.1:8000/v1/auth/logout')
      expect(init.method).toBe('POST')
      expect(init.body).toBe(JSON.stringify({ refresh_token: 'refresh-token' }))
      const headers = init.headers as Headers
      expect(headers.get('Authorization')).toBe('Bearer access-token')
    })

    it('omite refresh_token en body cuando no se pasa', async () => {
      fetchMock.mockResolvedValue(mockResponse(204, undefined))

      await logoutOnServer('access-token')

      const init = fetchMock.mock.calls[0][1]
      expect(init.body).toBe(JSON.stringify({}))
    })
  })
})
