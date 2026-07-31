/** Umbrales y copy visible al usuario para el pool unificado de IA ($7.50/mes). */

export const USAGE_WARNING_THRESHOLD_PERCENT = 80

/** Aviso al acercarse al límite (≥80% consumido). */
export const USAGE_WARNING_MESSAGE =
  'Te queda poco saldo de IA este mes. Recarga en tu tienda Nordik-IA más cercana cuando lo necesites.'

/** Bloqueo total al 100% — chat, visión, imágenes y herramientas IA. */
export const USAGE_LIMIT_BLOCKED_TITLE = 'Límite de IA alcanzado'

/** Copy corto para APIs, placeholders y errores 402. */
export const USAGE_LIMIT_BLOCKED_MESSAGE =
  'Has alcanzado tu límite de IA de este mes. Visita tu tienda Nordik-IA más cercana para recargar.'

/** Intro visible en guía guiada de recarga (D25 light). */
export const USAGE_RECHARGE_INTRO =
  'Tu saldo de IA de este mes se agotó. Chat, visión, imágenes y herramientas IA están pausados hasta que recargues.'

/** Pasos guiados para recargar en punto de venta físico. */
export const USAGE_RECHARGE_STEPS = [
  'Ubica un punto de venta Nordik-IA autorizado (pregunta en tu tienda habitual o donde compraste el pendrive).',
  'Lleva tu pendrive DOT y tu cédula de identidad.',
  'Pide una recarga de IA al servicio técnico o vendedor autorizado.',
  'Vuelve a abrir DOT e inicia sesión; tu saldo se actualizará al reconectar.',
] as const

/** Qué llevar a la tienda. */
export const USAGE_RECHARGE_BRING_ITEMS = ['Pendrive DOT', 'Cédula de identidad'] as const

/** Sin mapa fake: honesto hasta existir datos de tiendas en backend. */
export const USAGE_STORE_LOCATOR_HINT =
  'Por ahora no hay mapa de tiendas en DOT. Pregunta en tu punto de venta Nordik-IA habitual.'

export function usageRemainingPercent(consumedPercent: number): number {
  return Math.max(0, 100 - Math.min(100, consumedPercent))
}
