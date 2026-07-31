import { describe, expect, it } from 'vitest'

import { isPendingVerificationStatus } from './whatsappLinkStatus'

const baseStatus = {
  status: 'connecting' as const,
  linked: false,
  phone_number: null,
  channel_name: null,
  last_linked_at: null,
  last_disconnected_at: null,
  last_qr_at: '2026-07-03T00:00:00Z',
  last_heartbeat_at: null,
  last_error_at: null,
  reconnect_required: false,
  reconnect_attempts: 0,
  error: null,
}

describe('isPendingVerificationStatus', () => {
  it('marca true cuando ya hubo QR, no hay error y el estado sigue en connecting', () => {
    expect(isPendingVerificationStatus(baseStatus)).toBe(true)
  })

  it('ignora cuando ya marcamos linked', () => {
    expect(isPendingVerificationStatus({ ...baseStatus, linked: true })).toBe(false)
  })

  it('ignora cuando hay error o reconnect_required', () => {
    expect(isPendingVerificationStatus({ ...baseStatus, error: 'timeout' })).toBe(false)
    expect(isPendingVerificationStatus({ ...baseStatus, reconnect_required: true })).toBe(false)
  })

  it('ignora cuando no hay QR registrado aún', () => {
    expect(isPendingVerificationStatus({ ...baseStatus, last_qr_at: null })).toBe(false)
  })
})
