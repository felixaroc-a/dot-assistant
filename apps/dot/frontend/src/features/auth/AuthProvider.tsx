import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import {
  loginWithCedula,
  logoutOnServer,
  recoveryLogin as recoveryLoginApi,
  refreshAccessToken,
  type LoginResponseDto,
} from '@/lib/api/auth-login'
import { ApiError } from '@/lib/api/http'
import { translateError } from '@/lib/error-messages'
import { isSubscriptionExpired as isSubscriptionExpiredByDate } from '@/lib/subscription-expiry'
import { fingerprintHardwareSerial } from '@/lib/desktop/hardware-fingerprint'
import { readJwtExpMs, readJwtHardwareRequired } from '@/lib/jwt'
import {
  clearHardwareBindFingerprint,
  saveHardwareBindFingerprint,
} from '@/lib/hardware-bind-storage'
import { clearSecureJson, loadSecureJson, migrateLegacyLocalStorage, saveSecureJson } from '@/lib/secure-session'
import { wsClient } from '@/lib/websocket-client'

import { AuthReactContext } from './auth-context'
import type { AuthContextValue, ProductSession } from './types'

/** [DEV] Bypass de login: desactivar login real y crear sesión de prueba */
const DEV_SKIP_LOGIN = false

/** Misma secret que backend/.env JWT_SECRET para firmar tokens dev.
 *  SOLO disponible en desarrollo (MODE !== 'production'). En producción es undefined.*/
const DEV_JWT_SECRET: string | undefined =
  import.meta.env.MODE !== 'production'
    ? import.meta.env.VITE_DEV_JWT_SECRET as string | undefined
    : undefined

function base64url(data: Uint8Array): string {
  return btoa(String.fromCharCode(...data))
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
}

/** [DEV] Crea un JWT real firmado con HS256 usando la secret del backend */
async function createDevJwt(): Promise<string> {
  if (!DEV_JWT_SECRET) {
    throw new Error('DEV_JWT_SECRET no configurada en variables de entorno. Define VITE_DEV_JWT_SECRET en .env.development')
  }
  const header = { alg: 'HS256', typ: 'JWT' }
  const now = Math.floor(Date.now() / 1000)
  const payload = {
    sub: 'dev-cliente-id',
    cedula: 'V-12345678',
    email: 'dev@dot.ai',
    plan: 'anual',
    fecha_vencimiento: new Date(Date.now() + 365 * 24 * 3600 * 1000).toISOString().split('T')[0],
    token_use: 'access',
    jti: crypto.randomUUID(),
    iat: now,
    exp: now + 365 * 24 * 3600 * 10,
    hardware_required: false,
  }

  const encoder = new TextEncoder()
  const headerB64 = base64url(encoder.encode(JSON.stringify(header)))
  const payloadB64 = base64url(encoder.encode(JSON.stringify(payload)))
  const message = `${headerB64}.${payloadB64}`

  const key = await crypto.subtle.importKey(
    'raw',
    encoder.encode(DEV_JWT_SECRET),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  )

  const signature = await crypto.subtle.sign('HMAC', key, encoder.encode(message))
  const signatureB64 = base64url(new Uint8Array(signature))

  return `${message}.${signatureB64}`
}

/** [DEV] Sesion de prueba con JWT real firmado */
async function createDevSession(): Promise<ProductSession> {
  const token = await createDevJwt()
  return {
    accessToken: token,
    refreshToken: `${token}-refresh`,
    cliente: {
      cliente_id: 'dev-cliente-id',
      cedula: 'V-12345678',
      plan: 'anual',
      fecha_vencimiento: new Date(Date.now() + 365 * 24 * 3600 * 1000).toISOString().split('T')[0],
      correo: 'dev@dot.ai',
    },
    expiresAtMs: readJwtExpMs(token),
    hardwareRequired: null,
    recoveryKey: 'DEV-RECOVERY-KEY-PARA-PRUEBAS-LOCALES',
  }
}

/** Renovar 30 segundos antes de expirar */
const REFRESH_MARGIN_MS = 30_000
/** Intervalo de chequeo cada 15 segundos */
const CHECK_INTERVAL_MS = 15_000
/** Tiempo maximo para restaurar sesion desde almacenamiento seguro */
const SESSION_RESTORE_TIMEOUT_MS = 10_000

