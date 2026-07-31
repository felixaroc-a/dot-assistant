import type { ChatAttachment } from '@/lib/chat/types'

type ArtifactRecord = {
  type?: string
  mime?: string
  mime_type?: string
  data?: string
  data_base64?: string
  name?: string
  width?: number
  height?: number
}

/** Convierte artifacts SSE del agente en adjuntos renderizables en el chat. */
export function artifactsToGeneratedImages(items: unknown[]): ChatAttachment[] {
  const images: ChatAttachment[] = []

  for (const [index, raw] of items.entries()) {
    if (!raw || typeof raw !== 'object') continue
    const artifact = raw as ArtifactRecord
    if (artifact.type !== 'image') continue

    const mime = artifact.mime || artifact.mime_type || 'image/png'
    const base64 = (artifact.data || artifact.data_base64 || '').trim()
    if (!base64) continue

    const data = base64.startsWith('data:') ? base64 : `data:${mime};base64,${base64}`
    images.push({
      name: artifact.name || `imagen-generada-${index + 1}.png`,
      type: mime,
      size: Math.ceil((base64.length * 3) / 4),
      data,
    })
  }

  return images
}
