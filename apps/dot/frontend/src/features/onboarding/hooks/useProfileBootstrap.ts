import { useEffect, useState } from 'react'

import type { IntegrationId } from '@/features/integrations'
import type { ChannelId } from '@/features/onboarding/model/channel.types'
import type { OnboardingFlowStep } from '@/features/onboarding/model/flow.types'
import { filterIntegrationIds, isChannelId } from '@/features/onboarding/model/validators'
import type { GetAccessToken } from '@/lib/api/client'
import { apiFetchAuthed } from '@/lib/api/client'
import type { UserProfileDto } from '@/lib/api/user-profile'
import { translateError } from '@/lib/error-messages'

export type UseProfileBootstrapResult = {
  /** Indica si el perfil ya fue cargado */
  bootstrapped: boolean
  /** Mensaje de error si algo fallo al cargar el perfil */
  error: string | null
}

export type UseProfileBootstrapOptions = {
  sessionClientId: string | null
  getAccessToken: GetAccessToken
  /** Callback cuando se carga el perfil exitosamente */
  onProfileLoaded?: (profile: {
    displayName: string
    channel: ChannelId | null
    integrations: IntegrationId[]
    step: OnboardingFlowStep
  }) => void
}

/**
 * Hook encargado de cargar el perfil del usuario desde la API
 * cuando se monta el onboarding, y notificar con los datos parseados.
 *
 * Single Responsibility: Solo carga y parsea el perfil.
 * No sabe nada de sesionStorage ni del flujo de pasos.
 */
export function useProfileBootstrap({
  sessionClientId,
  getAccessToken,
  onProfileLoaded,
}: UseProfileBootstrapOptions): UseProfileBootstrapResult {
  const [bootstrapped, setBootstrapped] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!sessionClientId) {
      setBootstrapped(false)
      setError(null)
      return
    }

    let cancelled = false
    setBootstrapped(false)
    setError(null)

    void (async () => {
      try {
        const profile = await apiFetchAuthed<UserProfileDto>(
          '/users/me/profile',
          { method: 'GET' },
          getAccessToken,
        )
        if (cancelled) return

        const displayName =
          typeof profile.display_name === 'string' && profile.display_name.trim()
            ? profile.display_name.trim()
            : ''
        const channel = typeof profile.channel_id === 'string' && isChannelId(profile.channel_id)
          ? profile.channel_id
          : null
        const integrations = Array.isArray(profile.integrations)
          ? filterIntegrationIds(profile.integrations)
          : []
        const onboardingComplete = Boolean(profile.onboarding_completed)
        const hasDisplayName = typeof profile.display_name === 'string' && profile.display_name.trim().length > 0
        const step: OnboardingFlowStep = onboardingComplete && hasDisplayName
          ? 'dashboard'
          : 'welcome'

        onProfileLoaded?.({ displayName, channel, integrations, step })
      } catch (err) {
        const message = translateError(err, 'No se pudo cargar tu perfil. Intenta de nuevo.')
        console.warn('[useProfileBootstrap] No se pudo cargar perfil:', err)
        if (!cancelled) {
          setError(message)
          onProfileLoaded?.({
            displayName: '',
            channel: null,
            integrations: [],
            step: 'welcome',
          })
        }
      } finally {
        if (!cancelled) {
          setBootstrapped(true)
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [sessionClientId, getAccessToken, onProfileLoaded])

  return { bootstrapped, error }
}
