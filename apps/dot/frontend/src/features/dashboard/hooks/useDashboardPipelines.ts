import { useCallback, useEffect, useMemo, useState, type Dispatch, type SetStateAction } from 'react'

import type {
  ActivePipelineView,
  PipelineDef,
  PipelineExecuteResponse,
  PipelineStepRunStatus,
} from '@/features/dashboard/model/types'

export type UseDashboardPipelinesOptions = {
  pipelines: PipelineDef[]
  executePipeline: (id: string) => Promise<PipelineExecuteResponse | null>
  fetchPipelines: () => Promise<void>
  pushLocalExchange: (role: string, text: string) => void
}

export type UseDashboardPipelinesResult = {
  pipelineFeedback: string | null
  setPipelineFeedback: Dispatch<SetStateAction<string | null>>
  pipelineRunView: ActivePipelineView | null
  setPipelineRunView: Dispatch<SetStateAction<ActivePipelineView | null>>
  selectedPipelineId: string | null
  setSelectedPipelineId: Dispatch<SetStateAction<string | null>>
  selectedPipeline: PipelineDef | null
  buildStepStatuses: (
    pipeline: PipelineDef,
    result: { success: boolean; steps?: Array<{ step_id: string; error: string | null }> } | null,
    mode: 'running' | 'done',
  ) => Record<string, PipelineStepRunStatus>
  handlePipelineExecute: (id: string) => Promise<void>
  handleSelectPipeline: (id: string) => void
}

