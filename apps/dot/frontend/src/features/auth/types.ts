import type { SuscripcionCliente } from '@/lib/api/auth-login'

export type ProductSession = {
  accessToken: string
  refreshToken: string
  cliente: SuscripcionCliente
  /** ms epoch; null si no se pudo leer exp del JWT */
  expiresAtMs: number | null
  /** false si el JWT fue emitido via recovery key (sin exigencia de pendrive) */
  hardwareRequired: boolean | null
  /** Recovery key del usuario, para ofrecer guardado local */
  recoveryKey?: string
}

export type AuthContextValue = {
  /** Sesion producto DOT via JWT (Postgres/auto-venta1). */
  session: ProductSession | null
  /** Restauracion inicial de sesion desde almacenamiento seguro (no incluye login). */
  loading: boolean
  /** Error al restaurar sesion guardada; null si no hubo fallo. */
  sessionRestoreError: string | null
  getAccessToken: () => Promise<string | null>
  login: (cedula: string, password: string, hardwareSerial?: string | null) => Promise<void>
  recoveryLogin: (cedula: string, password: string, recoveryKey: string) => Promise<void>
  logout: () => void
  /** Indica si la suscripción del usuario ha vencido. */
  isSubscriptionExpired: boolean
  /** Fecha de vencimiento de la suscripción en formato ISO o null. */
  subscriptionExpiryDate: string | null
}
