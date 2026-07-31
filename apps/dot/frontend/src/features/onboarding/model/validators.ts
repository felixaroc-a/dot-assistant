import type { IntegrationId } from '@/features/integrations'
import type { ChannelId } from '@/features/onboarding/model/channel.types'

const VALID_CHANNEL_IDS = new Set<string>(['whatsapp'])
const VALID_INTEGRATION_IDS = new Set<string>(['gmail', 'google-calendar', 'third-option'])

export function isChannelId(value: string): value is ChannelId {
  return VALID_CHANNEL_IDS.has(value)
}

export function isIntegrationId(value: string): value is IntegrationId {
  return VALID_INTEGRATION_IDS.has(value)
}

export function filterIntegrationIds(values: string[]): IntegrationId[] {
  return values.filter(isIntegrationId)
}
