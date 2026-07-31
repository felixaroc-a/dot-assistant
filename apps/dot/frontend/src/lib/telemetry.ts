/**
 * Telemetria minima del lado cliente.
 * Solo errores de sesion, latencia de API, fallos de proveedor.
 * Sin datos personales.
 */

import { getApiBaseUrl } from '@/lib/api/base-url'

const TELEMETRY_PATH = '/v1/telemetry/event'

/** URL absoluta del endpoint de telemetría (usa la misma base que apiFetchJson). */
export function resolveTelemetryEventUrl(): string {
  const base = getApiBaseUrl().replace(/\/$/, '')
  return `${base}${TELEMETRY_PATH}`
}

type TelemetryEvent = {
  type: 'session_error' | 'api_latency' | 'provider_failure' | 'login_failure'
  timestamp: string
  meta: Record<string, string | number | boolean | null>
}

let enabled = true

export function disableTelemetry() {
  enabled = false
}

export function enableTelemetry() {
  enabled = true
}

function send(event: TelemetryEvent) {
  if (!enabled) return
  try {
    const url = resolveTelemetryEventUrl()
    const payload = JSON.stringify(event)
    if (navigator.sendBeacon) {
      const blob = new Blob([payload], { type: 'application/json' })
      navigator.sendBeacon(url, blob)
    } else {
      fetch(url, {
        method: 'POST',
        body: payload,
        headers: { 'Content-Type': 'application/json' },
        keepalive: true,
      }).catch(() => {
        /* fallo silencioso */
      })
    }
  } catch {
    /* ignorar errores de telemetria */
  }
}

export function trackSessionError(errorType: string, detail?: string) {
  send({
    type: 'session_error',
    timestamp: new Date().toISOString(),
    meta: { errorType: errorType, detail: detail ?? '' },
  })
}

export function trackApiLatency(endpoint: string, durationMs: number, status: number) {
  send({
    type: 'api_latency',
    timestamp: new Date().toISOString(),
    meta: { endpoint, durationMs: Math.round(durationMs), status },
  })
}

export function trackProviderFailure(providerId: string, errorMessage: string) {
  send({
    type: 'provider_failure',
    timestamp: new Date().toISOString(),
    meta: { providerId, errorMessage: errorMessage.slice(0, 200) },
  })
}

export function trackLoginFailure(reason: string) {
  send({
    type: 'login_failure',
    timestamp: new Date().toISOString(),
    meta: { reason },
  })
}
