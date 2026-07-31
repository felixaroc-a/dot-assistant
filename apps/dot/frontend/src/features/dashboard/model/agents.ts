import type { AgentId } from '@/features/dashboard/model/types'

export const WORKSPACE_AGENTS: Array<{ id: AgentId; label: string }> = [
  { id: 'auto', label: 'Auto' },
  { id: 'senior-code', label: 'Senior Code' },
  { id: 'finanzas', label: 'Finanzas' },
  { id: 'asistente', label: 'Asistente' },
  { id: 'opcion-5', label: 'Opción 5' },
]
