import type { GetAccessToken } from '@/lib/api/client'
import { apiClient } from '@/lib/api/client'
import * as authLogin from '@/lib/api/auth-login'
import * as googleOAuth from '@/lib/api/google-oauth'
import * as userProfile from '@/lib/api/user-profile'
import * as whatsapp from '@/lib/api/whatsapp'
import type { GenerateDocumentType } from '@/lib/api/documents'

import type { IAuthService, IAutomationService, IDocumentService, IGoogleOAuthService, IProfileService, IWhatsAppService } from './interfaces'

async function resolveToken(getAccessToken: GetAccessToken): Promise<string | null> {
  try {
    return await getAccessToken()
  } catch {
    return null
  }
}

export const authService: IAuthService = {
  login: async (cedula, password, hardwareSerial) => {
    const res = await authLogin.loginWithCedula(cedula, password, hardwareSerial)
    return {
      access_token: res.access_token,
      refresh_token: res.refresh_token,
      cliente: {
        cliente_id: res.cliente.cliente_id,
        cedula: res.cliente.cedula,
        plan: res.cliente.plan,
        fecha_vencimiento: res.cliente.fecha_vencimiento,
        correo: res.cliente.correo ?? '',
      },
    }
  },

  refresh: async (refreshToken) => {
    const res = await authLogin.refreshAccessToken(refreshToken)
    return { access_token: res.access_token, refresh_token: res.refresh_token }
  },

  logout: (accessToken, refreshToken) =>
    authLogin.logoutOnServer(accessToken, refreshToken),

  recoveryLogin: async (cedula, password, recoveryKey) => {
    const res = await authLogin.recoveryLogin(cedula, password, recoveryKey)
    return {
      access_token: res.access_token,
      refresh_token: res.refresh_token,
      cliente: {
        cliente_id: res.cliente.cliente_id,
        cedula: res.cliente.cedula,
        plan: res.cliente.plan,
        fecha_vencimiento: res.cliente.fecha_vencimiento,
        correo: res.cliente.correo ?? '',
      },
    }
  },
}

export const profileService: IProfileService = {
  get: async (getAccessToken) => {
    const token = await resolveToken(getAccessToken)
    return userProfile.fetchUserProfile(token ?? '')
  },

  patch: async (data, getAccessToken) => {
    const token = await resolveToken(getAccessToken)
    return userProfile.patchUserProfile(token ?? '', data)
  },
}

export const automationService: IAutomationService = {
  execute: (id, getAccessToken) =>
    apiClient.post<{ success: boolean; result: string; executed_at: string }>(
      `/v1/automations/${id}/execute`,
      undefined,
      getAccessToken,
    ),

  getPendingResults: (getAccessToken) =>
    apiClient.get<{ has_new: boolean }>(
      '/v1/automations/results/pending',
      getAccessToken,
    ),

  ackResults: (getAccessToken) =>
    apiClient.post<void>('/v1/automations/results/ack', undefined, getAccessToken),

  getHistory: (id, getAccessToken) =>
    apiClient.get<unknown[]>(`/v1/automations/${id}/history`, getAccessToken),
}

export const whatsAppService: IWhatsAppService = {
  getStatus: (getAccessToken) =>
    whatsapp.getWhatsAppChannelStatus(getAccessToken),

  updateStatus: (input, getAccessToken) =>
    whatsapp.updateWhatsAppChannelStatus(input, getAccessToken),

  sendEvent: (input, getAccessToken) =>
    whatsapp.sendWhatsAppChannelEvent(input, getAccessToken),

  reconnect: (getAccessToken) =>
    whatsapp.requestWhatsAppReconnect(getAccessToken),

  toLinkStatus: (status) => whatsapp.toLinkStatus(status),
}

export const googleOAuthService: IGoogleOAuthService = {
  start: (params) =>
    googleOAuth.requestGoogleOAuthStart({
      bearerAccessToken: params.bearerAccessToken,
      integrations: params.integrations,
    }),

  getStatus: (bearerAccessToken) =>
    googleOAuth.getGoogleOAuthStatus(bearerAccessToken),

  revoke: (getAccessToken) =>
    googleOAuth.revokeGoogleOAuth(getAccessToken),
}

export const documentService: IDocumentService = {
  generate: async (params, getAccessToken) => {
    const { generateDocument } = await import('@/lib/api/documents')
    return generateDocument(
      {
        document_type: params.document_type as GenerateDocumentType,
        title: params.title,
        content: params.content,
        folder: params.folder,
      },
      getAccessToken,
    )
  },
}
