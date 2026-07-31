import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useProfileBootstrap } from './useProfileBootstrap'

const apiFetchAuthedMock = vi.fn()

vi.mock('@/lib/api/client', () => ({
  apiFetchAuthed: (...args: unknown[]) => apiFetchAuthedMock(...args),
}))

describe('useProfileBootstrap', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('bootstrapped=false si no hay sessionClientId', () => {
    const { result } = renderHook(() =>
      useProfileBootstrap({
        sessionClientId: null,
        getAccessToken: vi.fn(),
      }),
    )
    expect(result.current.bootstrapped).toBe(false)
    expect(result.current.error).toBeNull()
    expect(apiFetchAuthedMock).not.toHaveBeenCalled()
  })

  it('carga el perfil al montarse y llama onProfileLoaded con los datos parseados', async () => {
    apiFetchAuthedMock.mockResolvedValue({
      display_name: 'Ana',
      channel_id: 'whatsapp',
      integrations: ['gmail', 'google-calendar'],
      onboarding_completed: false,
    })

    const onProfileLoaded = vi.fn()

    const { result } = renderHook(() =>
      useProfileBootstrap({
        sessionClientId: 'cliente-1',
        getAccessToken: vi.fn().mockResolvedValue('token'),
        onProfileLoaded,
      }),
    )

    expect(result.current.bootstrapped).toBe(false)

    await waitFor(() => {
      expect(result.current.bootstrapped).toBe(true)
    })

    expect(apiFetchAuthedMock).toHaveBeenCalledWith(
      '/users/me/profile',
      { method: 'GET' },
      expect.any(Function),
    )

    expect(onProfileLoaded).toHaveBeenCalledWith({
      displayName: 'Ana',
      channel: 'whatsapp',
      integrations: ['gmail', 'google-calendar'],
      step: 'welcome',
    })
  })

  it('detecta onboarding completado y notifica step=dashboard', async () => {
    apiFetchAuthedMock.mockResolvedValue({
      display_name: 'Ana',
      channel_id: null,
      integrations: [],
      onboarding_completed: true,
    })

    const onProfileLoaded = vi.fn()

    renderHook(() =>
      useProfileBootstrap({
        sessionClientId: 'cliente-1',
        getAccessToken: vi.fn().mockResolvedValue('token'),
        onProfileLoaded,
      }),
    )

    await waitFor(() => {
      expect(onProfileLoaded).toHaveBeenCalledWith(
        expect.objectContaining({ step: 'dashboard' }),
      )
    })
  })

  it('filtra integraciones invalidas del perfil', async () => {
    apiFetchAuthedMock.mockResolvedValue({
      display_name: '',
      channel_id: null,
      integrations: ['gmail', 'outlook', 'google-calendar', 'slack'],
      onboarding_completed: false,
    })

    const onProfileLoaded = vi.fn()

    renderHook(() =>
      useProfileBootstrap({
        sessionClientId: 'cliente-1',
        getAccessToken: vi.fn().mockResolvedValue('token'),
        onProfileLoaded,
      }),
    )

    await waitFor(() => {
      expect(onProfileLoaded).toHaveBeenCalledWith(
        expect.objectContaining({
          integrations: ['gmail', 'google-calendar'],
        }),
      )
    })
  })

  it('maneja error de API gracefulmente (onProfileLoaded con defaults y error seteado)', async () => {
    apiFetchAuthedMock.mockRejectedValue(new Error('Network error'))

    const onProfileLoaded = vi.fn()

    const { result } = renderHook(() =>
      useProfileBootstrap({
        sessionClientId: 'cliente-1',
        getAccessToken: vi.fn().mockResolvedValue('token'),
        onProfileLoaded,
      }),
    )

    await waitFor(() => {
      expect(result.current.bootstrapped).toBe(true)
      expect(result.current.error).toBe('Network error')
    })

    // Incluso con error, llama onProfileLoaded con defaults para no bloquear el flujo
    expect(onProfileLoaded).toHaveBeenCalledWith({
      displayName: '',
      channel: null,
      integrations: [],
      step: 'welcome',
    })
  })

  it('no llama onProfileLoaded si se desmonta antes de completar', async () => {
    // Promesa que nunca se resuelve
    apiFetchAuthedMock.mockReturnValue(new Promise(() => {}))

    const onProfileLoaded = vi.fn()

    const { unmount } = renderHook(() =>
      useProfileBootstrap({
        sessionClientId: 'cliente-1',
        getAccessToken: vi.fn().mockResolvedValue('token'),
        onProfileLoaded,
      }),
    )

    unmount()

    // Esperar un tick para verificar que no hubo llamadas
    await new Promise((r) => setTimeout(r, 50))
    expect(onProfileLoaded).not.toHaveBeenCalled()
  })

  it('parsea display_name con espacios como trim', async () => {
    apiFetchAuthedMock.mockResolvedValue({
      display_name: '  Ana Maria  ',
      channel_id: null,
      integrations: [],
      onboarding_completed: false,
    })

    const onProfileLoaded = vi.fn()

    renderHook(() =>
      useProfileBootstrap({
        sessionClientId: 'cliente-1',
        getAccessToken: vi.fn().mockResolvedValue('token'),
        onProfileLoaded,
      }),
    )

    await waitFor(() => {
      expect(onProfileLoaded).toHaveBeenCalledWith(
        expect.objectContaining({ displayName: 'Ana Maria' }),
      )
    })
  })
})
