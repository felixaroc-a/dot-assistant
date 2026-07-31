import { apiFetchJson } from '@/lib/api/http'
import type {
  AiCredentialsDto,
  AiCredentialsPatch,
  SavedAutomationDto,
  UserProfileDto,
  UserProfilePatch,
} from '@/lib/api/types'

export type {
  AiCredentialsDto,
  AiCredentialsPatch,
  SavedAutomationDto,
  UserProfileDto,
  UserProfilePatch,
}

export async function patchUserProfile(
  accessToken: string,
  body: UserProfilePatch,
): Promise<UserProfileDto> {
  return apiFetchJson<UserProfileDto>(
    '/users/me/profile',
    { method: 'PATCH', body: JSON.stringify(body) },
    accessToken,
  )
}

export async function fetchUserProfile(accessToken: string): Promise<UserProfileDto> {
  return apiFetchJson<UserProfileDto>('/users/me/profile', { method: 'GET' }, accessToken)
}
