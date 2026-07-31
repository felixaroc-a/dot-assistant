import { apiFetchJson } from '@/lib/api/http'
import type {
  LoginResponseDto,
  RefreshResponseDto,
  SuscripcionCliente,
} from '@/lib/api/types'

export type { LoginResponseDto, RefreshResponseDto, SuscripcionCliente }

export async function loginWithCedula(
  cedula: string,
  password: string,
  hardwareSerial?: string | null,
): Promise<LoginResponseDto> {
  const body: Record<string, string> = {
    cedula: cedula.trim(),
    password,
  }
  if (hardwareSerial?.trim()) {
    body.hardware_serial = hardwareSerial.trim()
  }
  return apiFetchJson<LoginResponseDto>(
    '/v1/auth/login',
    { method: 'POST', body: JSON.stringify(body) },
    null,
  )
}

export async function refreshAccessToken(refreshToken: string): Promise<RefreshResponseDto> {
  const body = { refresh_token: refreshToken }
  return apiFetchJson<RefreshResponseDto>(
    '/v1/auth/refresh',
    { method: 'POST', body: JSON.stringify(body) },
    null,
  )
}

export async function recoveryLogin(
  cedula: string,
  password: string,
  recoveryKey: string,
): Promise<LoginResponseDto> {
  return apiFetchJson<LoginResponseDto>(
    '/v1/pendrive/recovery-login',
    {
      method: 'POST',
      body: JSON.stringify({
        cedula: cedula.trim(),
        password,
        recovery_key: recoveryKey.trim(),
      }),
    },
    null,
  )
}

export async function linkNewPendrive(serial: string, bearerToken: string): Promise<void> {
  await apiFetchJson<{ ok: boolean }>(
    '/v1/pendrive/link',
    {
      method: 'POST',
      body: JSON.stringify({ serial: serial.trim() }),
    },
    bearerToken,
  )
}

export async function logoutOnServer(accessToken: string, refreshToken?: string): Promise<void> {
  const body = refreshToken ? { refresh_token: refreshToken } : {}
  await apiFetchJson<void>(
    '/v1/auth/logout',
    { method: 'POST', body: JSON.stringify(body) },
    accessToken,
  )
}
