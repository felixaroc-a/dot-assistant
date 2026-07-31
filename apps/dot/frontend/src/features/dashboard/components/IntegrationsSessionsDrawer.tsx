import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { tryExtractRawWhatsAppQr } from '@/features/onboarding/lib/openclawQrPayload'
import { extractAsciiQrBlock } from '@/features/onboarding/lib/openclawLogQr'
import { getDesktopWhatsAppBridge } from '@/features/onboarding/lib/whatsappLinkSignals'
import { WHATSAPP_LINK_UI } from '@/features/onboarding/lib/whatsappLinkUi'
import { ansiQrToDataUrl } from '@/features/onboarding/lib/ansiQrToDataUrl'
import {
  getWhatsAppChannelStatus,
  sendWhatsAppChannelEvent,
  toLinkStatus,
  type WhatsAppLinkStatus,
} from '@/lib/api/whatsapp'
import {
  requestGoogleOAuthStart,
  resolveGoogleOAuthStatus,
  revokeGoogleOAuth,
} from '@/lib/api/google-oauth'
import { getOrCreateLocalGoogleOAuthSubject } from '@/lib/api/oauth-subject-storage'
import { translateError, sanitizeWhatsAppUserError } from '@/lib/error-messages'
import type { GetAccessToken } from '@/lib/api/client'

import './integrations-sessions.css'

export type IntegrationsFocus = 'whatsapp' | 'google' | null

export type IntegrationsSessionsDrawerProps = {
  open: boolean
  focus?: IntegrationsFocus
  onClose: () => void
  onOpenSettings?: () => void
  whatsappStatus: WhatsAppLinkStatus
  whatsappPhone?: string | null
  googleConnected: boolean
  getAccessToken: GetAccessToken
  onWhatsAppChanged: () => void | Promise<void>
  onGoogleChanged: () => void | Promise<void>
}

function statusLabel(status: WhatsAppLinkStatus): string {
  switch (status) {
    case 'linked':
      return 'Vinculado'
    case 'connecting':
      return 'Reconectando…'
    case 'pending_verification':
      return 'Pendiente de verificación'
    default:
      return 'Vuelve a escanear el código'
  }
}

