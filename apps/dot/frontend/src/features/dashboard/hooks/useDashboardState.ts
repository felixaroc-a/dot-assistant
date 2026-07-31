import { useMemo, useState, type Dispatch, type SetStateAction } from 'react'

import type { AgentId, AutomationPendingResponse, SavedAutomation } from '@/features/dashboard/model/types'
import type { WhatsAppLinkStatus } from '@/lib/api/whatsapp'
import type { ProductSession } from '@/features/auth/types'

/** Capacidades del producto unificado (BIBLIA D1 — sin gating por plan). */
const UNIFIED_CAPABILITIES: string[] = [
  'chat_completion',
  'whatsapp_channel_login',
  'web_search',
  'automation_plugins',
  'image_generation',
  'file_tools',
]

function getPlanLabel(plan: string | null | undefined): string {
  if (plan === 'mensual') return 'Plan Mensual'
  if (plan === 'trimestral') return 'Plan Trimestral'
  if (plan === 'anual') return 'Plan Anual'
  return 'Sin plan'
}

export type UseDashboardStateOptions = {
  session: ProductSession | null
}

export type UseDashboardStateResult = {
  /** Plan del usuario (mensual / trimestral / anual) — solo duración/copy */
  plan: string | null
  /** Capacidades del producto (todas habilitadas; sin gating por plan) */
  capabilities: string[]
  /** Siempre true: producto unificado incluye automatizaciones */
  hasAutomations: boolean
  /** Etiqueta del plan (UI copy) */
  planLabel: string

  /** Agente seleccionado en el workspace */
  agent: AgentId
  setAgent: (agent: AgentId) => void

  /** Lista de automatizaciones guardadas */
  automations: SavedAutomation[]
  setAutomations: Dispatch<SetStateAction<SavedAutomation[]>>

  /** Indica si hay resultados pendientes de automatizaciones */
  hasPendingResults: boolean
  setHasPendingResults: (pending: boolean) => void
  /** Datos del resultado pendiente */
  pendingAutomation: AutomationPendingResponse | null
  setPendingAutomation: (pending: AutomationPendingResponse | null) => void

  /** Estado de la conexion WhatsApp */
  whatsappStatus: WhatsAppLinkStatus
  setWhatsappStatus: (status: WhatsAppLinkStatus) => void
}

export function useDashboardState({ session }: UseDashboardStateOptions): UseDashboardStateResult {
  const plan = session?.cliente?.plan ?? null
  const capabilities = UNIFIED_CAPABILITIES
  const hasAutomations = true
  const planLabel = getPlanLabel(plan)

  const [agent, setAgent] = useState<AgentId>('auto')
  const [automations, setAutomations] = useState<SavedAutomation[]>([])
  const [hasPendingResults, setHasPendingResults] = useState(false)
  const [pendingAutomation, setPendingAutomation] = useState<AutomationPendingResponse | null>(null)
  const [whatsappStatus, setWhatsappStatus] = useState<WhatsAppLinkStatus>('disconnected')

  return useMemo(() => ({
    plan,
    capabilities,
    hasAutomations,
    planLabel,
    agent,
    setAgent,
    automations,
    setAutomations,
    hasPendingResults,
    setHasPendingResults,
    pendingAutomation,
    setPendingAutomation,
    whatsappStatus,
    setWhatsappStatus,
  }), [
    plan,
    capabilities,
    hasAutomations,
    planLabel,
    agent,
    automations,
    hasPendingResults,
    pendingAutomation,
    whatsappStatus,
  ])
}
