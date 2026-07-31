import type { IntegrationId } from '@/features/integrations'

export type AgentId = 'auto' | 'senior-code' | 'finanzas' | 'asistente' | 'opcion-5'

export type AutomationOutputType = 'notify' | 'email' | 'file'

export type SavedAutomation = {
  id: string
  name: string
  integrationId: IntegrationId
  instruction: string
  active: boolean
  outputType?: AutomationOutputType
  schedule?: string
  description?: string
}

// ─── C2: Pipeline types ───────────────────────────────

export type PipelineStepType = 'trigger' | 'action' | 'condition' | 'output'

export type ConditionOperator =
  | 'always'
  | 'if_result_contains'
  | 'if_result_matches'
  | 'if_error'
  | 'if_no_error'

export type OnFailure = 'skip' | 'log' | 'abort'

export type PipelineStep = {
  id: string
  type: PipelineStepType
  integration: string
  instruction: string
  condition_operator: ConditionOperator
  condition_value: string
  depends_on: string[]
  on_failure: OnFailure
  timeout_seconds: number
}

export type PipelineDef = {
  id: string
  name: string
  description: string
  steps: PipelineStep[]
  schedule: string
  active: boolean
  created_at: string
  last_run: string | null
  source_nl: string
}

export type PipelineCreateRequest = {
  name?: string
  description?: string
  /** Vacío si se envían `steps` estructurados (p. ej. clon desde plantilla). */
  natural_language?: string
  schedule?: string
  steps?: PipelineStep[]
}

export type PipelineUpdateRequest = {
  name?: string | null
  description?: string | null
  steps?: PipelineStep[] | null
  schedule?: string | null
  active?: boolean | null
}

export type PipelineStepRunStatus = 'completed' | 'in_progress' | 'waiting' | 'error' | 'idle'

export type PipelineStepResult = {
  step_id: string
  step_type: string
  output: string
  error: string | null
  executed_at: string
  duration_ms?: number
}

export type PipelineExecuteResponse = {
  execution_id: string
  success: boolean
  final_output: string
  steps_count: number
  executed_at: string
  error?: string | null
  steps?: PipelineStepResult[]
}

/** Estado local de ejecución visible en el panel derecho. */
export type ActivePipelineView = {
  pipelineId: string
  runStatus: 'idle' | 'running' | 'success' | 'error'
  stepStatuses: Record<string, PipelineStepRunStatus>
  errorMessage?: string | null
  errorDetails?: string | null
  finalOutput?: string | null
  executedAt?: string | null
}

export type GeneratedDocPreview = {
  filename: string
  path: string
}

export type PipelineListResponse = {
  pipelines: PipelineDef[]
}

// ─── C3: Pipeline Template types ─────────────────────

export type PipelineTemplate = {
  id: string
  name: string
  description: string
  category: string
  schedule: string
  author_uid: string
  usage_count: number
  created_at: string
}

export type PipelineTemplateListResponse = {
  templates: PipelineTemplate[]
}

// ─── C3: Plantillas populares para automatizaciones simples ───

export type PopularAutomationTemplate = {
  id: string
  name: string
  description: string
  category: string
  schedule: string
  suggested_name: string
  suggested_instruction: string
  suggested_integration: string
  suggested_output_type: AutomationOutputType
}

export type PopularAutomationTemplatesResponse = {
  templates: PopularAutomationTemplate[]
}

export type TemplateCloneResponse = {
  template_id: string
  template_name: string
  schedule: string
  workflow_def: PipelineDef
}

export type TemplateSaveRequest = {
  name: string
  description?: string
  category?: string
  workflow_def: PipelineDef
  schedule?: string
}

export type ChatRole = 'agent' | 'user'

export type ChatMessage = {
  id: string
  role: ChatRole
  text: string
}

export type AgendaTodayResponse = {
  linked: boolean
  events: Array<{
    summary: string
    start: string | null
    end: string | null
    html_link: string | null
  }>
  message: string
}

export type ReminderCreateResponse = {
  ok: boolean
  id: string
  due_at: string
  message: string
}

export type PendingReminderResponse = {
  reminders: Array<{
    id: string
    text: string
    due_at: string
  }>
}

export type TranslateResponse = {
  translated_text: string
  provider: string
  target_lang: string
}

export type SummarizeResponse = {
  summary: string
  source_type: string
  chunks: number
}

export type AutomationPendingResponse = {
  has_new: boolean
  last_auto_id: string | null
  last_auto_name: string | null
  last_executed_at: string | null
  last_result_preview: string | null
}
