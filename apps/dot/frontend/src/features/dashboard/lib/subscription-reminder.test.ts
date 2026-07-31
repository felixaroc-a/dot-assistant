import { describe, expect, it } from 'vitest'

import { buildSubscriptionReminder } from './subscription-reminder'

describe('buildSubscriptionReminder', () => {
  it('retorna null cuando faltan mas de 7 dias', () => {
    const reminder = buildSubscriptionReminder('2030-01-20T00:00:00Z', new Date('2030-01-10T00:00:00Z'))
    expect(reminder).toBeNull()
  })

  it('retorna texto singular cuando falta 1 dia', () => {
    const reminder = buildSubscriptionReminder('2030-01-11T11:00:00', new Date('2030-01-10T12:00:00'))
    expect(reminder).not.toBeNull()
    expect(reminder?.daysRemaining).toBe(1)
    expect(reminder?.bannerText).toContain('1 día')
  })

  it('retorna texto para vencimiento hoy', () => {
    const reminder = buildSubscriptionReminder('2030-01-10T23:00:00Z', new Date('2030-01-10T08:00:00Z'))
    expect(reminder).not.toBeNull()
    expect(reminder?.daysRemaining).toBe(0)
    expect(reminder?.bannerText).toContain('vence hoy')
  })

  it('soporta formato YYYY-MM-DD con vencimiento hoy', () => {
    const reminder = buildSubscriptionReminder('2030-01-10', new Date('2030-01-10T12:00:00'))
    expect(reminder).not.toBeNull()
    expect(reminder?.daysRemaining).toBe(0)
  })
})
