export const IMAGE_ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp']
const MAX_IMAGE_FILE_SIZE = 10 * 1024 * 1024 // 10 MB

export function validateVisionImage(file: File): string | null {
  if (!IMAGE_ACCEPTED_TYPES.includes(file.type)) {
    return 'Solo se admiten imágenes PNG, JPG o WebP.'
  }

  if (file.size > MAX_IMAGE_FILE_SIZE) {
    return 'La imagen es demasiado grande. Tamaño máximo: 10 MB.'
  }

  return null
}
