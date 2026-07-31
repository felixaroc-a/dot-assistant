import { apiFetchAuthed } from '@/lib/api/client'
import type { GetAccessToken } from '@/lib/api/client'
import { isPendingVerificationStatus } from '@/lib/whatsapp/status'

/** Tipos para la API de estado del canal WhatsApp del cliente DOT. */
export type WhatsAppChannelLifecycle = 'disconnected' | 'connecting' | 'linked'
export type WhatsAppLinkStatus = WhatsAppChannelLifecycle | 'pending_verification'

export type WhatsAppChannelEventName =
  | 'connecting'
  | 'qr_ready'
  | 'linked'
  | 'heartbeat'
  | 'disconnected'
  | 'error'
  | 'reconnecting'

export interface WhatsAppChannelStatus {
  status: WhatsAppChannelLifecycle
  linked: boolean
  phone_number: string | null
  channel_name: string | null
  last_linked_at: string | null
  last_disconnected_at: string | null
  last_qr_at: string | null
  last_heartbeat_at: string | null
  last_error_at: string | null
  reconnect_required: boolean
  reconnect_attempts: number
  error: string | null
}

export interface UpdateWhatsAppChannelStatusInput {
  linked: boolean
  phone_number?: string | null
  channel_name?: string | null
  error?: string | null
  source?: string
}

export interface WhatsAppChannelEventInput {
  event: WhatsAppChannelEventName
  phone_number?: string | null
  channel_name?: string | null
  error?: string | null
  source?: string
}

export function toLinkStatus(status: WhatsAppChannelStatus): WhatsAppLinkStatus {
  // Durante reconexión silenciosa el backend conserva linked=true pero status=connecting.
  if (status.status === 'connecting') return 'connecting'
  if (status.status === 'linked') return 'linked'
  if (isPendingVerificationStatus(status)) return 'pending_verification'
  if (status.reconnect_required && status.error) return 'connecting'
  return 'disconnected'
}

export async function getWhatsAppChannelStatus(
  getAccessToken: GetAccessToken,
): Promise<WhatsAppChannelStatus> {
  return apiFetchAuthed<WhatsAppChannelStatus>(
    '/v1/whatsapp/channel/status',
    { method: 'GET' },
    getAccessToken,
  )
}

export async function updateWhatsAppChannelStatus(
  input: UpdateWhatsAppChannelStatusInput,
  getAccessToken: GetAccessToken,
): Promise<WhatsAppChannelStatus> {
  return apiFetchAuthed<WhatsAppChannelStatus>(
    '/v1/whatsapp/channel/status',
    {
      method: 'POST',
      body: JSON.stringify({
        linked: input.linked,
        phone_number: input.phone_number ?? null,
        channel_name: input.channel_name ?? null,
        error: input.error ?? null,
        source: input.source ?? 'dot-desktop',
      }),
    },
    getAccessToken,
  )
}

export async function sendWhatsAppChannelEvent(
  input: WhatsAppChannelEventInput,
  getAccessToken: GetAccessToken,
): Promise<WhatsAppChannelStatus> {
  return apiFetchAuthed<WhatsAppChannelStatus>(
    '/v1/whatsapp/channel/events',
    {
      method: 'POST',
      body: JSON.stringify({
        event: input.event,
        phone_number: input.phone_number ?? null,
        channel_name: input.channel_name ?? null,
        error: input.error ?? null,
        source: input.source ?? 'dot-desktop',
      }),
    },
    getAccessToken,
  )
}

export async function requestWhatsAppReconnect(
  getAccessToken: GetAccessToken,
): Promise<WhatsAppChannelStatus> {
  return apiFetchAuthed<WhatsAppChannelStatus>(
    '/v1/whatsapp/channel/reconnect',
    { method: 'POST' },
    getAccessToken,
  )
}

// ─── Mensajería outbound (A07) ────────────────────────────────────────────

export type SendWhatsAppOutboundInput = {
  to: string
  text: string
}

export type SendWhatsAppOutboundResult = {
  success: boolean
  message_id: string | null
  error: string | null
}

/**
 * Envía un mensaje saliente por WhatsApp usando el bridge local.
 * Requiere que el canal WhatsApp esté vinculado (`linked`).
 */
export async function sendWhatsAppOutbound(
  input: SendWhatsAppOutboundInput,
  getAccessToken: GetAccessToken,
): Promise<SendWhatsAppOutboundResult> {
  return apiFetchAuthed<SendWhatsAppOutboundResult>(
    '/v1/whatsapp/outbound',
    {
      method: 'POST',
      body: JSON.stringify({ to: input.to, text: input.text }),
    },
    getAccessToken,
  )
}

export type SendWhatsAppMediaInput = {
  path: string
  to?: string
  caption?: string
  media_type?: 'document' | 'image' | 'voice'
}

/**
 * Envía un archivo (documento, imagen o nota de voz) por WhatsApp vía bridge local.
 * Requiere canal WhatsApp vinculado.
 */
export async function sendWhatsAppMedia(
  input: SendWhatsAppMediaInput,
  getAccessToken: GetAccessToken,
): Promise<SendWhatsAppOutboundResult> {
  return apiFetchAuthed<SendWhatsAppOutboundResult>(
    '/v1/whatsapp/outbound/media',
    {
      method: 'POST',
      body: JSON.stringify({
        path: input.path,
        to: input.to,
        caption: input.caption ?? '',
        media_type: input.media_type ?? 'document',
      }),
    },
    getAccessToken,
  )
}
