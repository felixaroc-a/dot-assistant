/**
 * Sistema de notificaciones de escritorio para DOT.
 * Usa la Notification API del navegador/Electron.
 */

export type ScheduledNotification = {
  id: string
  title: string
  body: string
  scheduledAt: Date
  timeoutId: ReturnType<typeof setTimeout>
}

const activeTimers = new Map<string, ScheduledNotification>()

/**
 * Solicita permiso para mostrar notificaciones de escritorio.
 * Retorna true si ya está concedido o se concede ahora.
 */
export async function requestNotificationPermission(): Promise<boolean> {
  if (!('Notification' in window)) {
    console.warn('[notifications] Notification API no disponible en este entorno.')
    return false
  }

  if (Notification.permission === 'granted') return true
  if (Notification.permission === 'denied') {
    console.warn('[notifications] Permiso de notificaciones denegado.')
    return false
  }

  const permission = await Notification.requestPermission()
  return permission === 'granted'
}

/**
 * Muestra una notificación de escritorio inmediatamente.
 * - Si no hay permiso, lo solicita.
 * - En Electron, usa el API nativa del sistema.
 */
export async function showNotification(
  title: string,
  body: string,
): Promise<void> {
  const hasPermission = await requestNotificationPermission()
  if (!hasPermission) {
    console.warn('[notifications] Sin permiso para mostrar notificaciones.')
    return
  }

  try {
    const n = new Notification(title, {
      body,
      icon: '/assets/dot-icon.png',
      silent: false,
    })

    n.addEventListener('click', () => {
      window.focus()
      n.close()
    })

    // Auto-cierre después de 8 segundos
    setTimeout(() => n.close(), 8000)
  } catch (e) {
    console.error('[notifications] Error al mostrar notificación:', e)
  }
}

/**
 * Programa una notificación para el futuro.
 *
 * @param title - Título de la notificación
 * @param body - Cuerpo del mensaje
 * @param delayMs - Milisegundos desde ahora hasta la notificación
 * @returns ID único del temporizador (para cancelación)
 */
export function scheduleNotification(
  title: string,
  body: string,
  delayMs: number,
): string {
  const id = crypto.randomUUID()

  if (delayMs < 0) {
    console.warn('[notifications] delayMs negativo, mostrando inmediatamente.')
    void showNotification(title, body)
    return id
  }

  // Mostrar feedback en consola si es una simulación sin permiso
  if (!('Notification' in window) || Notification.permission === 'denied') {
    console.log(
      `[notifications] RECORDATORIO SIMULADO: "${title}" — ${body} (en ${Math.round(delayMs / 1000 / 60)} min)`,
    )
  }

  const timeoutId = setTimeout(() => {
    void showNotification(title, body)
    activeTimers.delete(id)
  }, delayMs)

  const scheduledAt = new Date(Date.now() + delayMs)

  activeTimers.set(id, { id, title, body, scheduledAt, timeoutId })

  return id
}

/**
 * Programa una notificación a una hora específica del día (hoy o mañana si ya pasó).
 *
 * @param title - Título de la notificación
 * @param body - Cuerpo del mensaje
 * @param hours - Hora (0-23)
 * @param minutes - Minutos (0-59)
 * @returns ID único del temporizador
 */
export function scheduleNotificationAtTime(
  title: string,
  body: string,
  hours: number,
  minutes: number,
): string {
  const now = new Date()
  const target = new Date(now)
  target.setHours(hours, minutes, 0, 0)

  let delayMs = target.getTime() - now.getTime()
  if (delayMs <= 0) {
    // Si ya pasó, programar para mañana
    target.setDate(target.getDate() + 1)
    delayMs = target.getTime() - now.getTime()
  }

  return scheduleNotification(title, body, delayMs)
}

/**
 * Programa una notificación basada en un texto descriptivo.
 * Soporta formatos:
 *   - "en X minutos/horas" -> scheduleNotification
 *   - "a las HH:MM" -> scheduleNotificationAtTime
 *
 * @returns Objeto con el ID y un mensaje descriptivo, o null si no se pudo parsear.
 */
export function scheduleFromText(
  text: string,
  reminderTitle: string = 'DOT — Recordatorio',
): { id: string; message: string } | null {
  const lower = text.toLowerCase().trim()

  // Patrón: "en X minutos" o "en X horas"
  const enPattern = /^en\s+(\d+)\s*(minuto|minutos|min|min|hora|horas|h)\s*(.*)$/i
  const enMatch = lower.match(enPattern)
  if (enMatch) {
    const cantidad = parseInt(enMatch[1], 10)
    const unidad = enMatch[2].toLowerCase()
    const mensaje = enMatch[3].trim() || text

    const multiplier = unidad.startsWith('h') ? 60 * 60 * 1000 : 60 * 1000
    const delayMs = cantidad * multiplier

    const id = scheduleNotification(reminderTitle, mensaje, delayMs)
    const unidadLabel = unidad.startsWith('h') ? (cantidad === 1 ? 'hora' : 'horas') : 'minutos'
    return {
      id,
      message: `Recordatorio programado: «${mensaje}» en ${cantidad} ${unidadLabel}.`,
    }
  }

  // Patrón: "a las HH:MM"
  const atPattern = /^a\s+las\s+(\d{1,2}):(\d{2})\s*(.*)$/i
  const atMatch = lower.match(atPattern)
  if (atMatch) {
    const hours = parseInt(atMatch[1], 10)
    const minutes = parseInt(atMatch[2], 10)
    const mensaje = atMatch[3].trim() || text

    if (hours < 0 || hours > 23 || minutes < 0 || minutes > 59) {
      return null
    }

    const id = scheduleNotificationAtTime(reminderTitle, mensaje, hours, minutes)
    const horaStr = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`
    return {
      id,
      message: `Recordatorio programado: «${mensaje}» a las ${horaStr}.`,
    }
  }

  return null
}

/**
 * Cancela una notificación programada por su ID.
 */
export function cancelScheduledNotification(id: string): boolean {
  const entry = activeTimers.get(id)
  if (!entry) return false

  clearTimeout(entry.timeoutId)
  activeTimers.delete(id)
  return true
}

/**
 * Cancela todas las notificaciones programadas.
 */
export function cancelAllScheduledNotifications(): void {
  for (const [id, entry] of activeTimers) {
    clearTimeout(entry.timeoutId)
    activeTimers.delete(id)
  }
}
