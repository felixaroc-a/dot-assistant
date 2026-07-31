/** Utilidades JWT en el renderer (solo claims no sensibles como exp). */

export function readJwtExpMs(token: string): number | null {
  try {
    const [, payloadB64] = token.split('.')
    if (!payloadB64) return null
    const normalized = payloadB64.replace(/-/g, '+').replace(/_/g, '/')
    const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4)
    const json = JSON.parse(atob(padded)) as { exp?: number }
    return typeof json.exp === 'number' ? json.exp * 1000 : null
  } catch {
    return null
  }
}

export function readJwtHardwareRequired(token: string): boolean | null {
  try {
    const [, payloadB64] = token.split('.')
    if (!payloadB64) return null
    const normalized = payloadB64.replace(/-/g, '+').replace(/_/g, '/')
    const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4)
    const json = JSON.parse(atob(padded)) as { hardware_required?: boolean }
    return json.hardware_required ?? null
  } catch {
    return null
  }
}
