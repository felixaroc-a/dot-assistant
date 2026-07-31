/**
 * Huella local del serial USB para enlazar la sesión al mismo pendrive del último login.
 * No usa HARDWARE_TOKEN_PEPPER del servidor (solo validación en login contra Postgres).
 *
 * C6: En producción, VITE_DOT_LOCAL_BIND_SECRET es obligatoria. Sin ella, el build
 * falla con un error claro. El secreto default de desarrollo no se filtra a producción.
 */

const DEV_DEFAULT = 'dot-local-bind-dev-only-change-in-prod-build'

const LOCAL_BIND_SECRET: string = (() => {
  const envValue = import.meta.env.VITE_DOT_LOCAL_BIND_SECRET?.trim()
  if (!envValue) {
    if (import.meta.env.PROD) {
      throw new Error(
        'VITE_DOT_LOCAL_BIND_SECRET no está definida en el build de producción. ' +
        'Establezca esta variable de entorno antes de compilar (npm run build / desktop:dist).'
      )
    }
    return DEV_DEFAULT
  }
  if (import.meta.env.PROD && envValue === DEV_DEFAULT) {
    throw new Error(
      'VITE_DOT_LOCAL_BIND_SECRET tiene el valor por defecto de desarrollo ' +
      'en un build de producción. Genere un secreto único antes de compilar.'
    )
  }
  return envValue
})()

function toHex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

/** SHA-256(serial + secreto local). Mismo formato hex que el backend (64 chars). */
export async function fingerprintHardwareSerial(serial: string): Promise<string> {
  const clean = serial.trim()
  if (!clean) throw new Error('Serial vacío')
  const payload = new TextEncoder().encode(`${clean}\x00${LOCAL_BIND_SECRET}`)
  const digest = await crypto.subtle.digest('SHA-256', payload)
  return toHex(digest)
}

export async function hardwareSerialMatchesFingerprint(
  serial: string | null | undefined,
  storedFingerprint: string | null | undefined,
): Promise<boolean> {
  if (!serial || !storedFingerprint) return false
  try {
    const fp = await fingerprintHardwareSerial(serial)
    return fp === storedFingerprint.toLowerCase()
  } catch {
    return false
  }
}
