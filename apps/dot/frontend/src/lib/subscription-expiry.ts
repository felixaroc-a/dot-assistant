/** Alineado con backend: `today > fecha_vencimiento` usando fecha calendario UTC. */

const ISO_DATE_ONLY_RE = /^(\d{4})-(\d{2})-(\d{2})$/

export type CalendarDate = { year: number; month: number; day: number }

export function parseFechaVencimiento(raw: string): CalendarDate | null {
  const value = raw.trim()
  const match = ISO_DATE_ONLY_RE.exec(value)
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) {
    return null
  }
  if (month < 1 || month > 12 || day < 1 || day > 31) return null
  return { year, month, day }
}

export function utcCalendarDate(ref: Date = new Date()): CalendarDate {
  return {
    year: ref.getUTCFullYear(),
    month: ref.getUTCMonth() + 1,
    day: ref.getUTCDate(),
  }
}

function compareCalendarDates(left: CalendarDate, right: CalendarDate): number {
  if (left.year !== right.year) return left.year - right.year
  if (left.month !== right.month) return left.month - right.month
  return left.day - right.day
}

/**
 * Suscripción vencida si la fecha UTC de hoy es posterior a `fecha_vencimiento`
 * (el día de vencimiento sigue activo, igual que en el backend).
 */
export function isSubscriptionExpired(
  fechaVencimiento: string,
  refDate: Date = new Date(),
): boolean {
  const expiry = parseFechaVencimiento(fechaVencimiento)
  if (!expiry) return false
  return compareCalendarDates(utcCalendarDate(refDate), expiry) > 0
}
