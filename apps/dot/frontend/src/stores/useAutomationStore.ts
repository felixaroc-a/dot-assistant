import { create } from 'zustand'

import type { AutomationPendingResponse, SavedAutomation } from '@/features/dashboard/model/types'
import type { WhatsAppLinkStatus } from '@/lib/api/whatsapp'

export type AutomationState = {
  /** Lista de automatizaciones del usuario */
  automations: SavedAutomation[]
  /** Indica si hay resultados pendientes de automatizaciones */
  hasPendingResults: boolean
  /** Datos del resultado pendiente */
  pendingAutomation: AutomationPendingResponse | null
  /** Estado de la conexion WhatsApp */
  whatsappStatus: WhatsAppLinkStatus
}

export type AutomationActions = {
  setAutomations: (automations: SavedAutomation[]) => void
  updateAutomation: (id: string, changes: Partial<SavedAutomation>) => void
  addAutomation: (automation: SavedAutomation) => void
  removeAutomation: (id: string) => void
  setHasPendingResults: (pending: boolean) => void
  setPendingAutomation: (pending: AutomationPendingResponse | null) => void
  setWhatsappStatus: (status: WhatsAppLinkStatus) => void
  clearPendingResults: () => void
}

export type AutomationStore = AutomationState & AutomationActions

export const useAutomationStore = create<AutomationStore>((set) => ({
  automations: [],
  hasPendingResults: false,
  pendingAutomation: null,
  whatsappStatus: 'disconnected',

  setAutomations: (automations) => set({ automations }),
  updateAutomation: (id, changes) =>
    set((s) => ({
      automations: s.automations.map((a) => (a.id === id ? { ...a, ...changes } : a)),
    })),
  addAutomation: (automation) =>
    set((s) => ({ automations: [...s.automations, automation] })),
  removeAutomation: (id) =>
    set((s) => ({ automations: s.automations.filter((a) => a.id !== id) })),
  setHasPendingResults: (pending) => set({ hasPendingResults: pending }),
  setPendingAutomation: (pending) => set({ pendingAutomation: pending }),
  setWhatsappStatus: (status) => set({ whatsappStatus: status }),
  clearPendingResults: () => set({ hasPendingResults: false, pendingAutomation: null }),
}))
