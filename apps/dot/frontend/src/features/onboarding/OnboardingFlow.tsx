import { AnimatePresence } from 'framer-motion'
import { useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import { LoadingScreen } from '@/components/LoadingScreen'
import { useToast } from '@/components/Toast'
import { LoginScreen, useAuth } from '@/features/auth'
import { DashboardShell } from '@/features/dashboard'
import type { IntegrationId } from '@/features/integrations'
import { CompletionSplash } from '@/features/onboarding/components/completion-splash'
import { GoogleAutomationOAuthStep } from '@/features/onboarding/components/google-automation-oauth/GoogleAutomationOAuthStep'
import { PersonalizeStep } from '@/features/onboarding/components/personalize-step/PersonalizeStep'
import { ProgressBar } from '@/features/onboarding/components/progress-bar/ProgressBar'
import { WelcomeStep } from '@/features/onboarding/components/welcome-step'
import { WhatsappLinkStep } from '@/features/onboarding/components/whatsapp-openclaw'
import { useOnboardingFlow } from '@/features/onboarding/hooks/useOnboardingFlow'
import { useProfileBootstrap } from '@/features/onboarding/hooks/useProfileBootstrap'
import { getChannelMeta } from '@/features/onboarding/model/channel.meta'
import type { ChannelId } from '@/features/onboarding/model/channel.types'
import type { OnboardingFlowStep } from '@/features/onboarding/model/flow.types'
import { stepToNumber } from '@/features/onboarding/model/flow.types'
import i18n from '@/lib/i18n/config'

type OnboardingFlowProps = {
  onLostPendrive?: () => void
}

export function OnboardingFlow({ onLostPendrive }: OnboardingFlowProps) {
  const { t } = useTranslation()
  const { success } = useToast()
  const { getAccessToken, session } = useAuth()
  const sessionClientId = session?.cliente?.cliente_id ?? null
  const flow = useOnboardingFlow(getAccessToken)

  const handleProfileLoaded = useCallback(
    (profile: {
      displayName: string
      channel: ChannelId | null
      integrations: IntegrationId[]
      step: OnboardingFlowStep
    }) => {
      flow.setDisplayName(profile.displayName)
      if (profile.step === 'dashboard') {
        flow.setFlowStep('dashboard')
        return
      }
      flow.setSelectedChannel(profile.channel)
      flow.setSelectedIntegrations(profile.integrations)
      // Si el perfil del servidor dice que el onboarding NO está completo,
      // siempre empezar desde welcome (ignora sessionStorage obsoleto).
      flow.setFlowStep('welcome')
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [flow.setDisplayName, flow.setSelectedChannel, flow.setSelectedIntegrations, flow.setFlowStep],
  )

  const { bootstrapped: profileBootstrapped } = useProfileBootstrap({
    sessionClientId,
    getAccessToken,
    onProfileLoaded: handleProfileLoaded,
  })

  const channelLabel = useMemo(
    () => (flow.selectedChannel !== null ? getChannelMeta(flow.selectedChannel).name : null),
    [flow.selectedChannel],
  )

  const googleIntegrations = useMemo(
    () => flow.selectedIntegrations.length > 0
      ? flow.selectedIntegrations.filter((id) => id === 'gmail' || id === 'google-calendar')
      : ['gmail', 'google-calendar'] as IntegrationId[],
    [flow.selectedIntegrations],
  )

  const currentStepNum = stepToNumber(flow.flowStep)
  const showProgress = currentStepNum >= 1 && currentStepNum <= 4

  if (!session) {
    return <LoginScreen onLostPendrive={onLostPendrive} />
  }

  if (!profileBootstrapped) {
    return <LoadingScreen message={t('loading.loading_profile')} />
  }

  // Auto-detect: if profile is bootstrapped as completed, go straight to dashboard
  if (flow.flowStep === 'dashboard') {
    return (
      <DashboardShell
        userDisplayName={flow.displayName}
        channelLabel={channelLabel}
        profileSyncWarning={flow.profileSyncWarning}
      />
    )
  }

  const handleWhatsAppSkip = () => flow.setFlowStep('google')
  const handleGoogleSkip = () => flow.setFlowStep('personalize')

  // When user completes personalize, also set channel/integrations based on what was chosen
  const handlePersonalizeComplete = async (opts: { displayName: string; language: string; wakeWord: boolean }) => {
    flow.setWakeWordEnabled(opts.wakeWord)
    flow.setLanguage(opts.language)

    // Auto-set WhatsApp as channel if they scanned during the step
    const hasWhatsApp = flow.selectedChannel === 'whatsapp'

    // Persist language preference
    try {
      localStorage.setItem('dot-lang', opts.language)
      await i18n.changeLanguage(opts.language)
    } catch {
      /* ignore i18n error */
    }

    await flow.completeOnboarding(opts.displayName)

    const integrationList = flow.selectedIntegrations.length > 0
      ? flow.selectedIntegrations.join(', ')
      : ''

    const parts: string[] = ['DOT ya está listo.']
    if (hasWhatsApp) {
      parts.push('WhatsApp vinculado.')
    }
    if (integrationList) {
      parts.push(`Integraciones activas: ${integrationList}.`)
    }
    parts.push('Briefing matutino activado (7:30). «Avísame cuando…» ya está encendido: ajústalo en Configuración → Notificaciones.')
    success(parts.join(' '))
  }

  return (
    <>
      {showProgress ? <ProgressBar currentStep={currentStepNum} /> : null}
      <AnimatePresence mode="wait">
        {flow.flowStep === 'welcome' ? (
          <WelcomeStep
            key="welcome"
            onContinue={() => flow.setFlowStep('whatsapp')}
          />
        ) : flow.flowStep === 'whatsapp' ? (
          <WhatsappLinkStep
            key="whatsapp"
            onBack={() => flow.setFlowStep('welcome')}
            onSkip={handleWhatsAppSkip}
            onContinue={handleWhatsAppSkip}
          />
        ) : flow.flowStep === 'google' ? (
          <GoogleAutomationOAuthStep
            key="google-oauth"
            googleIntegrations={googleIntegrations}
            getAccessToken={getAccessToken}
            onBack={() => flow.setFlowStep('whatsapp')}
            onSkip={handleGoogleSkip}
            onContinueToSummary={handleGoogleSkip}
          />
        ) : flow.flowStep === 'personalize' ? (
          <PersonalizeStep
            key="personalize"
            initialName={flow.displayName}
            initialLanguage={flow.language}
            initialWakeWord={flow.wakeWordEnabled}
            onBack={() => flow.setFlowStep('google')}
            onComplete={handlePersonalizeComplete}
          />
        ) : flow.flowStep === 'completion' ? (
          <CompletionSplash
            key="completion"
            onComplete={() => flow.setFlowStep('dashboard')}
          />
        ) : (
          <DashboardShell
            key="dashboard"
            userDisplayName={flow.displayName}
            channelLabel={channelLabel}
            profileSyncWarning={flow.profileSyncWarning}
          />
        )}
      </AnimatePresence>
    </>
  )
}