export function useDashboardPipelines({
  pipelines,
  executePipeline,
  fetchPipelines,
  pushLocalExchange,
}: UseDashboardPipelinesOptions): UseDashboardPipelinesResult {
  const [pipelineFeedback, setPipelineFeedback] = useState<string | null>(null)
  const [pipelineRunView, setPipelineRunView] = useState<ActivePipelineView | null>(null)
  const [selectedPipelineId, setSelectedPipelineId] = useState<string | null>(null)

  // Auto-dismiss pipeline feedback después de 6s
  useEffect(() => {
    if (!pipelineFeedback) return
    const timer = setTimeout(() => setPipelineFeedback(null), 6000)
    return () => clearTimeout(timer)
  }, [pipelineFeedback])

  // Limpiar selección si el pipeline ya no existe (p. ej. borrado en otro lado)
  useEffect(() => {
    if (selectedPipelineId && !pipelines.some((p) => p.id === selectedPipelineId)) {
      setSelectedPipelineId(null)
    }
  }, [pipelines, selectedPipelineId])

  const selectedPipeline = useMemo(
    () => pipelines.find((p) => p.id === selectedPipelineId) ?? null,
    [pipelines, selectedPipelineId],
  )

  const buildStepStatuses = useCallback((
    pipeline: PipelineDef,
    result: { success: boolean; steps?: Array<{ step_id: string; error: string | null }> } | null,
    mode: 'running' | 'done',
  ): Record<string, PipelineStepRunStatus> => {
    const statuses: Record<string, PipelineStepRunStatus> = {}
    if (mode === 'running') {
      pipeline.steps.forEach((step, i) => {
        statuses[step.id] = i === 0 ? 'in_progress' : 'waiting'
      })
      return statuses
    }
    if (result?.steps?.length) {
      const byId = new Map(result.steps.map((s) => [s.step_id, s]))
      pipeline.steps.forEach((step) => {
        const sr = byId.get(step.id)
        if (!sr) {
          statuses[step.id] = result.success ? 'completed' : 'waiting'
        } else if (sr.error) {
          statuses[step.id] = 'error'
        } else {
          statuses[step.id] = 'completed'
        }
      })
      return statuses
    }
    // Fallback: marcar todos completados o error en el último
    pipeline.steps.forEach((step, i) => {
      if (result?.success) {
        statuses[step.id] = 'completed'
      } else if (i === pipeline.steps.length - 1) {
        statuses[step.id] = 'error'
      } else {
        statuses[step.id] = 'completed'
      }
    })
    return statuses
  }, [])

  const handleSelectPipeline = useCallback((id: string) => {
    setSelectedPipelineId(id)
    if (pipelineRunView?.pipelineId !== id) {
      const pipeline = pipelines.find((p) => p.id === id)
      if (pipeline) {
        const stepStatuses: Record<string, PipelineStepRunStatus> = {}
        pipeline.steps.forEach((step) => {
          stepStatuses[step.id] = pipeline.last_run ? 'completed' : 'idle'
        })
        setPipelineRunView({
          pipelineId: id,
          runStatus: 'idle',
          stepStatuses,
        })
      }
    }
  }, [pipelineRunView?.pipelineId, pipelines])

  const handlePipelineExecute = useCallback(async (id: string) => {
    const pipeline = pipelines.find((p) => p.id === id)
    setSelectedPipelineId(id)
    if (pipeline) {
      setPipelineRunView({
        pipelineId: id,
        runStatus: 'running',
        stepStatuses: buildStepStatuses(pipeline, null, 'running'),
      })
    }

    // Avance visual de pasos mientras espera la API (hace obvio el progreso).
    let advanceTimer: ReturnType<typeof setInterval> | null = null
    if (pipeline && pipeline.steps.length > 1) {
      let cursor = 0
      advanceTimer = setInterval(() => {
        cursor += 1
        if (cursor >= pipeline.steps.length) {
          if (advanceTimer) clearInterval(advanceTimer)
          return
        }
        const statuses: Record<string, PipelineStepRunStatus> = {}
        pipeline.steps.forEach((step, i) => {
          if (i < cursor) statuses[step.id] = 'completed'
          else if (i === cursor) statuses[step.id] = 'in_progress'
          else statuses[step.id] = 'waiting'
        })
        setPipelineRunView((prev) => {
          if (!prev || prev.pipelineId !== id || prev.runStatus !== 'running') return prev
          return { ...prev, stepStatuses: statuses }
        })
      }, 700)
    }

    try {
      const result = await executePipeline(id)
      if (advanceTimer) clearInterval(advanceTimer)
      if (result?.success) {
        setPipelineFeedback('Pipeline ejecutado correctamente.')
        if (pipeline) {
          setPipelineRunView({
            pipelineId: id,
            runStatus: 'success',
            stepStatuses: buildStepStatuses(pipeline, result, 'done'),
            finalOutput: result.final_output,
            executedAt: result.executed_at,
          })
        }
        const output = result.final_output?.trim()
        pushLocalExchange(
          '',
          output
            ? `✅ Pipeline ejecutado (${result.steps_count} pasos).\n${output}`
            : `✅ Pipeline ejecutado (${result.steps_count} pasos).`,
        )
        void fetchPipelines()
      } else {
        const errMsg = result?.error || 'Error al ejecutar el pipeline.'
        const failedStep = result?.steps?.find((s) => s.error)
        const failedIdx =
          failedStep && pipeline
            ? pipeline.steps.findIndex((s) => s.id === failedStep.step_id)
            : -1
        const summary =
          failedIdx >= 0
            ? `El pipeline "${pipeline?.name ?? id}" falló en el Paso ${failedIdx + 1}.`
            : errMsg
        const details = [
          errMsg !== summary ? errMsg : null,
          result?.final_output,
          result?.steps
            ?.filter((s) => s.error)
            .map((s) => `${s.step_id}: ${s.error}`)
            .join('\n'),
        ]
          .filter(Boolean)
          .join('\n\n')
        setPipelineFeedback('Error al ejecutar el pipeline.')
        if (pipeline) {
          setPipelineRunView({
            pipelineId: id,
            runStatus: 'error',
            stepStatuses: buildStepStatuses(pipeline, result, 'done'),
            errorMessage: summary,
            errorDetails: details || null,
            executedAt: result?.executed_at ?? null,
          })
        }
        pushLocalExchange(
          '',
          details
            ? `❌ ${summary}\n${details}`
            : `❌ ${summary}`,
        )
      }
    } catch (err) {
      if (advanceTimer) clearInterval(advanceTimer)
      const msg = err instanceof Error ? err.message : 'Error al ejecutar el pipeline.'
      setPipelineFeedback(msg)
      if (pipeline) {
        setPipelineRunView({
          pipelineId: id,
          runStatus: 'error',
          stepStatuses: buildStepStatuses(pipeline, null, 'done'),
          errorMessage: msg,
          errorDetails: null,
        })
      }
      pushLocalExchange('', `❌ ${msg}`)
    }
  }, [executePipeline, fetchPipelines, pipelines, buildStepStatuses, pushLocalExchange])

  return {
    pipelineFeedback,
    setPipelineFeedback,
    pipelineRunView,
    setPipelineRunView,
    selectedPipelineId,
    setSelectedPipelineId,
    selectedPipeline,
    buildStepStatuses,
    handlePipelineExecute,
    handleSelectPipeline,
  }
}
