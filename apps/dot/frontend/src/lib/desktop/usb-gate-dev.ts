/**
 * [DEV] Bypass de puerta USB y modo demo.
 *
 * C8: Solo activo en desarrollo. En producción y tests, la puerta USB
 * se respeta siempre. Si este archivo se importa por error en un build
 * de producción, la verificación de entorno impide el bypass.
 *
 * El bypass se activa únicamente si VITE_DOT_SKIP_USB_GATE=1 está
 * definida Y el entorno NO es producción (VITE build).
 *
 * E05: Modo Demo. DOT_DEMO_MODE=1 permite usar la app sin pendrive
 * solo en desarrollo (nunca en producción empaquetada).
 */

export async function isUsbGateSkipped(): Promise<boolean> {
  // En producción (build con vite build), NUNCA saltar la puerta USB.
  if (import.meta.env.PROD) {
    return false
  }
  // En desarrollo: skip explícito O modo demo (desktop:no-usb).
  const skip =
    import.meta.env.VITE_DOT_SKIP_USB_GATE?.toString().trim() === '1'
  const demo =
    import.meta.env.VITE_DOT_DEMO_MODE?.toString().trim() === '1'
  return skip || demo
}

/**
 * E05: Detecta si DOT está en modo demo (sin verificación de pendrive).
 * Solo aplica en desarrollo. En producción, siempre retorna false.
 */
export async function isDemoMode(): Promise<boolean> {
  if (import.meta.env.PROD) return false
  return import.meta.env.VITE_DOT_DEMO_MODE?.toString().trim() === '1'
}
