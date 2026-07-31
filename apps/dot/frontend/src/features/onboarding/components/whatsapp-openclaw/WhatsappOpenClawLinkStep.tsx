import { motion, useReducedMotion } from 'framer-motion'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { LoadingScreen } from '@/components/LoadingScreen'
import { useAuth } from '@/features/auth'
import { extractAsciiQrBlock } from '@/features/onboarding/lib/openclawLogQr'
import { ansiQrToDataUrl } from '@/features/onboarding/lib/ansiQrToDataUrl'
import { tryExtractRawWhatsAppQr } from '@/features/onboarding/lib/openclawQrPayload'
import {
  hasDisconnectedSignal,
  hasLinkedSignal,
  getDesktopWhatsAppBridge,
  onWhatsAppLinked,
  sanitizeWhatsAppUserError,
} from '@/features/onboarding/lib/whatsappLinkSignals'
import { WHATSAPP_LINK_UI, resolveWhatsAppQrUiPhase } from '@/features/onboarding/lib/whatsappLinkUi'
import { isPendingVerificationStatus } from '@/features/onboarding/lib/whatsappLinkStatus'
import {
  getWhatsAppChannelStatus,
  requestWhatsAppReconnect,
  sendWhatsAppChannelEvent,
  toLinkStatus,
  type WhatsAppChannelEventName,
  type WhatsAppChannelStatus,
} from '@/lib/api/whatsapp'

import './whatsapp-openclaw.css'

/** @deprecated Legacy name — kept for external compatibility. Use {@link WhatsappLinkStepProps}. */
export type WhatsappOpenClawLinkStepProps = {
  onBack: () => void
  onSkip: () => void
  onContinue: () => void
}
export type WhatsappLinkStepProps = WhatsappOpenClawLinkStepProps

type RunState = 'idle' | 'running' | 'ended'

const MANUAL_CHECK_TIMEOUT_MS = 45_000
const MANUAL_CHECK_POLL_MS = 3_000
const STATUS_FETCH_TIMEOUT_MS = 8_000

function detectPhoneNumberInLog(rawLog: string): string | null {
  const patterns = [
    /(\d{8,15}(?::\d+)?)@s\.whatsapp\.net/i,
    /phone(?:_number)?\s*[:=]\s*"?(\+?\d{10,15})"?/i,
    /numero\s*[:=]\s*(\+?\d{10,15})/i,
    /(\+\d{10,15})\b/,
  ]
  for (const pattern of patterns) {
    const match = rawLog.match(pattern)
    if (!match?.[1]) continue
    const raw = match[1].split(':')[0].replace(/[^\d+]/g, '')
    const digits = raw.replace(/\D/g, '')
    if (!digits) continue
    if (raw.startsWith('+')) return `+${digits}`
    if (digits.startsWith('0') && digits.length === 11) return `+58${digits.slice(1)}`
    if (digits.startsWith('58') && digits.length >= 11) return `+${digits}`
    if (digits.length === 10 && digits.startsWith('4')) return `+58${digits}`
    if (digits.length >= 10 && digits.length <= 15) return `+${digits}`
  }
  return null
}

