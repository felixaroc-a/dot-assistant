/** Patrones estrictos: evitan falsos positivos con palabras sueltas como "linked" o "registered". */
export const LINKED_SIGNAL_PATTERNS = [
  /\[DOT\]\s*WhatsApp\s+vinculado/i,
  /\bwhatsapp\b[\s\S]{0,80}\bsession\s+active\b/i,
  /\bwhatsapp\b[\s\S]{0,80}\blogin\s+successful\b/i,
  /\bwhatsapp\b[\s\S]{0,80}\bauthenticated\s+successfully\b/i,
  /\bwhatsapp\b[\s\S]{0,80}\bpairing\s+success(?:ful)?\b/i,
  /\bwhatsapp\b[\s\S]{0,80}\bpairing\s+complete\b/i,
  /\bwhatsapp\b[\s\S]{0,80}\bdevice\s+linked\b/i,
  /\bwhatsapp\b[\s\S]{0,120}\bconnection\s*[:=]\s*['"]?open['"]?/i,
  /\bwhatsapp\b[\s\S]{0,120}\bstate\s*[:=]\s*['"]?open['"]?/i,
  /dispositivo\s+vinculado/i,
  /\bwhatsapp\s+connected\b/i,
  /\bwhatsapp\b[\s\S]{0,80}\bconnected\b/i,
  /\bwhatsapp\s+web\s+connected\b/i,
  /\blinked!\s*credentials\s+saved\b/i,
  /\bcredentials\s+saved\s+for\s+future\s+sends\b/i,
  /\blocal\s+login\s+saved\s+auth\s+for\s+whatsapp\b/i,
  /\bwhatsapp\b[\s\S]{0,80}\bready\s+to\s+receive\b/i,
  /\bwhatsapp\b[\s\S]{0,80}\bconnected\s+successfully\b/i,
  /\bwhatsapp\b[\s\S]{0,80}\bqr\s+(?:code\s+)?scanned\b/i,
  /\bwhatsapp\b[\s\S]{0,80}\blogged\s+in\b/i,
  /\bchannel\s+whatsapp\b[\s\S]{0,80}\b(?:ready|connected|online)\b/i,
] as const

export function hasLinkedSignal(rawLog: string): boolean {
  return LINKED_SIGNAL_PATTERNS.some((pattern) => pattern.test(rawLog))
}

export function hasDisconnectedSignal(rawLog: string): boolean {
  return /(disconnected|connection\s+closed|session\s+expired|logged\s+out|desconectad|reconnect\s+required)/i.test(
    rawLog,
  )
}

/** Oculta nombres internos del motor de vinculación en mensajes visibles al usuario. */
export { sanitizeWhatsAppUserError } from '@/lib/error-messages'

/** Bridge IPC de escritorio (Baileys por defecto; alias legacy openclaw). */
export function getDesktopWhatsAppBridge() {
  if (typeof window === 'undefined') return undefined
  return window.desktop?.whatsapp ?? window.desktop?.openclaw
}

/**
 * Escucha el evento estructurado de vinculación emitido por Electron
 * cuando el transporte WhatsApp confirma sesión activa.
 *
 * @param callback - Función que recibe `{ linked: true, phone_number?: string }`
 * @returns Función para cancelar la suscripción
 */
export function onWhatsAppLinked(
  callback: (data: { linked: boolean; phone_number?: string }) => void,
): () => void {
  const unsubscribe = getDesktopWhatsAppBridge()?.onLinked?.(callback)
  return unsubscribe ?? (() => {})
}
