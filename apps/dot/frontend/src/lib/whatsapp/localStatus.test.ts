import { describe, expect, it } from 'vitest'

import { toLinkStatus } from '@/lib/api/whatsapp'
import {
  electronNeedsWhatsAppRescan,
  electronStatusToLinkStatus,
} from '@/lib/whatsapp/localStatus'

describe('toLinkStatus', () => {
  it('prioriza connecting aunque linked siga true (reconexión silenciosa)', () => {
    const status = toLinkStatus({
      status: 'connecting',
      linked: true,
      phone_number: '+584121234567',
      channel_name: null,
      last_linked_at: null,
      last_disconnected_at: null,
      last_qr_at: null,
      last_heartbeat_at: null,
      last_error_at: null,
      reconnect_required: false,
      reconnect_attempts: 1,
      error: null,
    })
    expect(status).toBe('connecting')
  })
})

describe('electronStatusToLinkStatus', () => {
  it('restarting con creds → connecting (sin QR)', () => {
    expect(
      electronStatusToLinkStatus({
        connectionState: 'restarting',
        linked: true,
        configured: true,
        needsFreshLogin: false,
      }),
    ).toBe('connecting')
  })

  it('disconnected sin creds → disconnected', () => {
    expect(
      electronStatusToLinkStatus({
        connectionState: 'disconnected',
        configured: false,
        needsFreshLogin: true,
        error: 'Vuelve a escanear el código.',
      }),
    ).toBe('disconnected')
  })
})

describe('electronNeedsWhatsAppRescan', () => {
  it('detecta sesión muerta por needsFreshLogin', () => {
    expect(electronNeedsWhatsAppRescan({ needsFreshLogin: true })).toBe(true)
  })
})