export function WhatsappLinkStep({ onBack, onSkip, onContinue }: WhatsappLinkStepProps) {
  const { getAccessToken } = useAuth()
  const reduceMotion = useReducedMotion()
  const easing = reduceMotion ? 'linear' : ([0.16, 1, 0.3, 1] as const)

  const [runState, setRunState] = useState<RunState>('idle')
  const [log, setLog] = useState('')
  const [exitInfo, setExitInfo] = useState<{ code: number | null; signal: string | null } | null>(null)
  const [startError, setStartError] = useState<string | null>(null)
  const [channelStatus, setChannelStatus] = useState<WhatsAppChannelStatus | null>(null)
  const [channelSyncError, setChannelSyncError] = useState<string | null>(null)
  const [awaitingScan, setAwaitingScan] = useState(true)
  const [scanCheckMessage, setScanCheckMessage] = useState<string | null>(null)
  const [pendingVerification, setPendingVerification] = useState(false)
  const [manualCheckInProgress, setManualCheckInProgress] = useState(false)
  const [localLinked, setLocalLinked] = useState(false)
  const lastEventRef = useRef<WhatsAppChannelEventName | null>(null)
  const unmountingRef = useRef(false)
  const restartingRef = useRef(false)
  const startInFlightRef = useRef(false)
  const hasRawQrRef = useRef(false)
  const hasSeenRawQrRef = useRef(false)
  const manualCheckActiveRef = useRef(false)
  const manualPollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const linkedRef = useRef(false)
  const progressHangRef = useRef(false)
  const autoAdvancedRef = useRef(false)

  const desktopWhatsApp = getDesktopWhatsAppBridge()
  const isDesktop = Boolean(desktopWhatsApp)

  // Baileys (happy path): payload DOT_WHATSAPP_QR → imagen. Fallback legacy: ASCII ANSI en logs.
  const rawQrPayload = useMemo(() => tryExtractRawWhatsAppQr(log), [log])
  const rawQrLines = useMemo(() => extractAsciiQrBlock(log), [log])
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null)
  const ansiDataUrl = useMemo(
    () => (qrDataUrl ? null : rawQrLines ? ansiQrToDataUrl(rawQrLines) : null),
    [qrDataUrl, rawQrLines],
  )
  const qrSrc = qrDataUrl || ansiDataUrl
  const hasRawQr = Boolean(qrSrc || rawQrLines || rawQrPayload)
  const [qrTimeout, setQrTimeout] = useState(false)
  const [_qrProgress, setQrProgress] = useState(0)
  const [progressMessage, setProgressMessage] = useState<string | null>(null)

  useEffect(() => {
    hasRawQrRef.current = hasRawQr
  }, [hasRawQr])

  useEffect(() => {
    if (hasRawQr) {
      hasSeenRawQrRef.current = true
    }
  }, [hasRawQr])

  useEffect(() => {
    let cancelled = false
    if (!rawQrPayload) {
      setQrDataUrl(null)
      return
    }
    const render = window.desktop?.renderWhatsappQrDataUrl
    if (!render) {
      setQrDataUrl(null)
      return
    }
    void render(rawQrPayload).then((url) => {
      if (!cancelled) setQrDataUrl(url)
    })
    return () => {
      cancelled = true
    }
  }, [rawQrPayload])

  useEffect(() => {
    if (hasRawQr) {
      setProgressMessage(null)
      progressHangRef.current = false
      return
    }
    if (runState !== 'running') {
      setProgressMessage(null)
      progressHangRef.current = false
      return
    }

    const interval = setInterval(() => {
      setQrProgress((prev) => {
        const hangTarget = 90
        if (prev >= hangTarget) {
          if (!progressHangRef.current) {
            progressHangRef.current = true
            setProgressMessage(WHATSAPP_LINK_UI.generatingSlow)
          }
          return prev
        }
        const increment = Math.max(0.6, (hangTarget - prev) * 0.045)
        const next = Math.min(hangTarget, prev + increment)
        if (next >= hangTarget && !progressHangRef.current) {
          progressHangRef.current = true
          setProgressMessage(
            'Buscando QR real. Mantén la app visible y vuelve a comprobar si ya lo escaneaste.',
          )
        }
        return next
      })
    }, 140)

    return () => {
      clearInterval(interval)
      progressHangRef.current = false
    }
  }, [runState, hasRawQr])

  const linkStatus = useMemo(
    () => (channelStatus ? toLinkStatus(channelStatus) : runState === 'running' ? 'connecting' : 'disconnected'),
    [channelStatus, runState],
  )

  useEffect(() => {
    const linked = channelStatus?.linked === true || channelStatus?.status === 'linked'
    linkedRef.current = linked
    if (linked) {
      setAwaitingScan(false)
      setScanCheckMessage(null)
    }
  }, [channelStatus])

  useEffect(() => {
    if (channelStatus?.linked) {
      setPendingVerification(false)
    }
  }, [channelStatus?.linked])

  const refreshChannelStatus = useCallback(async () => {
    try {
      const status = await Promise.race([
        getWhatsAppChannelStatus(getAccessToken),
        new Promise<null>((_, reject) => {
          setTimeout(() => reject(new Error('timeout')), STATUS_FETCH_TIMEOUT_MS)
        }),
      ])
      setChannelStatus(status)
      setChannelSyncError(null)
      if (status.linked) {
        setAwaitingScan(false)
      }
      return status
    } catch (err) {
      if (import.meta.env.DEV) {
        console.warn('[WhatsApp] refreshChannelStatus falló:', err)
      }
      setChannelSyncError(WHATSAPP_LINK_UI.serverSyncError)
      return null
    }
  }, [getAccessToken])

  const publishChannelEvent = useCallback(
    async (
      event: WhatsAppChannelEventName,
      extra?: {
        phone_number?: string | null
        error?: string | null
      },
    ) => {
      try {
        const status = await sendWhatsAppChannelEvent(
          {
            event,
            phone_number: extra?.phone_number ?? null,
            error: extra?.error ?? null,
            channel_name: 'whatsapp',
            source: 'dot-desktop',
          },
          getAccessToken,
        )
        setChannelStatus(status)
        setChannelSyncError(null)
        if (status.linked) {
          setAwaitingScan(false)
        }
        return status
      } catch {
        setChannelSyncError(WHATSAPP_LINK_UI.serverSaveError)
        return null
      }
    },
    [getAccessToken],
  )

  const cancelManualCheckPolling = useCallback(() => {
    manualCheckActiveRef.current = false
    if (manualPollTimerRef.current) {
      clearTimeout(manualPollTimerRef.current)
      manualPollTimerRef.current = null
    }
  }, [])

  const markLinkedLocally = useCallback(
    (phoneNumber?: string | null) => {
      if (lastEventRef.current === 'linked' && linkedRef.current) return
      if (import.meta.env.DEV) {
        console.warn('[WhatsApp] Vinculación detectada', { phoneNumber })
      }
      linkedRef.current = true
      setLocalLinked(true)
      lastEventRef.current = 'linked'
      setAwaitingScan(false)
      setScanCheckMessage(null)
      setPendingVerification(false)
      cancelManualCheckPolling()
      setManualCheckInProgress(false)
      void publishChannelEvent('linked', {
        phone_number: phoneNumber ?? detectPhoneNumberInLog(log) ?? null,
      }).then((status) => {
        if (status?.linked) return
        void refreshChannelStatus()
      })
    },
    [cancelManualCheckPolling, log, publishChannelEvent, refreshChannelStatus],
  )

  useEffect(() => {
    if (!hasRawQr) return
    setQrProgress(100)
    setProgressMessage(null)
    setScanCheckMessage(null)
    progressHangRef.current = false
    if (lastEventRef.current !== 'qr_ready') {
      lastEventRef.current = 'qr_ready'
      void publishChannelEvent('qr_ready')
    }
  }, [hasRawQr, publishChannelEvent])

  useEffect(() => {
    if (!isDesktop) return
    void refreshChannelStatus()
    const poll = setInterval(() => {
      void refreshChannelStatus()
    }, 15_000)
    return () => clearInterval(poll)
  }, [isDesktop, refreshChannelStatus])

  /** T-P1-003a: Auto-start QR al montar el paso */
  useEffect(() => {
    if (!isDesktop || runState !== 'idle') return
    void handleStart()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDesktop])

  /* T12: Baileys emite DOT_WHATSAPP_QR (payload escaneable) → data URL.
   * Fallback OpenClaw: arte ASCII ANSI desde logs (legacy).
   */

  useEffect(() => {
    if (!isDesktop) return
    if (!log) return

    if (hasLinkedSignal(log) && hasSeenRawQrRef.current && lastEventRef.current !== 'linked') {
      markLinkedLocally(detectPhoneNumberInLog(log))
      return
    }

    if (hasDisconnectedSignal(log) && hasSeenRawQrRef.current && lastEventRef.current !== 'linked') {
      setScanCheckMessage(WHATSAPP_LINK_UI.scanThenCheck)
      return
    }

    if (hasDisconnectedSignal(log) && lastEventRef.current !== 'disconnected') {
      lastEventRef.current = 'disconnected'
      void publishChannelEvent('disconnected', {
        error: WHATSAPP_LINK_UI.sessionDisconnected,
      })
    }
  }, [isDesktop, log, hasRawQr, publishChannelEvent, markLinkedLocally])

  useEffect(() => {
    if (!isDesktop) return
    const off = onWhatsAppLinked((data) => {
      if (!data.linked) return
      markLinkedLocally(data.phone_number ?? null)
    })
    return off
  }, [isDesktop, markLinkedLocally])

  useEffect(() => {
    if (!isDesktop || runState !== 'ended' || exitInfo?.code !== 0) return
    if (linkedRef.current || lastEventRef.current === 'linked') return
    if (!hasSeenRawQrRef.current) return
    if (hasLinkedSignal(log)) {
      markLinkedLocally(detectPhoneNumberInLog(log))
    }
  }, [isDesktop, runState, exitInfo, log, markLinkedLocally])

  const linkedOk = useMemo(
    () =>
      (localLinked || linkStatus === 'linked' || channelStatus?.linked === true) && !awaitingScan,
    [localLinked, linkStatus, channelStatus?.linked, awaitingScan],
  )

  useEffect(() => {
    if (!linkedOk || autoAdvancedRef.current) return
    autoAdvancedRef.current = true
    const timer = window.setTimeout(() => onContinue(), 1200)
    return () => window.clearTimeout(timer)
  }, [linkedOk, onContinue])

  const append = useCallback((_stream: string, text: string) => {
    setLog((prev) => {
      const next = prev + text
      return next.length > 120_000 ? next.slice(-120_000) : next
    })
  }, [])

  useEffect(() => {
    if (!desktopWhatsApp) return

    const offData = desktopWhatsApp.onData((payload) => {
      append(payload.stream, payload.text)
    })
    const offExit = desktopWhatsApp.onExit((info) => {
      if (unmountingRef.current || restartingRef.current) return
      setRunState('ended')
      setExitInfo(info)
      if (linkedRef.current || lastEventRef.current === 'linked') {
        void publishChannelEvent('heartbeat')
        return
      }
      if (hasRawQrRef.current) {
        setScanCheckMessage(WHATSAPP_LINK_UI.scanThenCheck)
        return
      }
      void publishChannelEvent('disconnected', {
        error: WHATSAPP_LINK_UI.qrGenerateFailed,
      })
    })

    return () => {
      unmountingRef.current = true
      offData()
      offExit()
      void desktopWhatsApp.stop()
    }
  }, [append, desktopWhatsApp, publishChannelEvent])

  useEffect(() => {
    if (!isDesktop || runState !== 'running') return
    const heartbeatInterval = setInterval(() => {
      void publishChannelEvent('heartbeat')
    }, 20_000)
    return () => clearInterval(heartbeatInterval)
  }, [isDesktop, publishChannelEvent, runState])

  // Timeout de generacion QR: si tras 60s no hay QR, mostrar reintentar
  useEffect(() => {
    const qrAvailable = hasRawQr
    if (runState !== 'running' || qrAvailable) {
      setQrTimeout(false)
      return
    }
    const timer = setTimeout(() => {
      setQrTimeout(true)
    }, 60_000)
    return () => clearTimeout(timer)
  }, [runState, hasRawQr])

  async function handleRegenerate() {
    if (!isDesktop) return
    setScanCheckMessage(null)
    try {
      const next = await requestWhatsAppReconnect(getAccessToken)
      setChannelStatus(next)
      setChannelSyncError(null)
    } catch {
      setChannelSyncError(WHATSAPP_LINK_UI.restartError)
    }
    await handleStart()
  }

  async function handleStart() {
    if (!desktopWhatsApp) return
    if (startInFlightRef.current) return
    startInFlightRef.current = true
    restartingRef.current = true
    unmountingRef.current = false
    cancelManualCheckPolling()
    setPendingVerification(false)
      autoAdvancedRef.current = false
      hasSeenRawQrRef.current = false
    try {
      setStartError(null)
      setExitInfo(null)
      setLog('')
      setQrProgress(0)
      setProgressMessage(null)
      progressHangRef.current = false
      setQrTimeout(false)
      setAwaitingScan(true)
      setScanCheckMessage(null)
      setLocalLinked(false)
      setQrDataUrl(null)
      setRunState('running')
      await desktopWhatsApp.stop()
      setChannelStatus((prev) =>
        prev
          ? { ...prev, linked: false, status: 'connecting', reconnect_required: false, error: null }
          : prev,
      )
      lastEventRef.current = 'connecting'
      await publishChannelEvent('connecting')
      const res = await desktopWhatsApp.startWhatsAppLogin()
      restartingRef.current = false
      if (res.ok === false) {
        setRunState('idle')
        const userError = sanitizeWhatsAppUserError(res.error ?? 'No se pudo iniciar la vinculación.')
        setStartError(userError)
        await publishChannelEvent('error', {
          error: userError,
        })
      }
    } finally {
      restartingRef.current = false
      startInFlightRef.current = false
    }
  }

  const handleManualCheck = useCallback(async () => {
    if (!isDesktop || hasRawQr === false || runState !== 'running') return
    if (manualCheckActiveRef.current) return
    manualCheckActiveRef.current = true
    setManualCheckInProgress(true)
    setPendingVerification(false)
    setScanCheckMessage(WHATSAPP_LINK_UI.checkingStatus)
    const deadline = Date.now() + MANUAL_CHECK_TIMEOUT_MS
    let lastStatus: WhatsAppChannelStatus | null = null

    try {
      if (hasLinkedSignal(log) && hasSeenRawQrRef.current) {
        markLinkedLocally(detectPhoneNumberInLog(log))
        return
      }

      while (manualCheckActiveRef.current && Date.now() < deadline) {
        if (hasLinkedSignal(log) && hasSeenRawQrRef.current) {
          markLinkedLocally(detectPhoneNumberInLog(log))
          return
        }
        if (linkedRef.current || lastEventRef.current === 'linked') {
          setAwaitingScan(false)
          setScanCheckMessage(null)
          return
        }

        const status = await refreshChannelStatus()
        lastStatus = status
        if (!status) {
          await new Promise<void>((resolve) => {
            manualPollTimerRef.current = setTimeout(() => {
              manualPollTimerRef.current = null
              resolve()
            }, MANUAL_CHECK_POLL_MS)
          })
          continue
        }
        if (status.linked) {
          linkedRef.current = true
          lastEventRef.current = 'linked'
          setAwaitingScan(false)
          setPendingVerification(false)
          setScanCheckMessage(null)
          return
        }
        if (isPendingVerificationStatus(status)) {
          setPendingVerification(true)
          setScanCheckMessage(null)
        } else {
          setPendingVerification(false)
        }
        if (!manualCheckActiveRef.current) break
        await new Promise<void>((resolve) => {
          manualPollTimerRef.current = setTimeout(() => {
            manualPollTimerRef.current = null
            resolve()
          }, MANUAL_CHECK_POLL_MS)
        })
      }

      if (!linkedRef.current && !lastStatus?.linked) {
        if (lastStatus && isPendingVerificationStatus(lastStatus)) {
          setPendingVerification(true)
          setScanCheckMessage(null)
        } else {
          setPendingVerification(false)
          setScanCheckMessage(WHATSAPP_LINK_UI.manualCheckTimeout)
        }
      }
    } finally {
      cancelManualCheckPolling()
      setManualCheckInProgress(false)
    }
  }, [
    cancelManualCheckPolling,
    hasRawQr,
    isDesktop,
    log,
    markLinkedLocally,
    refreshChannelStatus,
    runState,
  ])

  useEffect(() => cancelManualCheckPolling, [cancelManualCheckPolling])

  const pendingExitMessage =
    exitInfo && runState === 'ended' && !linkedOk && !hasRawQr
      ? WHATSAPP_LINK_UI.linkFailed
      : null
  const pendingVerificationMessage = WHATSAPP_LINK_UI.pendingVerification
  const showEndedError = Boolean(
    isDesktop && runState === 'ended' && !linkedOk && !hasRawQr && !qrTimeout,
  )
  const uiPhase = resolveWhatsAppQrUiPhase({
    isDesktop,
    linkedOk,
    hasQrImage: Boolean(qrSrc),
    runState,
    qrTimeout,
    startError,
    showEndedError,
  })
  const statusText =
    showEndedError
      ? null
      : startError ??
        (pendingVerification ? pendingVerificationMessage : scanCheckMessage) ??
        progressMessage ??
        pendingExitMessage

  return (
    <motion.section
      className="wa-openclaw"
      initial={{ opacity: 0, filter: reduceMotion ? 'blur(0px)' : 'blur(8px)' }}
      animate={{ opacity: 1, filter: 'blur(0px)' }}
      exit={{ opacity: 0, filter: reduceMotion ? 'blur(0px)' : 'blur(8px)' }}
      transition={{ duration: reduceMotion ? 0.12 : 0.55, ease: easing }}
    >
      <div className="wa-openclaw__grain" aria-hidden />
      <div className="wa-openclaw__glow wa-openclaw__glow--a" aria-hidden />
      <div className="wa-openclaw__glow wa-openclaw__glow--b" aria-hidden />

      <motion.div
        className="wa-openclaw__content"
        initial={{ opacity: 0, y: reduceMotion ? 0 : 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: reduceMotion ? 0.12 : 0.55, delay: reduceMotion ? 0 : 0.08 }}
      >
        <motion.h2
          className="wa-openclaw__title"
          initial={{ opacity: 0, y: reduceMotion ? 0 : 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: reduceMotion ? 0.12 : 0.55, delay: reduceMotion ? 0 : 0.12 }}
        >
          Vincular WhatsApp
        </motion.h2>
        <p className="wa-openclaw__lead">{WHATSAPP_LINK_UI.groupSetupHint}</p>

        <div className="wa-openclaw__panel">
        <div className="wa-openclaw__qr-stage">
          {!isDesktop ? (
            <p className="wa-openclaw__placeholder">{WHATSAPP_LINK_UI.desktopOnly}</p>
          ) : uiPhase === 'connected' ? (
            <>
              <p className="wa-openclaw__status wa-openclaw__status--ok">{WHATSAPP_LINK_UI.connected}</p>
              <p className="wa-openclaw__scan-hint wa-openclaw__scan-hint--path">
                {WHATSAPP_LINK_UI.connectedSetupHint}
              </p>
            </>
          ) : hasRawQr && qrSrc ? (
            <motion.div
              className="wa-openclaw__qr-wrapper"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.5, ease: easing }}
            >
              <div className="wa-openclaw__qr-frame">
                <img src={qrSrc} alt="Código QR para vincular WhatsApp" />
              </div>
            </motion.div>
          ) : hasRawQr ? (
            <LoadingScreen
              message={WHATSAPP_LINK_UI.generatingQr}
              className="wa-openclaw__inline-loading"
            />
          ) : uiPhase === 'error' || qrTimeout ? (
            <div className="wa-openclaw__status wa-openclaw__status--error" role="alert">
              <p className="wa-openclaw__error-lead">
                {startError || (qrTimeout ? WHATSAPP_LINK_UI.qrTimeout : WHATSAPP_LINK_UI.linkFailed)}
              </p>
              <button type="button" className="wa-openclaw__regenerate" onClick={() => void handleRegenerate()}>
                {WHATSAPP_LINK_UI.retry}
              </button>
            </div>
          ) : uiPhase === 'generating' ? (
            <LoadingScreen
              message={progressMessage || WHATSAPP_LINK_UI.generatingQr}
              className="wa-openclaw__inline-loading"
            />
          ) : (
            <div className="wa-openclaw__status wa-openclaw__status--error" role="alert">
              <p className="wa-openclaw__error-lead">
                {startError || pendingExitMessage || WHATSAPP_LINK_UI.linkFailed}
              </p>
              <button type="button" className="wa-openclaw__regenerate" onClick={() => void handleRegenerate()}>
                {WHATSAPP_LINK_UI.retryConnection}
              </button>
            </div>
          )}

          {uiPhase === 'scan' && (
            <>
              <p className="wa-openclaw__scan-hint">{WHATSAPP_LINK_UI.scanHint}</p>
              <p className="wa-openclaw__scan-hint wa-openclaw__scan-hint--path">{WHATSAPP_LINK_UI.scanPath}</p>
            </>
          )}

          {uiPhase === 'scan' && runState === 'running' && (
            <button
              type="button"
              className="wa-openclaw__primary"
              onClick={() => void handleManualCheck()}
              disabled={manualCheckInProgress}
              aria-busy={manualCheckInProgress}
              style={{ marginTop: '0.75rem', fontSize: '0.85rem' }}
            >
              {manualCheckInProgress ? WHATSAPP_LINK_UI.checking : WHATSAPP_LINK_UI.alreadyScannedCheck}
            </button>
          )}

          <div
            className={`wa-openclaw__status${startError ? ' wa-openclaw__status--error' : ''}`}
            role="status"
          >
            {statusText}
          </div>
          {channelSyncError ? (
            <div className="wa-openclaw__status wa-openclaw__status--error" role="alert">
              {channelSyncError}
            </div>
          ) : null}
          {channelStatus?.reconnect_required &&
          runState === 'running' &&
          hasRawQr &&
          !linkedOk ? (
            <button type="button" className="wa-openclaw__regenerate" onClick={() => void handleRegenerate()}>
              {WHATSAPP_LINK_UI.retryConnection}
            </button>
          ) : null}
        </div>
        </div>

        {/* T-P1-003: Botones footer: Retroceder · Omitir · Continuar */}
        <motion.div
          className="wa-openclaw__actions"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: reduceMotion ? 0.12 : 0.45, delay: reduceMotion ? 0 : 0.28 }}
        >
          <button type="button" className="wa-openclaw__back" onClick={onBack}>
            Retroceder
          </button>
          <button type="button" className="wa-openclaw__secondary" onClick={onSkip}>
            Omitir
          </button>
          <button type="button" className="wa-openclaw__primary" onClick={onContinue}>
            Continuar
          </button>
        </motion.div>
      </motion.div>
    </motion.section>
  )
}

/** @deprecated Legacy alias. Use {@link WhatsappLinkStep} instead. */
export const WhatsappOpenClawLinkStep = WhatsappLinkStep
