/**
 * types.ts — Tipos internos para hooks de dashboard (C16 refactor).
 *
 * Define interfaces de referencia que los hooks necesitan para
 * desacoplarse sin depender directamente de otros módulos.
 */
import type { PipelineDef } from '../model/types'

export interface ChatRef {
  pushLocalExchange: (role: string, content: string) => void
}

export interface DashboardUIRef {
  setDrawerOpen: (open: boolean) => void
}

export interface PipelineRef {
  pipelineId: string
  pipelineName: string
  pipeline?: PipelineDef | null
  pipelines?: PipelineDef[]
}

export interface UsePipelinesReturn {
  items: PipelineDef[]
  loading: boolean
  fetchAll: () => Promise<void>
  create: (input: {
    name?: string
    description?: string
    natural_language?: string
    schedule?: string
    steps?: PipelineDef['steps']
  }) => Promise<PipelineDef | null>
  update: (id: string, patch: Partial<PipelineDef>) => Promise<PipelineDef | null>
  remove: (id: string) => Promise<boolean>
  execute: (id: string) => Promise<{
    success: boolean
    final_output?: string | null
    steps_count?: number
    error?: string | null
    steps?: Array<{ step_id: string; error: string | null }>
    executed_at?: string | null
  } | null>
}
