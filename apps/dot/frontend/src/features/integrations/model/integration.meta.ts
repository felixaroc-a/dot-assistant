// --- Inline SVG logos (data URIs) ---
const _svg = (s: string): string => `data:image/svg+xml,${encodeURIComponent(s)}`

const gmailLogo = _svg(
  '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 40 40">' +
    '<rect width="40" height="40" rx="8" fill="#ea4335"/>' +
    '<rect x="6" y="12" width="28" height="18" rx="2" fill="white"/>' +
    '<polygon points="6,12 20,24 34,12" fill="#ea4335"/>' +
    '<text x="20" y="31" text-anchor="middle" fill="#ea4335" font-size="8" font-weight="600" font-family="system-ui,sans-serif">Gmail</text></svg>',
)
const googleCalendarLogo = _svg(
  '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 40 40">' +
    '<rect width="40" height="40" rx="8" fill="#4285f4"/>' +
    '<rect x="8" y="10" width="24" height="22" rx="2" fill="white"/>' +
    '<rect x="8" y="14" width="24" height="3" fill="#4285f4"/>' +
    '<text x="20" y="29" text-anchor="middle" fill="#4285f4" font-size="11" font-weight="700" font-family="system-ui,sans-serif">28</text></svg>',
)
const customAiLogo = _svg(
  '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 40 40">' +
    '<rect width="40" height="40" rx="8" fill="#7c3aed"/>' +
    '<circle cx="20" cy="16" r="6" fill="white" opacity="0.9"/>' +
    '<path d="M12 30c0-4.418 3.582-8 8-8s8 3.582 8 8" fill="none" stroke="white" stroke-width="2" opacity="0.9"/>' +
    '<circle cx="28" cy="12" r="3" fill="white" opacity="0.6"/>' +
    '<circle cx="30" cy="10" r="2" fill="white" opacity="0.4"/>' +
    '<text x="20" y="36" text-anchor="middle" fill="white" font-size="6" font-weight="600" font-family="system-ui,sans-serif">AI</text></svg>',
)

export type IntegrationId = 'google-calendar' | 'gmail' | 'third-option'

export type IntegrationMeta = {
  id: IntegrationId
  label: string
  logoSrc?: string
}

export const INTEGRATION_META: readonly IntegrationMeta[] = [
  { id: 'google-calendar', label: 'Google Calendar', logoSrc: googleCalendarLogo },
  { id: 'gmail', label: 'Gmail', logoSrc: gmailLogo },
  { id: 'third-option', label: 'Personalizada (IA)', logoSrc: customAiLogo },
  /* T-ML-004: third-option = «Automatización personalizada (IA)»
     Sin integración externa; la interpreta el LLM. */
] as const

export function getIntegrationById(id: IntegrationId): IntegrationMeta {
  const found = INTEGRATION_META.find((i) => i.id === id)
  if (!found) {
    throw new Error(`Unknown integration: ${id}`)
  }
  return found
}
