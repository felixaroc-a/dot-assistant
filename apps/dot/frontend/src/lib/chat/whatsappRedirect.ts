/**
 * Detección de keywords para redirección a WhatsApp (A07).
 *
 * Reglas robustas para evitar false positives como "qué es un teléfono".
 * Solo redirige cuando hay intención clara de acción, no preguntas informativas.
 */

import { normalize } from './textNormalize'

/** Patrones de pregunta que NUNCA deben redirigir */
const QUESTION_PATTERNS = [
  /\bqu[ée]\s+es\b/i,
  /\bqu[ée]\s+significa\b/i,
  /\bdefinici[oó]n\s+de\b/i,
  /\bcomo\s+funciona\b/i,
  /\bpara\s+qu[ée]\s+sirve\b/i,
  /\bexplicame\b/i,
  /\bc[uú]al\s+es\b/i,
]

/** Grupo 1: Alta intención — verbos de acción explícitos + canal */
const EXPLICIT_SEND_PATTERNS = [
  /env[ií]a(?:lo|me|le|nos|las|los)?\s*(?:por|a\s*(?:mi|el|l[aao]s?)\s*)?(?:whatsapp|whats|wa|ws|tel[ée]fono|celular|m[oó]vil|movil)/i,
  /m[aá]nda(?:lo|me|le|nos|las|los)?\s*(?:por|a\s*(?:mi|el|l[aao]s?)\s*)?(?:whatsapp|whats|wa|ws|tel[ée]fono|celular|m[oó]vil|movil)/i,
  /reenv[ií]a(?:lo|me|le|nos|las|los)?\s*(?:por|a\s*(?:mi|el|l[aao]s?)\s*)?(?:whatsapp|whats|wa|ws|tel[ée]fono|celular|m[oó]vil|movil)/i,
  /p[aá]sa(?:lo|me|le|nos|las|los)?\s*(?:por|a\s*(?:mi|el|l[aao]s?)\s*)?(?:whatsapp|whats|wa|ws|tel[ée]fono|celular|m[oó]vil|movil)/i,
  /(?:env[ií]a|m[aá]nda|reenv[ií]a|p[aá]sa)\s*(?:un\s+)?(?:whatsapp|whats|mensaje\s+de\s+texto|sms)/i,
]

/** Grupo 2: Referencia directa a plataforma de mensajería con acción */
const PLATFORM_ACTION_PATTERNS = [
  /(?:av[ií]same|notif[ií]came|escr[ií]beme|cont[eá]ctame|resp[oó]ndeme)\s*(?:por|v[ií]a|en)\s*(?:whatsapp|whats|wa|ws|tel[ée]fono|celular|m[oó]vil|movil)/i,
  /(?:comun[ií]cate|h[aá]blame)\s*(?:por|v[ií]a)\s*(?:whatsapp|whats|wa|ws|tel[ée]fono|celular|m[oó]vil|movil)/i,
  /(?:a\s*(?:mi|el)\s*)?(?:whatsapp|whats)\s*(?:por\s*favor|ya|ahora|pls)/i,
  /ll[aá]mame\s*(?:al|por|a\s*mi)\s*(?:tel[ée]fono|celular|m[oó]vil|movil|whatsapp|whats|wa)/i,
]

/** Grupo 3: Referencia al dispositivo propio con verbo */
const DEVICE_ACTION_PATTERNS = [
  /(?:env[ií]a|m[aá]nda|reenv[ií]a|p[aá]sa|ll[eé]va)lo\s*a\s*(?:mi|el)\s*(?:tel[ée]fono|celular|m[oó]vil|movil)/i,
  /(?:env[ií]a|m[aá]nda|reenv[ií]a|p[aá]sa)me\s*(?:esto|lo|la)\s*a\s*(?:mi|el)\s*(?:tel[ée]fono|celular|m[oó]vil|movil)/i,
  /(?:env[ií]a|m[aá]nda)me\s*(?:un\s+)?(?:whatsapp|whats|mensaje|sms|mensaje\s+de\s+texto)/i,
]

/** Grupo 4: "mi número" + acción (fuerte señal de intención de contacto) */
const MY_NUMBER_PATTERNS = [
  /(?:m[ií]|mi)\s+n[uú]mero/i,
  /a\s*(?:mi|el)\s*(?:tel[ée]fono|celular|m[oó]vil|movil)/i,
]

/**
 * Determina si el texto del usuario debe redirigirse a WhatsApp.
 * Retorna `true` solo si hay intención clara de acción, no si es una pregunta.
 */
export function shouldRedirectToWhatsApp(text: string): boolean {
  const normalized = normalize(text).trim()
  if (!normalized) return false

  // Si es una pregunta informativa, NUNCA redirigir
  if (QUESTION_PATTERNS.some((p) => p.test(normalized))) {
    return false
  }

  // Grupo 1: verbos explícitos de envío (más fuerte)
  if (EXPLICIT_SEND_PATTERNS.some((p) => p.test(normalized))) {
    return true
  }

  // Grupo 2: acción de contacto por plataforma
  if (PLATFORM_ACTION_PATTERNS.some((p) => p.test(normalized))) {
    return true
  }

  // Grupo 3: acción hacia dispositivo propio
  if (DEVICE_ACTION_PATTERNS.some((p) => p.test(normalized))) {
    return true
  }

  // Grupo 4: "mi número" — señal fuerte de intención
  if (MY_NUMBER_PATTERNS.some((p) => p.test(normalized))) {
    return true
  }

  return false
}

/**
 * Detecta si el texto solicita explícitamente enviar un WhatsApp
 * (para mostrar feedback visual antes de enviar).
 */
export function hasWhatsAppIntent(text: string): boolean {
  const normalized = normalize(text).trim()
  if (!normalized) return false
  if (QUESTION_PATTERNS.some((p) => p.test(normalized))) return false

  // Señales rápidas de intención WhatsApp
  const quickPatterns = [
    /whatsapp/i, /whats/i, /\bwa\b/i, /\bws\b/i,
    /tel[ée]fono/i, /celular/i, /m[oó]vil/i, /movil/i,
    /ll[aá]mame/i, /mensaje\s+de\s+texto/i, /\bsms\b/i,
    /m[ií]\s+n[uú]mero/i,
  ]
  return quickPatterns.some((p) => p.test(normalized))
}
