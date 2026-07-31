import type { IntegrationId } from '@/features/integrations/model/integration.meta'

const GOOGLE_SCOPE_IDS = new Set<IntegrationId>(['google-calendar', 'gmail'])

/** Gmail y/o Calendar requieren OAuth Google (solo en flujo automatizaciones). */
export function integrationIdsNeedGoogleOAuth(ids: readonly IntegrationId[]): boolean {
  return ids.some((id) => GOOGLE_SCOPE_IDS.has(id))
}
