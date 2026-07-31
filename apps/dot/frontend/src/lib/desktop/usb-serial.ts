import { translateErrorMessage } from '@/lib/error-messages'

export type UsbSerialResult = {
  serial: string | null
  devices: string[]
  error?: string
}

function mapGateError(status: {
  reason?: string
  error?: string
  serial?: string | null
}): string {
  if (status.reason === 'multiple_usb') {
    return 'Hay varios USB conectados. Deja solo la llave DOT y reintenta.'
  }
  if (status.reason === 'vault_missing') {
    return 'USB detectado pero no está preparado para DOT. Ejecuta el asistente de provisión USB.'
  }
  if (status.reason === 'vault_invalid' || status.reason === 'no_valid_vault') {
    return 'Se detectó USB, pero no una llave DOT válida. Usa el pendrive provisionado del cliente.'
  }
  if (status.reason === 'drive_unresolved') {
    return 'USB detectado, pero Windows no pudo montar su unidad. Reconéctalo e intenta de nuevo.'
  }
  return translateErrorMessage(
    status.error ||
      'Conecta tu llave DOT (pendrive USB) e intenta de nuevo.',
    'Conecta tu llave DOT (pendrive USB) e intenta de nuevo.',
  )
}

/** Lee el serial del pendrive en la PC (Electron). En web devuelve error controlado. */
export async function readLocalUsbSerial(hint?: string): Promise<UsbSerialResult> {
  const api = window.desktop?.usbSerial
  if (!api?.get) {
    return {
      serial: null,
      devices: [],
      error: 'La detección de pendrive solo está disponible en la app de escritorio DOT.',
    }
  }
  return api.get(hint)
}

/**
 * Lista todos los seriales USB detectados en el sistema.
 * No selecciona uno; solo enumera los disponibles para que el usuario
 * pueda elegir o la UI pueda mostrar opciones.
 * @returns {Promise<string[]>}
 */
export async function listUsbSerials(): Promise<string[]> {
  const api = window.desktop?.usbSerial
  if (!api?.get) {
    return []
  }
  try {
    const result = await api.get()
    return result.devices || []
  } catch {
    return []
  }
}

/**
 * Lee el serial del USB solo si cumple la validación del gate (vault OK).
 * Devuelve errores de negocio más claros para UI.
 */
export async function readReadyDotUsbSerial(): Promise<UsbSerialResult> {
  const api = window.desktop?.usbSerial
  if (!api?.get) {
    return {
      serial: null,
      devices: [],
      error: 'La detección de pendrive solo está disponible en la app de escritorio DOT.',
    }
  }

  if (!api.isPresent) {
    return api.get()
  }

  const status = await api.isPresent()
  if (status.present && status.serial) {
    return { serial: status.serial, devices: status.serial ? [status.serial] : [] }
  }

  if (status.serial) {
    return {
      serial: null,
      devices: [status.serial],
      error: mapGateError(status),
    }
  }

  const fallback = await api.get()
  if (!fallback.serial) {
    return {
      ...fallback,
      error: fallback.error || mapGateError(status),
    }
  }
  return fallback
}
