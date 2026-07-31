const ONE_DAY_MS = 1000 * 60 * 60 * 24
const ISO_DATE_ONLY_RE = /^\d{4}-\d{2}-\d{2}$/

export type SubscriptionReminder = {
  daysRemaining: number
  bannerText: string
  notificationTitle: string
  notificationBody: string
}

function toExpiryDate(raw: string): Date | null {
  const value = raw.trim()
  if (!value) return null

  // Si viene solo la fecha, tomamos fin de día local para evitar alertas adelantadas.
  if (ISO_DATE_ONLY_RE.test(value)) {
    const parsed = new Date(`${value}T23:59:59.999`)
    return Number.isNaN(parsed.getTime()) ? null : parsed
  }

  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function getBannerText(daysRemaining: number): string {
  if (daysRemaining <= 0) {
    return 'Tu suscripción vence hoy. Renueva para evitar interrupciones.'
  }
  if (daysRemaining === 1) {
    return 'Tu suscripción vence en 1 día. Renueva cuanto antes.'
  }
  return `Tu suscripción vence en ${daysRemaining} días. Planifica tu renovación.`
}

function isSameLocalDate(left: Date, right: Date): boolean {
  return (
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate()
  )
}

export function buildSubscriptionReminder(
  expiryDateIso: string | null,
  now: Date = new Date(),
): SubscriptionReminder | null {
  if (!expiryDateIso) return null
  const expiryDate = toExpiryDate(expiryDateIso)
  if (!expiryDate) return null

  const diffMs = expiryDate.getTime() - now.getTime()
  const rawDaysRemaining = Math.ceil(diffMs / ONE_DAY_MS)
  const daysRemaining = isSameLocalDate(expiryDate, now) ? 0 : rawDaysRemaining

  if (daysRemaining < 0 || daysRemaining > 7) {
    return null
  }

  const bannerText = getBannerText(daysRemaining)
  return {
    daysRemaining,
    bannerText,
    notificationTitle: 'DOT - Recordatorio de suscripción',
    notificationBody: bannerText,
  }
}