export function IntegrationsSessionsDrawer({
  open,
  focus = null,
  onClose,
  onOpenSettings,
  whatsappStatus,
  whatsappPhone = null,
  googleConnected,
  getAccessToken,
  onWhatsAppChanged,
  onGoogleChanged,
}: IntegrationsSessionsDrawerProps) {
  const reduceMotion = useReducedMotion()
  const [busyWa, setBusyWa] = useState(false)
  const [busyGoogle, setBusyGoogle] = useState(false)
  const [privilegedPerm, setPrivilegedPerm] = useState<
    'allowed' | 'denied' | 'requires_confirmation' | 'unknown'
  >('unknown')
  const [busyPrivileged, setBusyPrivileged] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [linkingWa, setLinkingWa] = useState(false)
  const [log, setLog] = useState('')
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null)
  const stopLoginRef = useRef<(() => void) | null>(null)
  const waSectionRef = useRef<HTMLElement | null>(null)
  const googleSectionRef = useRef<HTMLElement | null>(null)

  const rawQrPayload = useMemo(() => tryExtractRawWhatsAppQr(log), [log])
  const rawQrLines = useMemo(() => extractAsciiQrBlock(log), [log])
  const ansiDataUrl = useMemo(
    () => (qrDataUrl ? null : rawQrLines ? ansiQrToDataUrl(rawQrLines) : null),
    [qrDataUrl, rawQrLines],
  )
  const qrSrc = qrDataUrl || ansiDataUrl

  useEffect(() => {
    let cancelled = false
    if (!rawQrPayload) {
      setQrDataUrl(null)
      return
    }
    const render = window.desktop?.renderWhatsappQrDataUrl
    if (!render) return
    void render(rawQrPayload).then((url) => {
      if (!cancelled) setQrDataUrl(url)
    })
    return () => {
      cancelled = true
    }
  }, [rawQrPayload])

  useEffect(() => {
    if (!open || !focus) return
    const target = focus === 'whatsapp' ? waSectionRef.current : googleSectionRef.current
    target?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [open, focus])

  const cleanupLogin = useCallback(() => {
    stopLoginRef.current?.()
    stopLoginRef.current = null
    setLinkingWa(false)
    setLog('')
    setQrDataUrl(null)
    void getDesktopWhatsAppBridge()?.stop?.()
  }, [])

  useEffect(() => {
    if (!open) {
      cleanupLogin()
      setError(null)
      setInfo(null)
    }
  }, [open, cleanupLogin])

  useEffect(() => () => cleanupLogin(), [cleanupLogin])

  const refreshPrivilegedPerm = useCallback(async () => {
    try {
      const status = await window.desktop?.localTools?.getPermissionStatus?.('privileged')
      if (status === 'allowed' || status === 'denied' || status === 'requires_confirmation') {
        setPrivilegedPerm(status)
      } else {
        setPrivilegedPerm('requires_confirmation')
      }
    } catch {
      setPrivilegedPerm('unknown')
    }
  }, [])

  useEffect(() => {
    if (!open) return
    void refreshPrivilegedPerm()
  }, [open, refreshPrivilegedPerm])

  const setPrivilegedPermission = useCallback(
    async (decision: 'always' | 'denied') => {
      setBusyPrivileged(true)
      setError(null)
      try {
        const res = await window.desktop?.localTools?.setPermission?.('privileged', decision)
        if (!res?.ok) {
          setError('No pude guardar el Modo privilegiado.')
          return
        }
        if (decision === 'always') {
          setInfo(
            'Modo privilegiado ON. DOT puede leer y escribir archivos fuera de Documentos, Escritorio y Descargas. ' +
              'Para páginas web usa Configuración → Privacidad → «DOT puede usar webs».',
          )
        } else {
          setInfo('Modo privilegiado OFF. Vuelves al acceso limitado a carpetas habituales.')
        }
        await refreshPrivilegedPerm()
      } catch {
        setError('Error al cambiar Modo privilegiado.')
      } finally {
        setBusyPrivileged(false)
      }
    },
    [refreshPrivilegedPerm],
  )

  const startWhatsAppLink = useCallback(async (opts?: { clearSession?: boolean }) => {
    setError(null)
    setInfo(null)
    const waBridge = getDesktopWhatsAppBridge()
    if (!waBridge?.startWhatsAppLogin) {
      setError('Vinculación WhatsApp solo disponible en la app de escritorio DOT.')
      return
    }

    cleanupLogin()
    setBusyWa(true)
    setLinkingWa(true)
    setLog('')

    const unsubs: Array<() => void> = []
    const finish = () => {
      for (const u of unsubs) u()
      stopLoginRef.current = null
    }
    stopLoginRef.current = finish

    if (waBridge.onData) {
      unsubs.push(
        waBridge.onData((payload) => {
          const chunk = String(payload?.text || '')
          if (chunk) setLog((prev) => (prev + chunk).slice(-120_000))
        }),
      )
    }
    if (waBridge.onLinked) {
      unsubs.push(
        waBridge.onLinked((payload) => {
          if (!payload?.linked) return
          void (async () => {
            try {
              await sendWhatsAppChannelEvent(
                {
                  event: 'linked',
                  phone_number: payload.phone_number || undefined,
                  source: 'dashboard-integrations',
                },
                getAccessToken,
              )
            } catch {
              // el poll de estado lo recuperará
            }
            setInfo(
              payload.phone_number
                ? `WhatsApp vinculado (${payload.phone_number}).`
                : 'WhatsApp vinculado.',
            )
            setLinkingWa(false)
            finish()
            await onWhatsAppChanged()
          })()
        }),
      )
    }

    try {
      const clearSession = opts?.clearSession !== false
      const started = await waBridge.startWhatsAppLogin({ clearSession })
      if (!started.ok) {
        setError(sanitizeWhatsAppUserError(started.error || 'No se pudo iniciar la vinculación de WhatsApp.'))
        setLinkingWa(false)
        finish()
        return
      }
      setInfo(clearSession ? WHATSAPP_LINK_UI.scanHint : WHATSAPP_LINK_UI.reconnecting)
      // Poll de respaldo
      const startedAt = Date.now()
      const poll = window.setInterval(() => {
        void (async () => {
          try {
            const st = await getWhatsAppChannelStatus(getAccessToken)
            if (toLinkStatus(st) === 'linked') {
              window.clearInterval(poll)
              setInfo(
                st.phone_number
                  ? `WhatsApp vinculado (${st.phone_number}).`
                  : 'WhatsApp vinculado.',
              )
              setLinkingWa(false)
              finish()
              await onWhatsAppChanged()
            }
          } catch {
            // ignore
          }
          if (Date.now() - startedAt > 180_000) {
            window.clearInterval(poll)
          }
        })()
      }, 3000)
      unsubs.push(() => window.clearInterval(poll))
    } catch (err) {
      setError(translateError(err, 'No pude conectar WhatsApp. Escanea el código de nuevo.'))
      setLinkingWa(false)
      finish()
    } finally {
      setBusyWa(false)
    }
  }, [cleanupLogin, getAccessToken, onWhatsAppChanged])

  // Al abrir con foco WhatsApp: reconexión silenciosa primero; QR solo si la sesión murió.
  useEffect(() => {
    if (!open || focus !== 'whatsapp') return
    if (whatsappStatus === 'linked' || linkingWa || busyWa) return

    void (async () => {
      setInfo(WHATSAPP_LINK_UI.reconnecting)
      const restore = window.desktop?.whatsapp?.restoreSession
      if (restore) {
        try {
          const result = await restore()
          if (result?.ok && !result.needs_qr) {
            setInfo(
              result.phone_number
                ? `WhatsApp reconectado (${result.phone_number}).`
                : WHATSAPP_LINK_UI.connected,
            )
            await onWhatsAppChanged()
            return
          }
          if (result?.needs_qr) {
            setInfo(WHATSAPP_LINK_UI.rescanQr)
            await startWhatsAppLink({ clearSession: true })
            return
          }
        } catch {
          // continuar con heurística de estado
        }
      }

      if (whatsappStatus === 'connecting') {
        setInfo(WHATSAPP_LINK_UI.reconnecting)
        return
      }

      if (whatsappStatus === 'disconnected') {
        setInfo(WHATSAPP_LINK_UI.rescanQr)
        await startWhatsAppLink({ clearSession: true })
      }
    })()
    // solo al abrir con ese foco
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, focus])

  const unlinkWhatsApp = useCallback(async () => {
    if (busyWa) return
    const ok = window.confirm(
      '¿Desvincular WhatsApp y mostrar un QR nuevo? Se cerrará la sesión en este PC.',
    )
    if (!ok) return
    setBusyWa(true)
    setError(null)
    setInfo(null)
    cleanupLogin()
    try {
      const desktop = window.desktop
      const logoutFn =
        desktop?.whatsapp?.logout ||
        desktop?.whatsappLogout ||
        getDesktopWhatsAppBridge()?.logoutWhatsApp

      if (typeof logoutFn === 'function') {
        const result = await logoutFn()
        if (result && result.ok === false) {
          setError(sanitizeWhatsAppUserError(result.error || 'No se pudo desvincular WhatsApp.'))
          return
        }
      } else {
        // Preload antiguo: detener daemon + login limpia sesión en main (clearSavedSession).
        await desktop?.whatsapp?.stopDaemon?.()
        await getDesktopWhatsAppBridge()?.stop?.()
        if (!getDesktopWhatsAppBridge()?.startWhatsAppLogin) {
          setError(
            'Cierra DOT por completo (X) y vuelve a abrir la aplicación. ' +
              'Luego intenta desvincular WhatsApp de nuevo.',
          )
          return
        }
      }

      try {
        await sendWhatsAppChannelEvent(
          {
            event: 'disconnected',
            error: 'user_logout',
            source: 'dashboard-integrations',
          },
          getAccessToken,
        )
      } catch {
        // ignore
      }

      setInfo('Sesión limpiada. Generando código QR…')
      await onWhatsAppChanged()
      setBusyWa(false)
      // Arranca QR de inmediato (main limpia credenciales al iniciar login)
      await startWhatsAppLink()
    } catch (err) {
      setError(translateError(err, 'No se pudo desvincular WhatsApp. Intenta de nuevo.'))
      setBusyWa(false)
    }
  }, [busyWa, cleanupLogin, getAccessToken, onWhatsAppChanged, startWhatsAppLink])

  const renewWhatsAppQr = useCallback(async () => {
    if (busyWa || linkingWa) return
    const ok = window.confirm(
      '¿Generar un QR nuevo? Se desvinculará la sesión actual de este PC.',
    )
    if (!ok) return
    await unlinkWhatsApp()
  }, [busyWa, linkingWa, unlinkWhatsApp])

  const connectGoogle = useCallback(async () => {
    if (busyGoogle) return
    setBusyGoogle(true)
    setError(null)
    setInfo(null)
    try {
      const token = await getAccessToken()
      const bearer = token?.trim() || null
      const devId = !bearer ? await getOrCreateLocalGoogleOAuthSubject() : undefined
      const start = await requestGoogleOAuthStart({
        bearerAccessToken: bearer,
        devUserIdWhenNoJwt: devId,
        integrations: ['gmail', 'google-calendar'],
      })
      if (!start.authorization_url) {
        setError('No se recibió URL de autorización de Google.')
        return
      }
      if (window.desktop?.openUrl) {
        await window.desktop.openUrl(start.authorization_url)
      } else {
        window.open(start.authorization_url, '_blank', 'noopener,noreferrer')
      }
      setInfo('Completa el permiso en el navegador. Esta ventana se actualizará sola.')

      const startedAt = Date.now()
      const poll = window.setInterval(() => {
        void (async () => {
          try {
            const st = await resolveGoogleOAuthStatus(getAccessToken)
            if (st.configured) {
              window.clearInterval(poll)
              setInfo('Google conectado (Gmail y Calendar). Ve a Configuración → Contactos para importar tu agenda.')
              await onGoogleChanged()
            }
          } catch {
            // ignore
          }
          if (Date.now() - startedAt > 180_000) {
            window.clearInterval(poll)
          }
        })()
      }, 2500)
    } catch (err) {
      setError(translateError(err, 'No se pudo conectar Google. Intenta de nuevo.'))
    } finally {
      setBusyGoogle(false)
    }
  }, [busyGoogle, getAccessToken, onGoogleChanged])

  const disconnectGoogle = useCallback(async () => {
    if (busyGoogle) return
    const ok = window.confirm(
      '¿Desconectar Google? Se perderán Gmail y Calendar hasta que vuelvas a vincular.',
    )
    if (!ok) return
    setBusyGoogle(true)
    setError(null)
    setInfo(null)
    try {
      const result = await revokeGoogleOAuth(getAccessToken)
      if (!result.ok) {
        setError(result.message || 'No se pudo desconectar Google.')
        return
      }
      setInfo('Google desconectado.')
      await onGoogleChanged()
    } catch (err) {
      setError(translateError(err, 'No se pudo desconectar Google. Intenta de nuevo.'))
    } finally {
      setBusyGoogle(false)
    }
  }, [busyGoogle, getAccessToken, onGoogleChanged])

  const waLinked = whatsappStatus === 'linked'

  return (
    <AnimatePresence>
      {open ? (
        <>
          <motion.button
            key="integrations-backdrop"
            type="button"
            className="main-dashboard__drawer-backdrop"
            aria-label="Cerrar sesiones"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduceMotion ? 0.08 : 0.2 }}
            onClick={onClose}
          />
          <motion.aside
            key="integrations-drawer"
            className="main-dashboard__drawer integrations-sessions"
            role="dialog"
            aria-modal="true"
            aria-labelledby="integrations-sessions-title"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{
              type: 'spring',
              stiffness: reduceMotion ? 400 : 320,
              damping: reduceMotion ? 40 : 32,
            }}
          >
            <div className="main-dashboard__drawer-head">
              <h2 id="integrations-sessions-title" className="main-dashboard__drawer-title">
                Sesiones
              </h2>
              <button type="button" className="main-dashboard__drawer-close" onClick={onClose}>
                ×
              </button>
            </div>

            <p className="integrations-sessions__intro">
              Vincula o desvincula WhatsApp y Google sin pasar por el onboarding. Útil si el
              cifrado de WhatsApp se trabó o cambiaste de cuenta.
            </p>

            {(error || info) && (
              <div
                className={`integrations-sessions__banner integrations-sessions__banner--${error ? 'error' : 'ok'}`}
                role="status"
              >
                {error || info}
              </div>
            )}

            <section
              ref={waSectionRef}
              className={`integrations-sessions__card integrations-sessions__card--${waLinked ? 'ok' : 'off'}`}
              aria-labelledby="integrations-wa-title"
            >
              <div className="integrations-sessions__card-head">
                <div>
                  <h3 id="integrations-wa-title" className="integrations-sessions__name">
                    WhatsApp
                  </h3>
                  <p className="integrations-sessions__meta">
                    {statusLabel(whatsappStatus)}
                    {whatsappPhone ? ` · ${whatsappPhone}` : ''}
                  </p>
                </div>
                <span
                  className={`status-preview__toggle status-preview__toggle--${waLinked ? 'ok' : 'off'}`}
                  aria-hidden
                >
                  <span className="status-preview__toggle-knob" />
                </span>
              </div>

              {waLinked ? (
                <p className="integrations-sessions__hint">{WHATSAPP_LINK_UI.groupSetupHint}</p>
              ) : null}

              <div className="integrations-sessions__actions">
                {waLinked ? (
                  <>
                    <button
                      type="button"
                      className="integrations-sessions__btn integrations-sessions__btn--primary"
                      disabled={busyWa || linkingWa}
                      onClick={() => void renewWhatsAppQr()}
                    >
                      {busyWa || linkingWa ? WHATSAPP_LINK_UI.generatingQr : 'QR nuevo'}
                    </button>
                    <button
                      type="button"
                      className="integrations-sessions__btn integrations-sessions__btn--danger"
                      disabled={busyWa || linkingWa}
                      onClick={() => void unlinkWhatsApp()}
                    >
                      {busyWa ? 'Desvinculando…' : 'Desvincular'}
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="integrations-sessions__btn integrations-sessions__btn--primary"
                    disabled={busyWa || linkingWa}
                    onClick={() => void startWhatsAppLink()}
                  >
                    {linkingWa ? WHATSAPP_LINK_UI.scanHint : 'Vincular con QR'}
                  </button>
                )}
                {linkingWa ? (
                  <button
                    type="button"
                    className="integrations-sessions__btn"
                    onClick={cleanupLogin}
                  >
                    Cancelar QR
                  </button>
                ) : null}
              </div>

              {linkingWa ? (
                <div className="integrations-sessions__qr-wrap">
                  {qrSrc ? (
                    <img
                      className="integrations-sessions__qr"
                      src={qrSrc}
                      alt="Código QR de WhatsApp"
                    />
                  ) : (
                    <p className="integrations-sessions__qr-wait">{WHATSAPP_LINK_UI.generatingQr}</p>
                  )}
                  <p className="integrations-sessions__hint">{WHATSAPP_LINK_UI.scanPath}</p>
                </div>
              ) : null}
            </section>

            <section
              ref={googleSectionRef}
              className={`integrations-sessions__card integrations-sessions__card--${googleConnected ? 'ok' : 'off'}`}
              aria-labelledby="integrations-google-title"
            >
              <div className="integrations-sessions__card-head">
                <div>
                  <h3 id="integrations-google-title" className="integrations-sessions__name">
                    Google
                  </h3>
                  <p className="integrations-sessions__meta">
                    {googleConnected ? 'Conectado · Gmail y Calendar' : 'Desconectado'}
                  </p>
                  {googleConnected && (
                    <p className="integrations-sessions__hint">
                      Para que DOT resuelva «escríbele a María», importa tus contactos en Configuración → Contactos.
                    </p>
                  )}
                </div>
                <span
                  className={`status-preview__toggle status-preview__toggle--${googleConnected ? 'ok' : 'off'}`}
                  aria-hidden
                >
                  <span className="status-preview__toggle-knob" />
                </span>
              </div>

              <div className="integrations-sessions__actions">
                {googleConnected ? (
                  <>
                    <button
                      type="button"
                      className="integrations-sessions__btn integrations-sessions__btn--danger"
                      disabled={busyGoogle}
                      onClick={() => void disconnectGoogle()}
                    >
                      {busyGoogle ? 'Desconectando…' : 'Desconectar'}
                    </button>
                    {onOpenSettings ? (
                      <button
                        type="button"
                        className="integrations-sessions__btn integrations-sessions__btn--ghost"
                        onClick={() => { onClose(); onOpenSettings() }}
                      >
                        Configuración
                      </button>
                    ) : null}
                  </>
                ) : (
                  <button
                    type="button"
                    className="integrations-sessions__btn integrations-sessions__btn--primary"
                    disabled={busyGoogle}
                    onClick={() => void connectGoogle()}
                  >
                    {busyGoogle ? 'Abriendo…' : 'Conectar Google'}
                  </button>
                )}
              </div>
            </section>

            <section
              className={`integrations-sessions__card integrations-sessions__card--${privilegedPerm === 'allowed' ? 'ok' : 'off'}`}
              aria-labelledby="integrations-privileged-title"
            >
              <div className="integrations-sessions__card-head">
                <div>
                  <h3 id="integrations-privileged-title" className="integrations-sessions__name">
                    Modo privilegiado
                  </h3>
                  <p className="integrations-sessions__meta">
                    {privilegedPerm === 'allowed'
                      ? 'ON · acceso ampliado a archivos en todo el PC (sin terminal).'
                      : 'OFF · solo Documentos, Escritorio y Descargas. Para webs: Configuración → Privacidad.'}
                  </p>
                </div>
                <span
                  className={`status-preview__toggle status-preview__toggle--${privilegedPerm === 'allowed' ? 'ok' : 'off'}`}
                  aria-hidden
                >
                  <span className="status-preview__toggle-knob" />
                </span>
              </div>
              <div className="integrations-sessions__actions">
                {privilegedPerm === 'allowed' ? (
                  <button
                    type="button"
                    className="integrations-sessions__btn integrations-sessions__btn--danger"
                    disabled={busyPrivileged}
                    onClick={() => void setPrivilegedPermission('denied')}
                  >
                    {busyPrivileged ? 'Guardando…' : 'Desactivar'}
                  </button>
                ) : (
                  <button
                    type="button"
                    className="integrations-sessions__btn integrations-sessions__btn--primary"
                    disabled={busyPrivileged}
                    onClick={() => void setPrivilegedPermission('always')}
                  >
                    {busyPrivileged ? 'Guardando…' : 'Activar Modo privilegiado'}
                  </button>
                )}
              </div>
            </section>
          </motion.aside>
        </>
      ) : null}
    </AnimatePresence>
  )
}
