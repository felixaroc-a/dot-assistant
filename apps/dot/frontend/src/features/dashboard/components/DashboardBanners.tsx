import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import type { SubscriptionReminder } from '@/features/dashboard/lib/subscription-reminder'
import type { WhatsAppLinkStatus } from '@/lib/api/whatsapp'

export type DashboardBannersProps = {
  planLabel: string
  subscriptionReminder: SubscriptionReminder | null
  profileSyncWarning?: string | null
  whatsappStatus: WhatsAppLinkStatus
  channelLabel?: string | null
  onOpenIntegrations?: () => void
}

export function DashboardBanners({
  planLabel,
  subscriptionReminder,
  profileSyncWarning,
  whatsappStatus,
  channelLabel,
  onOpenIntegrations,
}: DashboardBannersProps) {
  const { t } = useTranslation()
  const channelBannerMessage = useMemo(() => {
    if (whatsappStatus === 'pending_verification') {
      return t('dashboard.channel_banner_pending')
    }
    if (whatsappStatus === 'disconnected') {
      return t('dashboard.channel_banner_rescan')
    }
    if (whatsappStatus === 'connecting') {
      return t('dashboard.channel_banner_connecting')
    }
    return t('dashboard.channel_banner_connecting')
  }, [t, whatsappStatus])

  return (
    <>
      <aside className="main-dashboard__plan-banner" role="status">
        <strong>Plan:</strong> {planLabel}
      </aside>

      {subscriptionReminder ? (
        <aside className="main-dashboard__expiry-banner" role="status" aria-live="polite">
          <strong>Suscripción:</strong> {subscriptionReminder.bannerText}
        </aside>
      ) : null}

      {profileSyncWarning ? (
        <aside className="main-dashboard__sync-warning" role="alert">
          {profileSyncWarning}
        </aside>
      ) : null}

      {channelLabel && whatsappStatus !== 'linked' ? (
        <aside className="main-dashboard__channel-banner" role="status">
          <strong>{t('dashboard.channel', { channel: channelLabel })}</strong> — {channelBannerMessage}
          {onOpenIntegrations ? (
            <>
              {' '}
              <button
                type="button"
                className="main-dashboard__channel-banner-link"
                onClick={onOpenIntegrations}
              >
                Abrir sesiones
              </button>
            </>
          ) : null}
        </aside>
      ) : null}
    </>
  )
}
