import type { ChatAttachment } from '@/lib/chat/types'
import { FileAttachment } from './FileAttachment'

type GeneratedImagesGridProps = {
  images: ChatAttachment[]
}

export function GeneratedImagesGrid({ images }: GeneratedImagesGridProps) {
  if (!images.length) return null
  return (
    <div className="dot-chat__generated-images" role="group" aria-label="Imágenes generadas">
      {images.map((image, index) => (
        <FileAttachment key={`${image.name}-${index}`} attachment={image} />
      ))}
    </div>
  )
}
