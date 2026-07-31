const INTENT_PATTERNS: RegExp[] = [
  /^\s*(?:genera(?:r)?(?:\s+una)?\s+im[aá]gen|dibuja|crea(?:r)?(?:\s+una)?\s+im[aá]gen|hazme(?:\s+una)?\s+foto|ilustra)\b/i,
  /^\s*(?:generate(?:\s+an)?\s+image|draw(?:\s+a)?\s+picture|create(?:\s+an)?\s+image(?:\s+of)?|make(?:\s+a)?\s+photo(?:\s+of)?)\b/i,
]

const PREFIX_PATTERN =
  /^\s*(?:genera(?:r)?(?:\s+una)?\s+im[aá]gen(?:\s+de)?|dibuja(?:\s+una)?(?:\s+im[aá]gen(?:\s+de)?)?|crea(?:r)?(?:\s+una)?\s+im[aá]gen(?:\s+de)?|hazme(?:\s+una)?\s+foto(?:\s+de)?|ilustra(?:\s+una)?(?:\s+im[aá]gen(?:\s+de)?)?|generate(?:\s+an)?\s+image(?:\s+of)?|draw(?:\s+a)?\s+picture(?:\s+of)?|create(?:\s+an)?\s+image(?:\s+of)?|make(?:\s+a)?\s+photo(?:\s+of)?)\s*[:,-]?\s*/i

export function hasImageGenerationIntent(text: string): boolean {
  const value = text.trim()
  if (!value) return false
  return INTENT_PATTERNS.some((pattern) => pattern.test(value))
}

export function extractImagePrompt(text: string): string {
  let value = text.trim()
  let previous = ''
  while (value && value !== previous) {
    previous = value
    value = value.replace(PREFIX_PATTERN, '').trim()
  }
  return value || text.trim()
}

export const IMAGE_GEN_DRAFT_PREFIX = 'Genera una imagen de '
