import { describe, expect, it } from 'vitest'

import { ApiError } from '@/lib/api/http'
import {
  LOCAL_BACKEND_UNREACHABLE_MESSAGE,
  isTechnicalMessage,
  sanitizeWhatsAppUserError,
  translateApiError,
  translateError,
  translateErrorMessage,
} from './error-messages'

describe('error-messages', () => {
  it('oculta términos técnicos', () => {
    expect(isTechnicalMessage('ECONNREFUSED 127.0.0.1:8000')).toBe(true)
    expect(isTechnicalMessage('OpenClaw process exited')).toBe(true)
    expect(isTechnicalMessage('npm run backend:dev')).toBe(true)
    expect(isTechnicalMessage('sandbox deny: browser')).toBe(true)
    expect(isTechnicalMessage('Traceback (most recent call last)')).toBe(true)
  })

  it('traduce errores de red', () => {
    expect(translateErrorMessage('Failed to fetch')).toContain('conexión')
    expect(translateError(new TypeError('Failed to fetch'))).toContain('conexión')
  })

  it('oculta términos internos de WhatsApp', () => {
    expect(sanitizeWhatsAppUserError('OpenClaw login failed')).not.toMatch(/openclaw/i)
    expect(sanitizeWhatsAppUserError('Worker Baileys no encontrado')).not.toMatch(/baileys/i)
    expect(sanitizeWhatsAppUserError('gateway closed (1006)')).not.toMatch(/gateway/i)
    expect(sanitizeWhatsAppUserError('npm install openclaw')).not.toMatch(/npm/i)
  })

  it('traduce bridge_unreachable a mensaje de WhatsApp', () => {
    expect(translateErrorMessage('bridge_unreachable')).toContain('WhatsApp')
  })

  it('no expone códigos HTTP en toasts', () => {
    const err = new ApiError('ProviderNotAvailable: deepseek down', 503)
    expect(translateApiError(err)).not.toMatch(/503/)
    expect(translateApiError(err)).toContain('problemas')
  })

  it('backend local sin npm', () => {
    expect(LOCAL_BACKEND_UNREACHABLE_MESSAGE).not.toMatch(/npm/i)
  })

  it('traduce falta de scope Drive a reconectar Google', () => {
    expect(translateErrorMessage('permiso de Drive')).toContain('Configuración → Google')
    expect(translateErrorMessage('permiso de Drive')).toContain('desvincula')
  })
})
