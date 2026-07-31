import { useCallback, useEffect, useRef, useState } from 'react'

import { readReadyDotUsbSerial, listUsbSerials } from '@/lib/desktop/usb-serial'
import { translateErrorMessage } from '@/lib/error-messages'

import './login-gate.css'

type PendriveGateScreenProps = {
  /** Mensaje adicional (p. ej. tras desconectar el pendrive). */
  detail?: string | null
  onReady?: () => void
}

type DetectionStatus =
  | 'searching'
  | 'detected'
  | 'multiple_usb'
  | 'vault_missing'
  | 'vault_invalid'
  | 'no_usb'
  | 'error'

const POLL_MS = 2500

export function PendriveGateScreen({ detail, onReady }: PendriveGateScreenProps) {
  const [detectionStatus, setDetectionStatus] = useState<DetectionStatus>('searching')
  const [statusText, setStatusText] = useState<string>('Buscando tu llave DOT…')
  const [error, setError] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false)
  const [devices, setDevices] = useState<string[]>([])
  const mountedRef = useRef(true)

  useEffect(() => {
    return () => { mountedRef.current = false }
  }, [])

  const probe = useCallback(async () => {
    if (!mountedRef.current) return false
    setRetrying(true)

    try {
      const usb = await readReadyDotUsbSerial()
      if (!mountedRef.current) return false

      if (usb.serial) {
        setDetectionStatus('detected')
        setError(null)
        setStatusText('Llave DOT detectada.')
        setDevices([usb.serial])
        onReady?.()
        return true
      }

      // Determinar estado de detección
      const errorMsg = usb.error ?? ''
      if (errorMsg.includes('varios USB') || errorMsg.includes('múltiples')) {
        setDetectionStatus('multiple_usb')
        setStatusText('Se detectaron múltiples pendrives USB.')
        setError('Hay varios USB conectados. Deja solo la llave DOT y reintenta, o selecciona uno de la lista.')
      } else if (errorMsg.includes('no está preparado') || errorMsg.includes('vault')) {
        setDetectionStatus('vault_missing')
        setStatusText('USB detectado sin configuración DOT.')
        setError(translateErrorMessage(usb.error ?? '', 'USB detectado sin configuración DOT.'))
      } else if (errorMsg.includes('no válida') || errorMsg.includes('inválido')) {
        setDetectionStatus('vault_invalid')
        setStatusText('USB detectado con vault no válido.')
        setError(translateErrorMessage(usb.error ?? '', 'USB detectado sin configuración DOT.'))
      } else {
        setDetectionStatus('no_usb')
        setStatusText('Esperando pendrive DOT…')
        setError(translateErrorMessage(usb.error ?? '', 'Conecta tu llave DOT (pendrive USB).'))
      }

      // Si hay múltiples USB, listarlos
      if (detectionStatus === 'multiple_usb' || usb.devices?.length > 1) {
        try {
          const allDevices = await listUsbSerials()
          if (mountedRef.current) setDevices(allDevices)
        } catch { /* ignorar */ }
      }

      return false
    } finally {
      if (mountedRef.current) setRetrying(false)
    }
  }, [onReady])

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setInterval> | undefined

    const tick = async () => {
      if (cancelled) return
      const ok = await probe()
      if (ok && timer) {
        clearInterval(timer)
        timer = undefined
      }
    }

    void tick()
    timer = setInterval(() => {
      void tick()
    }, POLL_MS)

    return () => {
      cancelled = true
      if (timer) clearInterval(timer)
    }
  }, [probe])

  const handleManualRetry = () => {
    void probe()
  }

  const handleSelectDevice = (serial: string) => {
    setError(null)
    setDetectionStatus('searching')
    setStatusText(`Verificando USB ${serial}…`)
    onReady?.()
  }

  const statusIndicator = {
    searching: '🔄',
    detected: '✓',
    multiple_usb: '⚠️',
    vault_missing: '⚠️',
    vault_invalid: '✗',
    no_usb: '⊙',
    error: '✗',
  }

  return (
    <div className="login-gate--compact" role="status" aria-live="polite">
      <h1 className="login-gate__title">Conecta tu llave DOT</h1>
      <p className="login-gate__text">
        <span aria-hidden="true">{statusIndicator[detectionStatus]} </span>
        {statusText}
      </p>
      {detail ? <p className="login-gate__text">{detail}</p> : null}
      {error ? (
        <p className="login-gate__error" role="alert">
          {error}
        </p>
      ) : null}

      {detectionStatus === 'multiple_usb' && devices.length > 1 ? (
        <div className="login-gate__devices" style={{ marginTop: '0.75rem' }}>
          <p className="login-gate__label">USB detectados:</p>
          <ul className="login-gate__device-list">
            {devices.map((serial) => (
              <li key={serial}>
                <button
                  type="button"
                  className="login-gate__device-btn"
                  onClick={() => handleSelectDevice(serial)}
                >
                  {serial}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <button
        type="button"
        className="login-gate__retry"
        onClick={handleManualRetry}
        disabled={retrying}
      >
        {retrying ? 'Buscando…' : 'Reintentar ahora'}
      </button>
    </div>
  )
}
