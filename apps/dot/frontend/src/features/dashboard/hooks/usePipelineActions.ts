/**
 * usePipelineActions — Hook de acciones de pipeline.
 *
 * Extraído de DashboardShell.tsx (C16: refactor para reducir de 1388 a <500 líneas).
 * Centraliza: crear, editar, eliminar, ejecutar, seleccionar y guardar pipelines.
 *
 * Dependencias: usePipelines (data layer), useChat (notificaciones en chat),
 * useDashboardUI (control de drawer).
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ChatRef, DashboardUIRef, UsePipelinesReturn } from './types'
import type {
  ActivePipelineView,
  PipelineDef,
  PipelineStepRunStatus,
} from '../model/types'

export interface UsePipelineActionsInput {
  pipelines: UsePipelinesReturn
  chat: ChatRef
  ui: DashboardUIRef
}

export function usePipelineActions({ pipelines, chat, ui }: UsePipelineActionsInput) {
  const {
    items,
    fetchAll,
    create,
    update,
    remove,
    execute,
  } = pipelines

  const [editingPipeline, setEditingPipeline] = useState<PipelineDef | null>(null)
  const [pipelineFeedback, setPipelineFeedback] = useState<string | null>(null)
  const [selectedPipelineId, setSelectedPipelineId] = useState<string | null>(null)
  const [pipelineRunView, setPipelineRunView] = useState<ActivePipelineView | null>(null)

  useEffect(() => {
    void fetchAll()
  }, [fetchAll])

  useEffect(() => {
    if (!pipelineFeedback) return
    const timer = setTimeout(() => setPipelineFeedback(null), 6000)
    return () => clearTimeout(timer)
  }, [pipelineFeedback])

  const openPipelineEditor = useCallback((pipeline?: PipelineDef | null) => {
    setEditingPipeline(pipeline ?? null)
    ui.setDrawerOpen(true)
  }, [ui])

  const selectedPipeline = useMemo(
    () => items.find((p) => p.id === selectedPipelineId) ?? null,
    [items, selectedPipelineId],
  )

  useEffect(() => {
    if (selectedPipelineId && !items.some((p) => p.id === selectedPipelineId)) {
      setSelectedPipelineId(null)
    }
  }, [items, selectedPipelineId])

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
        statuses[step.id] = !sr
          ? result.success
            ? 'completed'
            : 'waiting'
          : sr.error
            ? 'error'
            : 'completed'
      })
      return statuses
    }
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

  const handlePipelineEdit = useCallback((id: string) => {
    const found = items.find((p) => p.id === id) ?? null
    openPipelineEditor(found)
  }, [items, openPipelineEditor])

  const handlePipelineDelete = useCallback(async (id: string) => {
    const ok = await remove(id)
    if (ok) {
      setPipelineFeedback('Pipeline eliminado.')
      if (selectedPipelineId === id) {
        setSelectedPipelineId(null)
        setPipelineRunView(null)
      }
    } else {
      setPipelineFeedback('No se pudo eliminar el pipeline.')
    }
  }, [remove, selectedPipelineId])

  const handlePipelineToggleActive = useCallback(async (id: string) => {
    const current = items.find((p) => p.id === id)
    if (!current) return
    const updatedPipeline = await update(id, { active: !current.active })
    if (updatedPipeline) {
      setPipelineFeedback(
        updatedPipeline.active
          ? `Pipeline "${updatedPipeline.name}" activado.`
          : `Pipeline "${updatedPipeline.name}" pausado.`,
      )
    }
  }, [items, update])

  const handleSelectPipeline = useCallback((id: string) => {
    setSelectedPipelineId(id)
    if (pipelineRunView?.pipelineId !== id) {
      const pipeline = items.find((p) => p.id === id)
      if (pipeline) {
        const stepStatuses: Record<string, PipelineStepRunStatus> = {}
        pipeline.steps.forEach((step) => {
          stepStatuses[step.id] = pipeline.last_run ? 'completed' : 'idle'
        })
        setPipelineRunView({ pipelineId: id, runStatus: 'idle', stepStatuses })
      }
    }
  }, [pipelineRunView?.pipelineId, items])

  const handlePipelineExecute = useCallback(async (id: string) => {
    const pipeline = items.find((p) => p.id === id)
    setSelectedPipelineId(id)
    if (pipeline) {
      setPipelineRunView({
        pipelineId: id,
        runStatus: 'running',
        stepStatuses: buildStepStatuses(pipeline, null, 'running'),
      })
    }

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
      const result = await execute(id)
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
        chat.pushLocalExchange(
          '',
          output
            ? `✅ Pipeline ejecutado (${result.steps_count} pasos).\n${output}`
            : `✅ Pipeline ejecutado (${result.steps_count} pasos).`,
        )
        void fetchAll()
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
          result?.steps?.filter((s) => s.error).map((s) => `${s.step_id}: ${s.error}`).join('\n'),
        ].filter(Boolean).join('\n\n')
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
        chat.pushLocalExchange('', details ? `❌ ${summary}\n${details}` : `❌ ${summary}`)
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
      chat.pushLocalExchange('', `❌ ${msg}`)
    }
  }, [execute, chat, fetchAll, items, buildStepStatuses])

  const handlePipelineSave = useCallback(async (
    name: string,
    description: string,
    naturalLanguage: string,
    schedule: string,
  ) => {
    if (editingPipeline) {
      const updatedPipeline = await update(editingPipeline.id, {
        name: name.trim() || editingPipeline.name,
        description: description.trim(),
        schedule,
      })
      if (updatedPipeline) {
        setPipelineFeedback(`Pipeline "${updatedPipeline.name}" actualizado.`)
        setSelectedPipelineId(updatedPipeline.id)
        chat.pushLocalExchange('', `✅ Pipeline "${updatedPipeline.name}" actualizado.`)
        ui.setDrawerOpen(false)
        setEditingPipeline(null)
      } else {
        setPipelineFeedback('No se pudo actualizar el pipeline.')
      }
      return
    }

    const created = await create({
      name: name.trim() || undefined,
      description: description.trim() || undefined,
      natural_language: naturalLanguage,
      schedule,
    })
    if (created) {
      setPipelineFeedback(`Pipeline "${created.name}" creado. Ya aparece en Pipelines.`)
      setSelectedPipelineId(created.id)
      const stepStatuses: Record<string, PipelineStepRunStatus> = {}
      created.steps.forEach((step, i) => {
        stepStatuses[step.id] = i === 0 ? 'waiting' : 'idle'
      })
      setPipelineRunView({ pipelineId: created.id, runStatus: 'idle', stepStatuses })
      chat.pushLocalExchange(
        '',
        `✅ Pipeline "${created.name}" creado con ${created.steps.length} pasos. Revisa el panel Previsualización y Estado.`,
      )
      ui.setDrawerOpen(false)
      setEditingPipeline(null)
    } else {
      setPipelineFeedback('No se pudo crear el pipeline. Revisa la descripción e intenta de nuevo.')
    }
  }, [editingPipeline, update, create, chat, ui])

  return {
    // Estado
    editingPipeline,
    pipelineFeedback,
    selectedPipelineId,
    pipelineRunView,
    // Acciones
    setDrawerMode: ui.setDrawerOpen ? ((_mode: string) => {
      ui.setDrawerOpen(true)
    }) : undefined,
    openPipelineEditor,
    handlePipelineEdit,
    handlePipelineDelete,
    handlePipelineToggleActive,
    handlePipelineExecute,
    handlePipelineSave,
    handleSelectPipeline,
    selectedPipeline,
    buildStepStatuses,
    setPipelineFeedback,
    setSelectedPipelineId,
    setPipelineRunView,
    setEditingPipeline,
  }
}
