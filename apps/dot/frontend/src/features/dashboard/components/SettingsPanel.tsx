import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { motion, AnimatePresence } from 'framer-motion'

import { useTheme } from '@/shared/theme-context'
import { PRODUCT_NAME, PRODUCT_VERSION } from '@/shared/constants/brand'
import { ContactsSettings } from '@/features/dashboard/components/ContactsSettings'
import { CronTab } from '@/features/dashboard/components/CronTab'
import { MorningBriefingSettings } from '@/features/dashboard/components/MorningBriefingSettings'
import { ProactiveTriggersSettings } from '@/features/dashboard/components/ProactiveTriggersSettings'
import { BrowserWebSettings } from '@/features/dashboard/components/BrowserWebSettings'
import { MemoryRecallSettings } from '@/features/dashboard/components/MemoryRecallSettings'
import { exportUserData } from '@/features/dashboard/lib/user-data-export'
import { describeVoiceCapability } from '@/lib/api/voice'
import type { GetAccessToken } from '@/lib/api/client'

export type SettingsPanelProps = {
  open: boolean
  onClose: () => void
  userDisplayName: string
  channelLabel: string | null
  onLogout?: () => void
  getAccessToken?: GetAccessToken
  dotSpeaksEnabled?: boolean
  onDotSpeaksChange?: (enabled: boolean) => void
  voiceSttAvailable?: boolean
  voiceTtsAvailable?: boolean
  voiceStatusLoaded?: boolean
}

type SettingsSection = 'profile' | 'memory' | 'contacts' | 'notifications' | 'appearance' | 'privacy' | 'cron' | 'about'

const SECTION_LABELS: Record<SettingsSection, string> = {
  profile: 'Perfil',
  memory: 'Memoria',
  contacts: 'Contactos',
  notifications: 'Notificaciones',
  appearance: 'Apariencia',
  privacy: 'Privacidad',
  cron: 'Tareas',
  about: 'Acerca de',
}

function getElectronVersions(): { electron: string; chrome: string; node: string } | null {
  try {
    const nav = navigator as Navigator & { userAgentData?: { brands?: Array<{ brand: string; version: string }> } }
    const ua = nav.userAgent || ''
    const chromeMatch = ua.match(/Chrome\/(\d+)/)
    const electronMatch = ua.match(/Electron\/(\d+\.\d+\.\d+)/)
    const nodeMatch = ua.match(/Node\.js\/(\d+\.\d+\.\d+)/)

    return {
      electron: electronMatch?.[1] || 'N/A',
      chrome: chromeMatch?.[1] || 'N/A',
      node: nodeMatch?.[1] || 'N/A',
    }
  } catch {
    return null
  }
}

