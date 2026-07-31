import { useState, useCallback } from 'react'

import type {
  PipelineCreateRequest,
  PipelineDef,
  PipelineExecuteResponse,
  PipelineListResponse,
  PipelineUpdateRequest,
} from '@/features/dashboard/model/types'
import { apiFetchAuthed } from '@/lib/api/client'

export type UsePipelineOptions = {
  getAccessToken: () => Promise<string | null>
}

export type UsePipelineResult = {
  pipelines: PipelineDef[]
  loading: boolean
  error: string | null
  fetchPipelines: () => Promise<void>
  createPipeline: (req: PipelineCreateRequest) => Promise<PipelineDef | null>
  updatePipeline: (id: string, req: PipelineUpdateRequest) => Promise<PipelineDef | null>
  deletePipeline: (id: string) => Promise<boolean>
  executePipeline: (id: string) => Promise<PipelineExecuteResponse | null>
  detectPipelineIntent: (text: string) => Promise<{ is_pipeline: boolean; pipeline: PipelineDef | null; explanation: string }>
}

export function usePipelines({ getAccessToken }: UsePipelineOptions): UsePipelineResult {
  const [pipelines, setPipelines] = useState<PipelineDef[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchPipelines = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetchAuthed<PipelineListResponse>(
        '/v1/pipelines',
        { method: 'GET' },
        getAccessToken,
      )
      setPipelines(data.pipelines || [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al cargar pipelines')
      setPipelines([])
    } finally {
      setLoading(false)
    }
  }, [getAccessToken])

  const createPipeline = useCallback(async (req: PipelineCreateRequest): Promise<PipelineDef | null> => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetchAuthed<PipelineDef>(
        '/v1/pipelines',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(req),
        },
        getAccessToken,
      )
      setPipelines((prev) => [...prev, data])
      return data
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al crear pipeline')
      return null
    } finally {
      setLoading(false)
    }
  }, [getAccessToken])

  const updatePipeline = useCallback(async (id: string, req: PipelineUpdateRequest): Promise<PipelineDef | null> => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetchAuthed<PipelineDef>(
        `/v1/pipelines/${id}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(req),
        },
        getAccessToken,
      )
      setPipelines((prev) => prev.map((p) => (p.id === id ? data : p)))
      return data
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al actualizar pipeline')
      return null
    } finally {
      setLoading(false)
    }
  }, [getAccessToken])

  const deletePipeline = useCallback(async (id: string): Promise<boolean> => {
    setLoading(true)
    setError(null)
    try {
      await apiFetchAuthed(
        `/v1/pipelines/${id}`,
        { method: 'DELETE' },
        getAccessToken,
      )
      setPipelines((prev) => prev.filter((p) => p.id !== id))
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al eliminar pipeline')
      return false
    } finally {
      setLoading(false)
    }
  }, [getAccessToken])

  const executePipeline = useCallback(async (id: string): Promise<PipelineExecuteResponse | null> => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetchAuthed<PipelineExecuteResponse>(
        `/v1/pipelines/${id}/execute`,
        { method: 'POST' },
        getAccessToken,
      )
      return data
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al ejecutar pipeline')
      return null
    } finally {
      setLoading(false)
    }
  }, [getAccessToken])

  const detectPipelineIntent = useCallback(async (text: string) => {
    try {
      const data = await apiFetchAuthed<{ is_pipeline: boolean; pipeline: PipelineDef | null; explanation: string }>(
        '/v1/pipelines/intent/detect',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text }),
        },
        getAccessToken,
      )
      return data
    } catch {
      return { is_pipeline: false, pipeline: null, explanation: 'Error al detectar intención' }
    }
  }, [getAccessToken])

  return {
    pipelines,
    loading,
    error,
    fetchPipelines,
    createPipeline,
    updatePipeline,
    deletePipeline,
    executePipeline,
    detectPipelineIntent,
  }
}
