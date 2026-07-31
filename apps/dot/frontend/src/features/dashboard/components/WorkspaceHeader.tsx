import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { AgentId } from '@/features/dashboard/model/types'
import { WORKSPACE_AGENTS } from '@/features/dashboard/model/agents'
import { LogoutConfirmModal } from '@/features/auth/LogoutConfirmModal'
import { UsageMeter } from '@/features/dashboard/components/UsageMeter'
import type { UsageSummary } from '@/lib/api/usage'
import type { WhatsAppLinkStatus } from '@/lib/api/whatsapp'
import { useOnlineStatus } from '@/lib/use-online-status'

export type WorkspaceHeaderProps = {
  selectedAgent: AgentId
  onAgentChange: (id: AgentId) => void
  userDisplayName: string
  channelLabel: string | null
  profileSyncWarning?: string | null
  onLogout?: () => void
  whatsappStatus?: WhatsAppLinkStatus
  whatsappRefreshing?: boolean
  onRefreshWhatsapp?: () => void
  googleConnected?: boolean
  onRevokeGoogle?: () => void
  wsConnected?: boolean
  theme: 'light' | 'dark'
  onToggleTheme: () => void
  onOpenSettings?: () => void
  usageSummary?: UsageSummary | null
  usageLoading?: boolean
}

const LANGUAGES = [
  { code: 'es', label: 'ES' },
  { code: 'en', label: 'EN' },
  { code: 'pt', label: 'PT' },
] as const

function whatsappDotColor(status: WhatsAppLinkStatus): string {
  switch (status) {
    case 'linked':
      return 'var(--dash-success)'
    case 'connecting':
      return 'var(--dash-warning)'
    case 'disconnected':
      return 'var(--dash-error)'
    case 'pending_verification':
      return 'var(--dash-warning)'
    default:
      return 'var(--dash-text-secondary)'
  }
}

function whatsappLabel(status: WhatsAppLinkStatus, t: (key: string) => string): string {
  switch (status) {
    case 'linked':
      return t('dashboard.whatsapp_linked')
    case 'connecting':
      return t('dashboard.whatsapp_reconnecting')
    case 'disconnected':
      return t('dashboard.whatsapp_rescan_qr')
    case 'pending_verification':
      return t('dashboard.whatsapp_pending')
    default:
      return 'WhatsApp'
  }
}

function StatusPill({
  dotColor,
  label,
  title,
  children,
}: {
  dotColor: string
  label: string
  title?: string
  children?: React.ReactNode
}) {
  return (
    <span className="main-dashboard__status-pill" title={title ?? label}>
      <span className="main-dashboard__status-dot" style={{ backgroundColor: dotColor }} />
      <span>{label}</span>
      {children}
    </span>
  )
}

