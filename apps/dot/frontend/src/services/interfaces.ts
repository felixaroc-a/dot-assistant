import type { GoogleOAuthRevokeResponse, GoogleOAuthStartResponse, GoogleOAuthStatusResponse } from '@/lib/api/google-oauth'
import type { UserProfileDto, UserProfilePatch } from '@/lib/api/user-profile'
import type { WhatsAppChannelEventInput, WhatsAppChannelStatus, WhatsAppLinkStatus } from '@/lib/api/whatsapp'

// ──────────────────────────────────────────────────
// Interfaces de Servicios (Puertos para la UI)
// ──────────────────────────────────────────────────

export interface IAuthService {
  login(cedula: string, password: string, hardwareSerial?: string | null): Promise<{
    access_token: string
    refresh_token: string
    cliente: {
      cliente_id: string
      cedula: string
      plan: string
      fecha_vencimiento: string
      correo: string
    }
  }>
  refresh(refreshToken: string): Promise<{ access_token: string; refresh_token: string }>
  logout(accessToken: string, refreshToken?: string): Promise<void>
  recoveryLogin(cedula: string, password: string, recoveryKey: string): Promise<{
    access_token: string
    refresh_token: string
    cliente: {
      cliente_id: string
      cedula: string
      plan: string
      fecha_vencimiento: string
      correo: string
    }
  }>
}

export interface IProfileService {
  get(getAccessToken: () => Promise<string | null>): Promise<UserProfileDto>
  patch(data: UserProfilePatch, getAccessToken: () => Promise<string | null>): Promise<UserProfileDto>
}

export interface IAutomationService {
  execute(id: string, getAccessToken: () => Promise<string | null>): Promise<{ success: boolean; result: string; executed_at: string }>
  getPendingResults(getAccessToken: () => Promise<string | null>): Promise<{ has_new: boolean }>
  ackResults(getAccessToken: () => Promise<string | null>): Promise<void>
  getHistory(id: string, getAccessToken: () => Promise<string | null>): Promise<unknown[]>
}

export interface IWhatsAppService {
  getStatus(getAccessToken: () => Promise<string | null>): Promise<WhatsAppChannelStatus>
  updateStatus(input: { linked: boolean; phone_number?: string | null; channel_name?: string | null; error?: string | null }, getAccessToken: () => Promise<string | null>): Promise<WhatsAppChannelStatus>
  sendEvent(input: WhatsAppChannelEventInput, getAccessToken: () => Promise<string | null>): Promise<WhatsAppChannelStatus>
  reconnect(getAccessToken: () => Promise<string | null>): Promise<WhatsAppChannelStatus>
  toLinkStatus(status: WhatsAppChannelStatus): WhatsAppLinkStatus
}

export interface IGoogleOAuthService {
  start(params: { bearerAccessToken: string | null; integrations?: readonly string[] }): Promise<GoogleOAuthStartResponse>
  getStatus(bearerAccessToken: string | null): Promise<GoogleOAuthStatusResponse>
  revoke(getAccessToken: () => Promise<string | null>): Promise<GoogleOAuthRevokeResponse>
}

export interface IDocumentService {
  generate(params: { document_type: string; title: string; content: string; folder?: string }, getAccessToken: () => Promise<string | null>): Promise<{ filename: string; path: string }>
}
