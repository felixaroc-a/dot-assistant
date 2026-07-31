import { useCallback, useEffect, useState } from 'react'

import type { IntegrationId } from '@/features/integrations'
import { getIntegrationById } from '@/features/integrations'
import type { OnboardingFlowStep } from '@/features/onboarding/model/flow.types'
import type { ChannelId } from '@/features/onboarding/model/channel.types'
import { apiFetchAuthed } from '@/lib/api/client'
import type { GetAccessToken } from '@/lib/api/client'
import { translateError } from '@/lib/error-messages'

const SS_KEY_STEP = 'dot_onboarding_step'
const SS_KEY_CHANNEL = 'dot_onboarding_channel'
const SS_KEY_INTEGRATIONS = 'dot_onboarding_integrations'
const SS_KEY_DISPLAY_NAME = 'dot_onboarding_display_name'
const SS_KEY_LANGUAGE = 'dot_onboarding_language'
const SS_KEY_WAKE_WORD = 'dot_onboarding_wake_word'
const SS_KEY_LEGAL_ACCEPTANCE = 'dot_onboarding_legal_acceptance'

function loadFromSession<T>(key: string, fallback: T): T {
  try {
    const raw = sessionStorage.getItem(key)
    if (raw !== null) return JSON.parse(raw) as T
  } catch {
    /* ignore corrupt data */
  }
  return fallback
}

function saveToSession(key: string, value: unknown): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* storage full or blocked — ignore */
  }
}

function clearOnboardingSession(): void {
  try {
    sessionStorage.removeItem(SS_KEY_STEP)
    sessionStorage.removeItem(SS_KEY_CHANNEL)
    sessionStorage.removeItem(SS_KEY_INTEGRATIONS)
    sessionStorage.removeItem(SS_KEY_DISPLAY_NAME)
    sessionStorage.removeItem(SS_KEY_LANGUAGE)
    sessionStorage.removeItem(SS_KEY_WAKE_WORD)
    sessionStorage.removeItem(SS_KEY_LEGAL_ACCEPTANCE)
  } catch {
    /* ignore */
  }
}

export function useOnboardingFlow(getAccessToken: GetAccessToken) {
  const [flowStep, setFlowStep_] = useState<OnboardingFlowStep>(
    loadFromSession<OnboardingFlowStep>(SS_KEY_STEP, 'welcome'),
  )
  const [selectedChannel, setSelectedChannel_] = useState<ChannelId | null>(
    loadFromSession<ChannelId | null>(SS_KEY_CHANNEL, null),
  )
  const [selectedIntegrations, setSelectedIntegrations_] = useState<IntegrationId[]>(
    loadFromSession<IntegrationId[]>(SS_KEY_INTEGRATIONS, []),
  )
  const [displayName, setDisplayName] = useState(
    loadFromSession<string>(SS_KEY_DISPLAY_NAME, ''),
  )
  const [language, setLanguage_] = useState(
    loadFromSession<string>(SS_KEY_LANGUAGE, 'es'),
  )
  const [wakeWordEnabled, setWakeWordEnabled_] = useState(
    loadFromSession<boolean>(SS_KEY_WAKE_WORD, true),
  )
  const [profileSyncWarning, setProfileSyncWarning] = useState<string | null>(null)
  const [legalAccepted, setLegalAccepted_] = useState<boolean>(
    loadFromSession<boolean>(SS_KEY_LEGAL_ACCEPTANCE, false),
  )

  /* ── Persist selected state to sessionStorage ── */
  const setFlowStep: typeof setFlowStep_ = useCallback((stepOrFn) => {
    setFlowStep_((prev) => {
      const next = typeof stepOrFn === 'function' ? stepOrFn(prev) : stepOrFn
      if (next === 'dashboard') clearOnboardingSession()
      else saveToSession(SS_KEY_STEP, next)
      return next
    })
  }, [])

  const setSelectedChannel: typeof setSelectedChannel_ = useCallback((valueOrFn) => {
    setSelectedChannel_((prev) => {
      const next = typeof valueOrFn === 'function' ? valueOrFn(prev) : valueOrFn
      saveToSession(SS_KEY_CHANNEL, next)
      return next
    })
  }, [])

  const setSelectedIntegrations: typeof setSelectedIntegrations_ = useCallback((valueOrFn) => {
    setSelectedIntegrations_((prev) => {
      const next = typeof valueOrFn === 'function' ? valueOrFn(prev) : valueOrFn
      saveToSession(SS_KEY_INTEGRATIONS, next)
      return next
    })
  }, [])

  const setLanguage: typeof setLanguage_ = useCallback((valueOrFn) => {
    setLanguage_((prev) => {
      const next = typeof valueOrFn === 'function' ? valueOrFn(prev) : valueOrFn
      saveToSession(SS_KEY_LANGUAGE, next)
      return next
    })
  }, [])

  const setWakeWordEnabled: typeof setWakeWordEnabled_ = useCallback((valueOrFn) => {
    setWakeWordEnabled_((prev) => {
      const next = typeof valueOrFn === 'function' ? valueOrFn(prev) : valueOrFn
      saveToSession(SS_KEY_WAKE_WORD, next)
      return next
    })
  }, [])

  const setLegalAccepted: typeof setLegalAccepted_ = useCallback((valueOrFn) => {
    setLegalAccepted_((prev) => {
      const next = typeof valueOrFn === 'function' ? valueOrFn(prev) : valueOrFn
      saveToSession(SS_KEY_LEGAL_ACCEPTANCE, next)
      return next
    })
  }, [])

  /* Sync displayName to session on change */
  useEffect(() => {
    saveToSession(SS_KEY_DISPLAY_NAME, displayName)
  }, [displayName])

  const completeOnboarding = useCallback(
    async (name: string) => {
      const automationSummary =
        selectedIntegrations.length === 0
          ? null
          : selectedIntegrations.map((id) => getIntegrationById(id).label).join(', ')
      const payload = {
        display_name: name,
        channel_id: selectedChannel,
        ai_provider_id: 'deepseek',
        integrations: selectedIntegrations.length > 0
          ? selectedIntegrations.filter((id) => id === 'gmail' || id === 'google-calendar')
          : [],
        automation_summary: automationSummary,
        onboarding_completed: true,
        legal_acceptance: legalAccepted ? new Date().toISOString() : undefined,
        preferred_language: language,
        wake_word_enabled: wakeWordEnabled,
      }
      try {
        await apiFetchAuthed(
          '/users/me/profile',
          {
            method: 'PATCH',
            body: JSON.stringify(payload),
          },
          getAccessToken,
        )
        setProfileSyncWarning(null)
      } catch (e) {
        const message =
          translateError(e, 'No se pudo guardar el perfil en el servidor.')
        setProfileSyncWarning(message)
      }
      setDisplayName(name)
      setFlowStep('completion')
    },
    [getAccessToken, selectedChannel, selectedIntegrations, legalAccepted, language, wakeWordEnabled, setFlowStep],
  )

  return {
    flowStep,
    setFlowStep,
    selectedChannel,
    setSelectedChannel,
    selectedIntegrations,
    setSelectedIntegrations,
    displayName,
    setDisplayName,
    language,
    setLanguage,
    wakeWordEnabled,
    setWakeWordEnabled,
    profileSyncWarning,
    legalAccepted,
    setLegalAccepted,
    completeOnboarding,
  }
}
