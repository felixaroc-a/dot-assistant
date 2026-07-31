import whatsappLogo from '@/assets/onboarding/whatsapp.png'

import type { ChannelId } from '@/features/onboarding/model/channel.types'

export type ChannelMeta = {
  id: ChannelId
  name: string
  iconSrc: string
}

export const CHANNEL_META: readonly ChannelMeta[] = [
  { id: 'whatsapp', name: 'WhatsApp', iconSrc: whatsappLogo },
] as const

export function getChannelMeta(id: ChannelId): ChannelMeta {
  const m = CHANNEL_META.find((c) => c.id === id)
  if (!m) throw new Error(`Unknown channel: ${id}`)
  return m
}