function withTimeout<T>(promise: Promise<T>, ms: number, message: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error(message)), ms)
    promise.then(
      (value) => {
        window.clearTimeout(timer)
        resolve(value)
      },
      (error) => {
        window.clearTimeout(timer)
        reject(error instanceof Error ? error : new Error(String(error)))
      },
    )
  })
}

function parseSession(raw: string | null): ProductSession | null {
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as ProductSession & { expiresAtMs?: unknown }
    if (
      typeof parsed.accessToken !== 'string' ||
      typeof parsed.refreshToken !== 'string' ||
      !parsed.cliente ||
      typeof parsed.cliente.cedula !== 'string'
    ) {
      return null
    }
    const expiresAtMs =
      typeof parsed.expiresAtMs === 'number' ? parsed.expiresAtMs : readJwtExpMs(parsed.accessToken)
    const hardwareRequired =
      typeof parsed.hardwareRequired === 'boolean'
        ? parsed.hardwareRequired
        : readJwtHardwareRequired(parsed.accessToken)
    return {
      accessToken: parsed.accessToken,
      refreshToken: parsed.refreshToken,
      cliente: parsed.cliente,
      expiresAtMs,
      hardwareRequired,
      recoveryKey: typeof parsed.recoveryKey === 'string' ? parsed.recoveryKey : undefined,
    }
  } catch {
    console.warn('[AuthProvider] No se pudo parsear la sesión guardada')
    return null
  }
}

async function persistSession(session: ProductSession | null) {
  if (session) {
    await saveSecureJson(JSON.stringify(session))
  } else {
    await clearSecureJson()
    await clearHardwareBindFingerprint()
    await window.desktop?.usbSerial?.unbind?.()
  }
}

