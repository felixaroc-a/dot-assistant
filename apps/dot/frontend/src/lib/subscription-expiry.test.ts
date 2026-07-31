import { describe, expect, it } from 'vitest'

import { isSubscriptionExpired, parseFechaVencimiento } from './subscription-expiry'

describe('parseFechaVencimiento', () => {
  it('parsea YYYY-MM-DD', () => {
    expect(parseFechaVencimiento('2026-12-31')).toEqual({
      year: 2026,
      month: 12,
      day: 31,
    })
  })

  it('rechaza formatos inválidos', () => {
    expect(parseFechaVencimiento('bad')).toBeNull()
    expect(parseFechaVencimiento('2026-13-40')).toBeNull()
  })
})

describe('isSubscriptionExpired', () => {
  it('marca vencida solo cuando hoy UTC es posterior al día de vencimiento', () => {
    const ref = new Date('2026-12-31T23:30:00.000Z')
    expect(isSubscriptionExpired('2026-12-30', ref)).toBe(true)
    expect(isSubscriptionExpired('2026-12-31', ref)).toBe(false)
    expect(isSubscriptionExpired('2027-01-01', ref)).toBe(false)
  })

  it('no marca vencida el mismo día UTC (evita falsos positivos por timezone)', () => {
    const ref = new Date('2026-12-31T08:00:00.000Z')
    expect(isSubscriptionExpired('2026-12-31', ref)).toBe(false)
  })

  it('marca vencida al día siguiente UTC', () => {
    const ref = new Date('2027-01-01T00:00:01.000Z')
    expect(isSubscriptionExpired('2026-12-31', ref)).toBe(true)
  })

  it('evita falso positivo de new Date(YYYY-MM-DD) < now en el día de vencimiento', () => {
    const ref = new Date('2026-12-31T15:00:00.000Z')
    const legacyParsed = new Date('2026-12-31')
    expect(legacyParsed < ref).toBe(true)
    expect(isSubscriptionExpired('2026-12-31', ref)).toBe(false)
  })
})
