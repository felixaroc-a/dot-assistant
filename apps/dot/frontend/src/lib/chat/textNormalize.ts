/**
 * Utilidad mínima de normalización de texto para comparaciones case-insensitive
 * y sin acentos.
 */

const STRIP_ACCENTS_MAP: Record<string, string> = {
  á: 'a', é: 'e', í: 'i', ó: 'o', ú: 'u',
  Á: 'A', É: 'E', Í: 'I', Ó: 'O', Ú: 'U',
  ñ: 'n', Ñ: 'N',
  ü: 'u', Ü: 'U',
}

/** Convierte a minúsculas y remueve acentos comunes del español. */
export function normalize(text: string): string {
  let result = text.toLowerCase()
  for (const [accented, plain] of Object.entries(STRIP_ACCENTS_MAP)) {
    result = result.replaceAll(accented, plain)
  }
  return result
}
