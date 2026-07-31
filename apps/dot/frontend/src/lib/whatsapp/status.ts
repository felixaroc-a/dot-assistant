import type { WhatsAppChannelStatus } from '@/lib/api/whatsapp'

/**
 * Determina cuándo el backend reporta que ya se mostró el QR y parece haber
 * una sesión activa aunque todavía no se marcó `linked: true`.
 */
export function isPendingVerificationStatus(status: WhatsAppChannelStatus): boolean {
  return (
    status.status === 'connecting' &&
    !status.linked &&
    !status.reconnect_required &&
    !status.error &&
    Boolean(status.last_qr_at)
  )
}
