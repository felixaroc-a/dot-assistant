import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

import { fingerprintHardwareSerial, hardwareSerialMatchesFingerprint } from '@/lib/desktop/hardware-fingerprint'
import { isUsbGateSkipped } from '@/lib/desktop/usb-gate-dev'
import { readReadyDotUsbSerial } from '@/lib/desktop/usb-serial'
import {
  clearHardwareBindFingerprint,
  loadHardwareBindFingerprint,
  saveHardwareBindFingerprint,
} from '@/lib/hardware-bind-storage'

import { PendriveGateScreen } from './PendriveGateScreen'
import { LoadingScreen } from '@/components/LoadingScreen'

import { useAuth } from './auth-context'

type PendriveAppGateProps = {
  children: ReactNode
}

type GatePhase = 'checking' | 'blocked' | 'ready'

/**
 * Capa React: valida pendrive al restaurar sesión y reacciona a desconexión en caliente.
 * El arranque sin pendrive lo bloquea Electron antes de cargar la UI principal.
 */
export function PendriveAppGate({ children }: PendriveAppGateProps) {
  const { session, loading, logout } = useAuth()
  const [phase, setPhase] = useState<GatePhase>('checking')
  const [disconnectDetail, setDisconnectDetail] = useState<string | null>(null)
  const initialValidationDone = useRef(false)

  const bindMainProcess = useCallback(async (serial: string) => {
    await window.desktop?.usbSerial?.bind?.(serial)
  }, [])

  const unbindMainProcess = useCallback(async () => {
    await window.desktop?.usbSerial?.unbind?.()
  }, [])

  const validateSessionUsb = useCallback(async (): Promise<boolean> => {
    if (!window.desktop?.usbSerial?.get) {
      setPhase('ready')
      return true
    }

    // Si el JWT fue emitido via recovery key (hardware_required=false),
    // saltamos la validacion de pendrive para mostrar PendriveLostFlow
    if (session?.hardwareRequired === false) {
      await unbindMainProcess()
      setDisconnectDetail(null)
      setPhase('ready')
      return true
    }

    if (await isUsbGateSkipped()) {
      await unbindMainProcess()
      setDisconnectDetail(null)
      setPhase('ready')
      return true
    }

    const stored = await loadHardwareBindFingerprint()
    if (!session) {
      await unbindMainProcess()
      setPhase('ready')
      return true
    }

    const usb = await readReadyDotUsbSerial()
    if (!usb.serial) {
      setDisconnectDetail('No se detecta el pendrive. Conéctalo para continuar.')
      setPhase('blocked')
      return false
    }

    if (!stored) {
      // No hay fingerprint guardado. En lugar de hacer logout (que causaba loop
      // cuando window.desktop.hardwareBind no está disponible o el storage se
      // limpió), guardamos el fingerprint ahora y proseguimos.
      // - Si hardwareBind no existe: saveHardwareBindFingerprint es no-op → igual proseguimos
      // - Si hardwareBind existe pero se perdió el fingerprint: re-establecemos el enlace
      const fp = await fingerprintHardwareSerial(usb.serial)
      await saveHardwareBindFingerprint(fp)
      await bindMainProcess(usb.serial)
      setDisconnectDetail(null)
      setPhase('ready')
      return true
    }

    const match = await hardwareSerialMatchesFingerprint(usb.serial, stored)
    if (!match) {
      setDisconnectDetail(
        'El pendrive conectado no coincide con el de tu última sesión. Usa la misma llave DOT.',
      )
      logout()
      await clearHardwareBindFingerprint()
      setPhase('blocked')
      return false
    }

    await bindMainProcess(usb.serial)
    setDisconnectDetail(null)
    setPhase('ready')
    return true
  }, [session, logout, bindMainProcess, unbindMainProcess])

  useEffect(() => {
    if (loading) return

    // Si la validacion inicial ya se completo y hay sesion (login fresco),
    // no re-valida USB: el login ya guardo fingerprint y bindeo el pendrive.
    // Esto evita el loop splash→login al evitar que validateSessionUsb
    // falle (ej. fingerprint no disponible, USB no detectado inmediatamente).
    if (initialValidationDone.current && session) {
      setPhase('ready')
      return
    }

    setPhase('checking')
    let cancelled = false
    ;(async () => {
      try {
        const ok = await validateSessionUsb()
        if (!cancelled && ok) {
          setPhase('ready')
          initialValidationDone.current = true
        }
      } catch (err) {
        console.error('[PendriveAppGate] Error validando pendrive:', err)
        if (!cancelled) {
          setDisconnectDetail('Error inesperado al verificar la llave DOT. Reconecta e intenta de nuevo.')
          setPhase('blocked')
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [loading, session, validateSessionUsb])

  useEffect(() => {
    const onLost = window.desktop?.usbSerial?.onLost
    if (!onLost) return undefined

    let cancelled = false
    let unsubscribe: (() => void) | undefined

    void isUsbGateSkipped().then((skipped) => {
      if (cancelled || skipped) return
      unsubscribe = onLost((payload) => {
        const reason =
          payload?.reason === 'mismatch'
            ? 'Se detectó otro pendrive. Vuelve a conectar tu llave DOT original.'
            : 'Se desconectó tu llave DOT. La sesión local se cerró por seguridad.'
        setDisconnectDetail(reason)
        logout()
        void clearHardwareBindFingerprint()
        void unbindMainProcess()
        setPhase('blocked')
      })
    })

    return () => {
      cancelled = true
      unsubscribe?.()
    }
  }, [logout, unbindMainProcess])

  if (loading || phase === 'checking') {
    return <LoadingScreen message="Verificando llave DOT…" />
  }

  if (phase === 'blocked') {
    return (
      <PendriveGateScreen
        detail={disconnectDetail}
        onReady={() => {
          setDisconnectDetail(null)
          void validateSessionUsb().then((ok) => {
            if (ok) setPhase('ready')
          })
        }}
      />
    )
  }

  return <>{children}</>
}
