import { apiClient } from '@/lib/api/api-client'
import type { GetAccessToken } from '@/lib/api/api-client'

export type GeneratedImageDto = {
  mime_type: string
  data_base64: string
  width: number
  height: number
}

export type ImageGenerateResponse = {
  images: GeneratedImageDto[]
  prompt_used: string
  count: number
  usage: {
    cost_usd: number
    model: string
  }
}

export type ImageGenerateRequest = {
  prompt: string
  count?: number | null
  aspect_ratio?: string
  resolution?: string
}

export async function generateImages(
  body: ImageGenerateRequest,
  getAccessToken: GetAccessToken,
): Promise<ImageGenerateResponse> {
  return apiClient.post<ImageGenerateResponse>('/v1/images/generate', body, getAccessToken)
}
