/**
 * Dominio compartido: tipos y catálogo de integraciones (Calendar, Gmail, etc.).
 * Consumido por onboarding y por el workspace (drawer de automatizaciones).
 */
export type { IntegrationId, IntegrationMeta } from './model/integration.meta'
export { INTEGRATION_META, getIntegrationById } from './model/integration.meta'
export { integrationIdsNeedGoogleOAuth } from './model/google-automation'