export function WorkspaceHeader({
  selectedAgent,
  onAgentChange,
  userDisplayName,
  channelLabel,
  profileSyncWarning,
  onLogout,
  whatsappStatus = 'disconnected',
  whatsappRefreshing = false,
  onRefreshWhatsapp,
  googleConnected = false,
  onRevokeGoogle,
  wsConnected = false,
  theme,
  onToggleTheme,
  onOpenSettings,
  usageSummary = null,
  usageLoading = false,
}: WorkspaceHeaderProps) {
  const { t, i18n } = useTranslation()
  const [logoutModalOpen, setLogoutModalOpen] = useState(false)
  const online = useOnlineStatus()

  const handleLanguageChange = useCallback(
    (code: string) => {
      i18n.changeLanguage(code)
      localStorage.setItem('dot-lang', code)
    },
    [i18n],
  )

  const currentLang = i18n.language?.startsWith('pt')
    ? 'pt'
    : i18n.language?.startsWith('en')
      ? 'en'
      : 'es'
  const isDevMode = import.meta.env.MODE !== 'production'
  const wsStatusLabel = wsConnected
    ? t('dashboard.ws_connected')
    : isDevMode
      ? t('dashboard.ws_dev_mode')
      : t('dashboard.ws_disconnected')
  const wsStatusTitle = wsConnected
    ? t('dashboard.ws_connected_title')
    : isDevMode
      ? t('dashboard.ws_dev_mode_title')
      : t('dashboard.ws_disconnected_title')
  const wsDotColor = wsConnected
    ? 'var(--dash-success)'
    : isDevMode
      ? 'var(--dash-warning)'
      : 'var(--dash-error)'

  return (
    <header className="main-dashboard__header">
      {profileSyncWarning ? (
        <div className="main-dashboard__sync-alert" role="alert">
          {t('dashboard.profile_sync_error', { error: profileSyncWarning })}
        </div>
      ) : null}

      <div className="main-dashboard__header-bar">
        <div className="main-dashboard__header-left">
          <UsageMeter summary={usageSummary} loading={usageLoading} />
          <p className="main-dashboard__brand">{userDisplayName}</p>
          <div className="main-dashboard__agents" role="list" aria-label={t('dashboard.agent_label')}>
            {WORKSPACE_AGENTS.map((a) => (
              <button
                key={a.id}
                type="button"
                role="listitem"
                className={`main-dashboard__agent-chip ${selectedAgent === a.id ? 'main-dashboard__agent-chip--active' : ''}`}
                onClick={() => onAgentChange(a.id)}
              >
                {a.label}
              </button>
            ))}
          </div>
        </div>

        <div className="main-dashboard__header-right">
          <div className="main-dashboard__status-group">
            <StatusPill
              dotColor={whatsappDotColor(whatsappStatus)}
              label={whatsappLabel(whatsappStatus, t)}
            >
              {whatsappStatus === 'pending_verification' && onRefreshWhatsapp ? (
                <button
                  type="button"
                  className="main-dashboard__status-pill-refresh"
                  onClick={onRefreshWhatsapp}
                  disabled={whatsappRefreshing}
                >
                  {whatsappRefreshing
                    ? `${t('dashboard.revalidate_whatsapp')}…`
                    : t('dashboard.revalidate_whatsapp')}
                </button>
              ) : null}
            </StatusPill>
            <StatusPill
              dotColor={googleConnected ? 'var(--dash-success)' : 'var(--dash-text-secondary)'}
              label={googleConnected ? t('dashboard.google_connected') : t('dashboard.google_disconnected')}
            >
              {googleConnected && onRevokeGoogle ? (
                <button
                  type="button"
                  className="main-dashboard__google-revoke-btn"
                  onClick={() => {
                    if (
                      window.confirm(
                        '¿Desconectar acceso a Google? Se perderán las integraciones de Gmail y Calendar.',
                      )
                    ) {
                      onRevokeGoogle()
                    }
                  }}
                  title="Desconectar Google"
                >
                  {t('dashboard.disconnect')}
                </button>
              ) : null}
            </StatusPill>
            <StatusPill
              dotColor={wsDotColor}
              label={wsStatusLabel}
              title={wsStatusTitle}
            />
            {!online ? (
              <span className="main-dashboard__status-pill main-dashboard__status-pill--offline">
                <span
                  className="main-dashboard__status-dot"
                  style={{ backgroundColor: 'var(--dash-error)' }}
                />
                {t('dashboard.offline')}
              </span>
            ) : null}
            {channelLabel !== null ? (
              <span className="main-dashboard__status-pill" title={channelLabel}>
                {t('dashboard.channel', { channel: channelLabel })}
              </span>
            ) : null}
          </div>

          <div className="main-dashboard__header-actions">
            <div className="main-dashboard__lang-selector">
              {LANGUAGES.map((lang) => (
                <button
                  key={lang.code}
                  type="button"
                  className={`main-dashboard__lang-btn ${currentLang === lang.code ? 'main-dashboard__lang-btn--active' : ''}`}
                  onClick={() => handleLanguageChange(lang.code)}
                  aria-label={lang.label}
                  title={lang.label}
                >
                  {lang.label}
                </button>
              ))}
            </div>
            <button
              type="button"
              className="main-dashboard__icon-btn"
              onClick={onToggleTheme}
              aria-label={theme === 'dark' ? t('dashboard.theme_light') : t('dashboard.theme_dark')}
              title={theme === 'dark' ? t('dashboard.theme_light') : t('dashboard.theme_dark')}
            >
              {theme === 'dark'
                ? (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                    <circle cx="12" cy="12" r="5" />
                    <g stroke="currentColor" strokeWidth="2" strokeLinecap="round" fill="none">
                      <line x1="12" y1="1" x2="12" y2="3" />
                      <line x1="12" y1="21" x2="12" y2="23" />
                      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
                      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
                      <line x1="1" y1="12" x2="3" y2="12" />
                      <line x1="21" y1="12" x2="23" y2="12" />
                      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
                      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
                    </g>
                  </svg>
                )
                : (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                  </svg>
                )}
            </button>
            {onOpenSettings ? (
              <button
                type="button"
                className="main-dashboard__icon-btn"
                onClick={onOpenSettings}
                aria-label="Configuración"
                title="Configuración"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <circle cx="12" cy="12" r="3" />
                  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
                </svg>
              </button>
            ) : null}
            <div className="main-dashboard__legal-links">
              <button
                type="button"
                className="main-dashboard__legal-link"
                onClick={() => {
                  void window.desktop?.openUrl(
                    'https://raw.githubusercontent.com/nordik-ia/dot/main/docs/legal/TERMS-OF-SERVICE.md',
                  )
                }}
                title={t('dashboard.legal_terms')}
              >
                {t('dashboard.legal_terms')}
              </button>
              <button
                type="button"
                className="main-dashboard__legal-link"
                onClick={() => {
                  void window.desktop?.openUrl(
                    'https://raw.githubusercontent.com/nordik-ia/dot/main/docs/legal/PRIVACY-POLICY.md',
                  )
                }}
                title={t('dashboard.legal_privacy')}
              >
                {t('dashboard.legal_privacy')}
              </button>
            </div>
            {onLogout ? (
              <button
                type="button"
                className="main-dashboard__logout"
                onClick={() => setLogoutModalOpen(true)}
              >
                {t('dashboard.logout_button')}
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <LogoutConfirmModal
        open={logoutModalOpen}
        onCancel={() => setLogoutModalOpen(false)}
        onConfirm={() => {
          setLogoutModalOpen(false)
          onLogout?.()
        }}
      />
    </header>
  )
}
