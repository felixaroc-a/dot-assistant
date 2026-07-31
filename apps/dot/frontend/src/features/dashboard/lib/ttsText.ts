const MEMORY_BLOCK = /--MEMORY[\s\S]*?(?:\}--|$)/g
const MAX_TTS_CHARS = 4000

/** Prepara texto de respuesta del asistente para síntesis de voz. */
export function prepareTextForTts(raw: string): string {
  let text = raw.replace(MEMORY_BLOCK, '')
  text = text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\s+/g, ' ')
    .trim()

  if (text.length > MAX_TTS_CHARS) {
    text = `${text.slice(0, MAX_TTS_CHARS - 1).trim()}…`
  }

  return text
}