export function SettingsPanel({
  open,
  onClose,
  userDisplayName,
  channelLabel,
  onLogout,
  getAccessToken,
  dotSpeaksEnabled = false,
  onDotSpeaksChange,
  voiceSttAvailable = false,
  voiceTtsAvailable = false,
  voiceStatusLoaded = false,
}: SettingsPanelProps) {
  const { t } = useTranslation()
  const sttStatus = voiceStatusLoaded
    ? describeVoiceCapability(voiceSttAvailable ? 'ready' : 'needs_api_key', 'stt', t)
    : { ready: false, label: '…', help: t('loading.connecting') }
  const ttsStatus = voiceStatusLoaded
    ? describeVoiceCapability(voiceTtsAvailable ? 'ready' : 'needs_api_key', 'tts', t)
    : { ready: false, label: '…', help: t('loading.connecting') }
  const { theme, toggleTheme } = useTheme()
  const [activeSection, setActiveSection] = useState<SettingsSection>('profile')
  const [exporting, setExporting] = useState(false)
  const [exportMessage, setExportMessage] = useState<string | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)

  const versions = getElectronVersions()
  const buildDate = document.querySelector('meta[name="build-date"]')?.getAttribute('content') || 'N/A'

  const handleExportData = useCallback(async () => {
    if (!getAccessToken || exporting) return

    setExporting(true)
    setExportMessage(null)
    setExportError(null)

    try {
      const { savedPath, partial } = await exportUserData(getAccessToken, {
        theme,
        dot_speaks_enabled: dotSpeaksEnabled,
        channel_label: channelLabel,
        display_name: userDisplayName,
      })

      if (partial) {
        setExportMessage(
          `Exportación parcial guardada en ${savedPath}. Algunos datos no estuvieron disponibles; revisa el archivo JSON.`,
        )
      } else {
        setExportMessage(`Tus datos se guardaron correctamente en ${savedPath}.`)
      }
    } catch {
      setExportError('No se pudo descargar tus datos. Revisa tu conexión e intenta de nuevo.')
    } finally {
      setExporting(false)
    }
  }, [
    channelLabel,
    dotSpeaksEnabled,
    exporting,
    getAccessToken,
    theme,
    userDisplayName,
  ])

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="settings-overlay"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          <motion.aside
            className="settings-panel"
            role="dialog"
            aria-modal="true"
            aria-label="Configuración"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', stiffness: 420, damping: 38 }}
          >
            <div className="settings-panel__header">
              <h2 className="settings-panel__title">Configuración</h2>
              <button
                type="button"
                className="settings-panel__close"
                onClick={onClose}
                aria-label="Cerrar configuración"
              >
                ×
              </button>
            </div>

            <div className="settings-panel__body">
              {/* Sidebar de navegación */}
              <nav className="settings-panel__nav" role="tablist" aria-label="Secciones de configuración">
                {(Object.keys(SECTION_LABELS) as SettingsSection[]).map((section) => (
                  <button
                    key={section}
                    type="button"
                    role="tab"
                    aria-selected={activeSection === section}
                    className={`settings-panel__nav-item${activeSection === section ? ' settings-panel__nav-item--active' : ''}`}
                    onClick={() => setActiveSection(section)}
                  >
                    {SECTION_LABELS[section]}
                  </button>
                ))}
              </nav>

              {/* Contenido de la sección */}
              <div className="settings-panel__content" role="tabpanel" aria-label={SECTION_LABELS[activeSection]}>
                {activeSection === 'profile' && (
                  <div className="settings-section">
                    <h3 className="settings-section__title">Perfil</h3>
                    <div className="settings-section__card">
                      <div className="settings-field">
                        <label className="settings-field__label">Nombre</label>
                        <span className="settings-field__value">{userDisplayName || '—'}</span>
                      </div>
                      <div className="settings-field">
                        <label className="settings-field__label">Canal</label>
                        <span className="settings-field__value">{channelLabel || 'PC'}</span>
                      </div>
                      <div className="settings-field settings-field--group">
                        <span className="settings-field__label">{t('voice.settings_voice_title')}</span>
                        <div className="settings-field settings-field--nested">
                          <div className="settings-field__row">
                            <label className="settings-field__label">{t('voice.settings_stt_title')}</label>
                            <span
                              className={`settings-field__badge${sttStatus.ready ? ' settings-field__badge--ok' : ' settings-field__badge--warn'}`}
                            >
                              {sttStatus.label}
                            </span>
                          </div>
                          <span className="settings-field__help">{sttStatus.help}</span>
                        </div>
                      </div>
                      {onDotSpeaksChange ? (
                        <div className="settings-field settings-field--toggle settings-field--nested">
                          <div>
                            <div className="settings-field__row">
                              <label className="settings-field__label">{t('voice.settings_speak_title')}</label>
                              <span
                                className={`settings-field__badge${ttsStatus.ready ? ' settings-field__badge--ok' : ' settings-field__badge--warn'}`}
                              >
                                {ttsStatus.label}
                              </span>
                            </div>
                            <span className="settings-field__help">{ttsStatus.help}</span>
                          </div>
                          <button
                            type="button"
                            className={`settings-toggle${dotSpeaksEnabled ? ' settings-toggle--active' : ''}`}
                            onClick={() => onDotSpeaksChange(!dotSpeaksEnabled)}
                            aria-label={dotSpeaksEnabled ? t('voice.speak_disable') : t('voice.speak_enable')}
                            role="switch"
                            aria-checked={dotSpeaksEnabled}
                            disabled={!voiceStatusLoaded || !voiceTtsAvailable}
                          >
                            <span className="settings-toggle__thumb" />
                          </button>
                        </div>
                      ) : null}
                    </div>
                    {onLogout ? (
                      <button
                        type="button"
                        className="settings-section__danger-btn"
                        onClick={onLogout}
                      >
                        Cerrar sesión
                      </button>
                    ) : null}
                  </div>
                )}

                {activeSection === 'memory' && (
                  <div className="settings-section">
                    <h3 className="settings-section__title">Lo que recuerdo de ti</h3>
                    {getAccessToken ? (
                      <MemoryRecallSettings getAccessToken={getAccessToken} />
                    ) : (
                      <div className="settings-section__card">
                        <p className="settings-section__desc">
                          No se pudo cargar tu memoria. Cierra y vuelve a abrir la configuración.
                        </p>
                      </div>
                    )}
                  </div>
                )}

                {activeSection === 'contacts' && (
                  <div className="settings-section">
                    <h3 className="settings-section__title">Agenda de contactos</h3>
                    {getAccessToken ? (
                      <ContactsSettings getAccessToken={getAccessToken} />
                    ) : (
                      <div className="settings-section__card">
                        <p className="settings-section__desc">
                          Inicia sesión para gestionar tu agenda de contactos.
                        </p>
                      </div>
                    )}
                  </div>
                )}

                {activeSection === 'notifications' && (
                  <div className="settings-section">
                    <h3 className="settings-section__title">Notificaciones</h3>
                    <p className="settings-section__desc">
                      Elige qué avisos recibes y cuándo DOT actúa por ti con mandatos
                      «avísame cuando…».
                    </p>
                    {getAccessToken ? (
                      <>
                        <h4 className="settings-section__subtitle">Briefing matutino</h4>
                        <MorningBriefingSettings getAccessToken={getAccessToken} />
                        <h4 className="settings-section__subtitle">Avísame cuando…</h4>
                        <ProactiveTriggersSettings getAccessToken={getAccessToken} />
                      </>
                    ) : null}
                    <div className="settings-section__card">
                      <p className="settings-section__desc">
                        Las notificaciones del sistema operativo se gestionan desde Windows.
                        DOT envía avisos para recordatorios, automatizaciones y tu briefing matutino.
                      </p>
                    </div>
                  </div>
                )}

                {activeSection === 'appearance' && (
                  <div className="settings-section">
                    <h3 className="settings-section__title">Apariencia</h3>
                    <div className="settings-section__card">
                      <div className="settings-field settings-field--toggle">
                        <div>
                          <label className="settings-field__label">Tema oscuro</label>
                          <span className="settings-field__help">
                            {theme === 'dark' ? 'Activado' : 'Desactivado'} — cambia entre modo claro y oscuro
                          </span>
                        </div>
                        <button
                          type="button"
                          className={`settings-toggle${theme === 'dark' ? ' settings-toggle--active' : ''}`}
                          onClick={toggleTheme}
                          aria-label={theme === 'dark' ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro'}
                          role="switch"
                          aria-checked={theme === 'dark'}
                        >
                          <span className="settings-toggle__thumb" />
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {activeSection === 'privacy' && (
                  <div className="settings-section">
                    <h3 className="settings-section__title">Privacidad</h3>
                    {getAccessToken ? <BrowserWebSettings getAccessToken={getAccessToken} /> : null}
                    <div className="settings-section__card">
                      <p className="settings-section__desc">
                        Tus conversaciones están cifradas en reposo. DOT no comparte tus datos con terceros.
                      </p>
                      <p className="settings-section__desc">
                        Puedes descargar un archivo JSON con tu perfil, hechos de memoria y preferencias
                        básicas (briefing, avisos proactivos y navegación web).
                      </p>
                      <button
                        type="button"
                        className="settings-section__secondary-btn"
                        onClick={() => void handleExportData()}
                        disabled={!getAccessToken || exporting}
                      >
                        {exporting ? 'Preparando exportación…' : 'Descargar mis datos'}
                      </button>
                      {exportMessage ? (
                        <p className="settings-export__success" role="status">
                          {exportMessage}
                        </p>
                      ) : null}
                      {exportError ? (
                        <p className="settings-export__error" role="alert">
                          {exportError}
                        </p>
                      ) : null}
                    </div>
                  </div>
                )}

                {activeSection === 'cron' && getAccessToken && (
                  <CronTab getAccessToken={getAccessToken} />
                )}

                {activeSection === 'cron' && !getAccessToken && (
                  <div className="settings-section">
                    <h3 className="settings-section__title">Tareas programadas</h3>
                    <div className="settings-section__card">
                      <p className="settings-section__desc">
                        No se pudo cargar la configuración de tareas programadas.
                        Cierra y vuelve a abrir la configuración.
                      </p>
                    </div>
                  </div>
                )}

                {activeSection === 'about' && (
                  <div className="settings-section">
                    <h3 className="settings-section__title">Acerca de {PRODUCT_NAME}</h3>
                    <div className="settings-section__card">
                      <div className="settings-field">
                        <label className="settings-field__label">Versión</label>
                        <span className="settings-field__value">{PRODUCT_VERSION}</span>
                      </div>
                      <div className="settings-field">
                        <label className="settings-field__label">Build</label>
                        <span className="settings-field__value">{buildDate}</span>
                      </div>
                      {versions ? (
                        <>
                          <div className="settings-field">
                            <label className="settings-field__label">Electron</label>
                            <span className="settings-field__value">v{versions.electron}</span>
                          </div>
                          <div className="settings-field">
                            <label className="settings-field__label">Chromium</label>
                            <span className="settings-field__value">v{versions.chrome}</span>
                          </div>
                          <div className="settings-field">
                            <label className="settings-field__label">Node.js</label>
                            <span className="settings-field__value">v{versions.node}</span>
                          </div>
                        </>
                      ) : (
                        <p className="settings-section__desc">
                          Ejecutando en navegador web. Instala la app de escritorio para ver versiones de Electron.
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </motion.aside>
        </motion.div>
      ) : null}
    </AnimatePresence>
  )
}