type AuthProviderProps = {
  children: ReactNode
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [session, setSession] = useState<ProductSession | null>(null)
  const [loading, setLoading] = useState(true)
  const [sessionRestoreError, setSessionRestoreError] = useState<string | null>(null)
  const refreshPromiseRef = useRef<Promise<void> | null>(null)
  const restoreAttemptRef = useRef(0)
  const sessionRef = useRef(session)
  sessionRef.current = session

  useEffect(() => {
    if (DEV_SKIP_LOGIN) {
      ;(async () => {
        const devSession = await createDevSession()
        setSession(devSession)
        setLoading(false)
        // Conectar WebSocket con el token dev
        wsClient.connect(devSession.accessToken)
      })()
      return
    }
    let cancelled = false
    const attemptId = ++restoreAttemptRef.current
    ;(async () => {
      try {
        const raw = await withTimeout(
          (async () => {
            await migrateLegacyLocalStorage()
            return loadSecureJson()
          })(),
          SESSION_RESTORE_TIMEOUT_MS,
          'Tiempo de espera agotado al restaurar la sesión',
        )
        if (!cancelled) {
          setSession(parseSession(raw))
          setSessionRestoreError(null)
        }
      } catch (err) {
        const message =
          translateError(err, 'No se pudo restaurar la sesión guardada.')
        console.warn('[AuthProvider] Error al cargar la sesión segura:', err)
        if (!cancelled) {
          setSession(null)
          setSessionRestoreError(message)
        }
      } finally {
        if (!cancelled && restoreAttemptRef.current === attemptId) {
          setLoading(false)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const clearLocalSession = useCallback(() => {
    void persistSession(null)
    setSession(null)
  }, [])

  const logout = useCallback(() => {
    wsClient.disconnect()
    const current = sessionRef.current
    if (current?.accessToken) {
      void logoutOnServer(current.accessToken, current.refreshToken).catch(() => {
        console.warn('[AuthProvider] No se pudo cerrar sesión en el servidor; se limpia local')
      })
    }
    clearLocalSession()
  }, [clearLocalSession])

  const doRefresh = useCallback(async () => {
    const current = sessionRef.current
    if (!current?.refreshToken) return

    try {
      const dto = await refreshAccessToken(current.refreshToken)
      const next: ProductSession = {
        accessToken: dto.access_token,
        refreshToken: dto.refresh_token,
        cliente: current.cliente,
        expiresAtMs: readJwtExpMs(dto.access_token),
        hardwareRequired: current.hardwareRequired,
        recoveryKey: current.recoveryKey,
      }
      await persistSession(next)
      setSession(next)
    } catch (err) {
      const isDefinitiveAuthFailure =
        err instanceof ApiError && (err.status === 401 || err.status === 403)
      if (isDefinitiveAuthFailure) {
        console.warn('[AuthProvider] Refresh token inválido; limpiando sesión local')
        clearLocalSession()
      } else {
        console.warn('[AuthProvider] Error transitorio al refrescar token; manteniendo sesión', err)
      }
    }
  }, [clearLocalSession])

  const getAccessToken = useCallback(async (): Promise<string | null> => {
    const current = sessionRef.current
    if (!current) return null

    const expiresAt = current.expiresAtMs
    if (expiresAt !== null && Date.now() >= expiresAt - REFRESH_MARGIN_MS) {
      if (!refreshPromiseRef.current) {
        refreshPromiseRef.current = doRefresh().finally(() => {
          refreshPromiseRef.current = null
        })
      }
      await refreshPromiseRef.current
      return sessionRef.current?.accessToken ?? null
    }

    return current.accessToken
  }, [doRefresh])

  const login = useCallback(async (cedula: string, password: string, hardwareSerial?: string | null) => {
    setSessionRestoreError(null)
    try {
      const dto = await loginWithCedula(cedula, password, hardwareSerial)
      const hardwareRequired = readJwtHardwareRequired(dto.access_token)
      const next: ProductSession = {
        accessToken: dto.access_token,
        refreshToken: dto.refresh_token,
        cliente: dto.cliente,
        expiresAtMs: readJwtExpMs(dto.access_token),
        hardwareRequired,
        recoveryKey: (dto as LoginResponseDto & { recovery_key?: string }).recovery_key ?? undefined,
      }
      // Guardar fingerprint ANTES de persistir sesión, para evitar sesiones
      // huérfanas (sesión persistida sin fingerprint, que causaba loop en PendriveAppGate)
      if (hardwareSerial?.trim()) {
        const fp = await fingerprintHardwareSerial(hardwareSerial.trim())
        await saveHardwareBindFingerprint(fp)
        await window.desktop?.usbSerial?.bind?.(hardwareSerial.trim())
      }
      await persistSession(next)
      setSession(next)
      // Conectar WebSocket para notificaciones en tiempo real
      wsClient.connect(next.accessToken)
    } catch (err) {
      console.error('[Auth] Login fallo:', err)
      throw err
    }
  }, [])

  const recoveryLogin = useCallback(async (cedula: string, password: string, recoveryKey: string) => {
    setSessionRestoreError(null)
    try {
      const dto = await recoveryLoginApi(cedula, password, recoveryKey)
      const hardwareRequired = readJwtHardwareRequired(dto.access_token)
      const next: ProductSession = {
        accessToken: dto.access_token,
        refreshToken: dto.refresh_token,
        cliente: dto.cliente,
        expiresAtMs: readJwtExpMs(dto.access_token),
        hardwareRequired,
        recoveryKey: (dto as LoginResponseDto & { recovery_key?: string }).recovery_key ?? recoveryKey,
      }
      await persistSession(next)
      setSession(next)
      wsClient.connect(next.accessToken)
    } catch (err) {
      console.error('[Auth] Recovery login fallo:', err)
      throw err
    }
  }, [])

  useEffect(() => {
    const interval = window.setInterval(() => {
      const current = sessionRef.current
      if (!current?.expiresAtMs || !current.refreshToken) return

      if (Date.now() >= current.expiresAtMs - REFRESH_MARGIN_MS) {
        void doRefresh()
      }
    }, CHECK_INTERVAL_MS)

    return () => window.clearInterval(interval)
  }, [doRefresh])

  const isSubscriptionExpired = useMemo(() => {
    const raw = session?.cliente?.fecha_vencimiento
    if (!raw) return false
    return isSubscriptionExpiredByDate(raw)
  }, [session])

  const subscriptionExpiryDate: string | null =
    session?.cliente?.fecha_vencimiento ?? null

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      loading,
      sessionRestoreError,
      getAccessToken,
      login,
      recoveryLogin,
      logout,
      isSubscriptionExpired,
      subscriptionExpiryDate,
    }),
    [
      session,
      loading,
      sessionRestoreError,
      getAccessToken,
      login,
      recoveryLogin,
      logout,
      isSubscriptionExpired,
      subscriptionExpiryDate,
    ],
  )

  return <AuthReactContext.Provider value={value}>{children}</AuthReactContext.Provider>
}
