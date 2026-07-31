import { describe, expect, it } from 'vitest'

import type {
  AiCredentialsDto,
  SavedAutomationDto,
  UserProfileDto,
  UserProfilePatch,
} from '@/lib/api/user-profile'

const PROFILE_DTO_KEYS: (keyof UserProfileDto)[] = [
  'display_name',
  'channel_id',
  'ai_provider_id',
  'ai_credentials',
  'integrations',
  'automation_summary',
  'onboarding_completed',
  'saved_automations',
  'pending_automation_results',
]

const PROFILE_PATCH_KEYS: (keyof UserProfilePatch)[] = [
  'display_name',
  'channel_id',
  'ai_provider_id',
  'ai_credentials',
  'integrations',
  'automation_summary',
  'onboarding_completed',
  'saved_automations',
]

function sampleProfile(): UserProfileDto {
  const automation: SavedAutomationDto = {
    id: 'auto-1',
    name: 'Inbox',
    integration_id: 'gmail',
    instruction: 'Revisar correo',
    active: true,
    output_type: 'chat',
  }
  const aiCredentials: AiCredentialsDto = {
    provider_id: 'deepseek',
    username: 'ana',
    has_password: true,
  }
  return {
    display_name: 'Ana',
    channel_id: 'ch-1',
    ai_provider_id: 'deepseek',
    ai_credentials: aiCredentials,
    integrations: ['gmail'],
    automation_summary: null,
    onboarding_completed: true,
    saved_automations: [automation],
    pending_automation_results: { has_new: false },
  }
}

describe('UserProfileDto shape', () => {
  it('incluye todas las claves del contrato GET /users/me/profile', () => {
    const profile = sampleProfile()
    for (const key of PROFILE_DTO_KEYS) {
      expect(Object.prototype.hasOwnProperty.call(profile, key)).toBe(true)
    }
  })

  it('usa integration_id y output_type en saved_automations (sin camelCase)', () => {
    const profile = sampleProfile()
    const auto = profile.saved_automations?.[0]
    expect(auto?.integration_id).toBe('gmail')
    expect(auto).not.toHaveProperty('integrationId')
    expect(auto).not.toHaveProperty('outputType')
  })

  it('UserProfilePatch acepta credenciales IA sin exponer password en respuesta', () => {
    const patch: UserProfilePatch = {
      display_name: 'Ana',
      ai_credentials: {
        provider_id: 'deepseek',
        username: 'ana',
        password: 'secreto',
      },
    }
    expect(PROFILE_PATCH_KEYS.some((k) => k in patch)).toBe(true)
    expect(patch.ai_credentials?.password).toBe('secreto')
    const profile = sampleProfile()
    expect(profile.ai_credentials?.has_password).toBe(true)
    expect(profile.ai_credentials).not.toHaveProperty('password')
  })
})
