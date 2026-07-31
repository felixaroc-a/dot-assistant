import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

import { AuthProvider } from './AuthProvider'
import { useAuth } from './auth-context'

const loadSecureJsonMock = vi.fn()
const migrateLegacyLocalStorageMock = vi.fn()
const loginWithCedulaMock = vi.fn()

vi.mock('@/lib/secure-session', () => ({
  loadSecureJson: () => loadSecureJsonMock(),
  migrateLegacyLocalStorage: () => migrateLegacyLocalStorageMock(),
  saveSecureJson: vi.fn(),
  clearSecureJson: vi.fn(),
}))

vi.mock('@/lib/api/auth-login', () => ({
  loginWithCedula: (...args: unknown[]) => loginWithCedulaMock(...args),
  logoutOnServer: vi.fn(),
  recoveryLogin: vi.fn(),
  refreshAccessToken: vi.fn(),
}))

vi.mock('@/lib/websocket-client', () => ({
  wsClient: { connect: vi.fn(), disconnect: vi.fn() },
}))

function wrapper({ children }: { children: ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>
}

describe('AuthProvider session restore', () => {
  beforeEach(() => {
    migrateLegacyLocalStorageMock.mockResolvedValue(undefined)
    loadSecureJsonMock.mockResolvedValue(null)
    loginWithCedulaMock.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('deja loading en false tras restaurar sesion vacia', async () => {
    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })
    expect(result.current.session).toBeNull()
    expect(result.current.sessionRestoreError).toBeNull()
  })

  it('expone error y muestra login si restore supera timeout', async () => {
    vi.useFakeTimers()
    loadSecureJsonMock.mockImplementation(
      () =>
        new Promise(() => {
          /* nunca resuelve */
        }),
    )

    const { result } = renderHook(() => useAuth(), { wrapper })

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })

    expect(result.current.loading).toBe(false)
    expect(result.current.session).toBeNull()
    expect(result.current.sessionRestoreError).toMatch(/Tiempo de espera agotado/)
  })

  it('login no vuelve a activar loading global', async () => {
    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    loginWithCedulaMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          setTimeout(
            () =>
              resolve({
                access_token: 'token',
                refresh_token: 'refresh',
                cliente: {
                  cliente_id: 'id-1',
                  cedula: 'V-12345678',
                  plan: 'anual',
                  fecha_vencimiento: '2030-12-31',
                },
              }),
            500,
          )
        }),
    )

    let loginPromise: Promise<void> | undefined
    act(() => {
      loginPromise = result.current.login('V-12345678', 'test123', null)
    })

    expect(result.current.loading).toBe(false)

    await act(async () => {
      await loginPromise
    })

    expect(result.current.loading).toBe(false)
    expect(result.current.session?.accessToken).toBe('token')
  })
})
