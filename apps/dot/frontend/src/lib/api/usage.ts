import { apiClient } from '@/lib/api/api-client'
import type { GetAccessToken } from '@/lib/api/api-client'

export type UsagePeriod = {
  start: string
  end: string
}

export type ProviderModelCost = {
  [modelId: string]: number
}

export type ProviderBreakdownItem = {
  provider: string
  total_usd: number
  tokens_in: number
  tokens_out: number
  models: ProviderModelCost
}

export type UsageBreakdown = {
  chat_usd: number
  reasoning_usd: number
  vision_usd: number
  image_usd: number
}

export type UsageDailyItem = {
  date: string
  usd: number
}

export type UsageSummary = {
  cliente_id: string
  period: UsagePeriod
  limit_usd: number
  consumed_usd: number
  consumed_percent: number
  remaining_usd: number
  limit_enabled: boolean
  blocked: boolean
  breakdown?: UsageBreakdown
  provider_breakdown?: ProviderBreakdownItem[]
  projected_depletion_date?: string | null
}

export type UsageDailyResponse = {
  days: UsageDailyItem[]
}

export async function fetchUsageSummary(
  getAccessToken: GetAccessToken,
): Promise<UsageSummary> {
  return apiClient.get<UsageSummary>('/v1/usage/summary', getAccessToken)
}

export async function fetchUsageDaily(
  getAccessToken: GetAccessToken,
  days = 7,
): Promise<UsageDailyResponse> {
  return apiClient.get<UsageDailyResponse>(`/v1/usage/daily?days=${days}`, getAccessToken)
}
