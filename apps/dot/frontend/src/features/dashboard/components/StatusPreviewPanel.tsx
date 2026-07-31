import { useCallback, useState } from 'react'

import { useToast } from '@/components/Toast'
import { useAuth } from '@/features/auth'
import { translateErrorMessage } from '@/lib/error-messages'
import type { WhatsAppLinkStatus } from '@/lib/api/whatsapp'
import { sendWhatsAppMedia } from '@/lib/api/whatsapp'
import type {
  ActivePipelineView,
  GeneratedDocPreview,
  PipelineDef,
  PipelineStepRunStatus,
} from '@/features/dashboard/model/types'

export type StatusPreviewPanelProps = {
  selectedPipeline: PipelineDef | null
  activeView: ActivePipelineView | null
  docPreview: GeneratedDocPreview | null
  whatsappStatus: WhatsAppLinkStatus
  whatsappPhone?: string | null
  googleConnected: boolean
  pipelineCount?: number
  onSelectPipelineHint?: () => void
  onCreatePipelineHint?: () => void
  onOpenIntegrations?: (focus?: 'whatsapp' | 'google') => void
}

function whatsappLabel(status: WhatsAppLinkStatus): string {
  switch (status) {
    case 'linked':
      return 'Vinculado'
    case 'connecting':
      return 'Conectando…'
    case 'pending_verification':
      return 'Pendiente'
    default:
      return 'Desconectado'
  }
}

function whatsappTone(status: WhatsAppLinkStatus): 'ok' | 'warn' | 'off' {
  if (status === 'linked') return 'ok'
  if (status === 'connecting' || status === 'pending_verification') return 'warn'
  return 'off'
}

function stepStatusLabel(status: PipelineStepRunStatus): string {
  switch (status) {
    case 'completed':
      return 'Completado'
    case 'in_progress':
      return 'En progreso'
    case 'waiting':
      return 'Esperando input'
    case 'error':
      return 'Error'
    default:
      return 'Pendiente'
  }
}

function stepGlyph(status: PipelineStepRunStatus): string {
  switch (status) {
    case 'completed':
      return '✓'
    case 'in_progress':
      return '●'
    case 'error':
      return '!'
    case 'waiting':
      return '…'
    default:
      return String.fromCharCode(0x25cb) // ○
  }
}

function deriveStepStatus(
  stepId: string,
  index: number,
  pipeline: PipelineDef,
  view: ActivePipelineView | null,
): PipelineStepRunStatus {
  if (view?.pipelineId === pipeline.id && view.stepStatuses[stepId]) {
    return view.stepStatuses[stepId]
  }
  if (view?.pipelineId === pipeline.id && view.runStatus === 'running') {
    return 'waiting'
  }
  if (pipeline.last_run && (!view || view.pipelineId !== pipeline.id || view.runStatus === 'idle')) {
    return 'completed'
  }
  if (index === 0 && pipeline.active) return 'waiting'
  return 'idle'
}

function progressStats(
  pipeline: PipelineDef,
  view: ActivePipelineView | null,
): { done: number; total: number; currentLabel: string } {
  const total = pipeline.steps.length
  let done = 0
  let currentLabel = 'Sin ejecutar'
  let foundActive = false

  pipeline.steps.forEach((step, index) => {
    const status = deriveStepStatus(step.id, index, pipeline, view)
    if (status === 'completed') done += 1
    if (!foundActive && (status === 'in_progress' || status === 'waiting' || status === 'error')) {
      foundActive = true
      currentLabel = `Paso ${index + 1}: ${stepStatusLabel(status)}`
    }
  })

  if (view?.runStatus === 'success') currentLabel = 'Completado'
  else if (view?.runStatus === 'error') currentLabel = 'Falló'
  else if (view?.runStatus === 'running' && !foundActive) currentLabel = 'Ejecutando…'
  else if (!foundActive && done === total && total > 0 && pipeline.last_run) {
    currentLabel = 'Última corrida OK'
  }

  return { done, total, currentLabel }
}

export function StatusPreviewPanel({
  selectedPipeline,
  activeView,
  docPreview,
  whatsappStatus,
  whatsappPhone = null,
  googleConnected,
  pipelineCount = 0,
  onSelectPipelineHint,
  onCreatePipelineHint,
  onOpenIntegrations,
}: StatusPreviewPanelProps) {
  const waTone = whatsappTone(whatsappStatus)
  const progress = selectedPipeline ? progressStats(selectedPipeline, activeView) : null
  const progressPct =
    progress && progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0

  const { getAccessToken } = useAuth()
  const { toast, success: toastSuccess } = useToast()
  const [waSending, setWaSending] = useState(false)
  const [copiedPath, setCopiedPath] = useState(false)

  const waReady =
    whatsappStatus === 'linked' &&
    typeof whatsappPhone === 'string' &&
    whatsappPhone.length > 0

  const handleOpenDocument = useCallback(async () => {
    if (!docPreview?.path) return
    const openPath = window.desktop?.openPath
    if (openPath) {
      const result = await openPath(docPreview.path)
      if (!result.ok) {
        toast(translateErrorMessage(result.error, 'No se pudo abrir el archivo.'), 'error')
      }
      return
    }
    toast('Abrir archivos solo está disponible en la app de escritorio.', 'warning')
  }, [docPreview?.path, toast])

  const handleCopyPath = useCallback(async () => {
    if (!docPreview?.path) return
    try {
      await navigator.clipboard.writeText(docPreview.path)
      setCopiedPath(true)
      toastSuccess('Ruta copiada')
      window.setTimeout(() => setCopiedPath(false), 1800)
    } catch {
      toast('No se pudo copiar la ruta al portapapeles.', 'error')
    }
  }, [docPreview?.path, toast, toastSuccess])

  const handleShareWhatsApp = useCallback(async () => {
    if (!docPreview) return
    if (!waReady) {
      toast('WhatsApp no está vinculado. Vincúlalo en Integraciones.', 'warning')
      onOpenIntegrations?.('whatsapp')
      return
    }
    setWaSending(true)
    try {
      const result = await sendWhatsAppMedia(
        {
          path: docPreview.path,
          to: whatsappPhone!,
          caption: docPreview.filename,
          media_type: 'document',
        },
        getAccessToken,
      )
      if (result.success) {
        toastSuccess('Documento enviado por WhatsApp')
      } else {
        toast(
          translateErrorMessage(result.error, 'No se pudo enviar el documento por WhatsApp.'),
          'error',
        )
      }
    } catch {
      toast('No se pudo enviar el documento por WhatsApp. Revisa tu conexión.', 'error')
    } finally {
      setWaSending(false)
    }
  }, [
    docPreview,
    waReady,
    whatsappPhone,
    getAccessToken,
    toast,
    toastSuccess,
    onOpenIntegrations,
  ])

  const matchedView =
    selectedPipeline && activeView?.pipelineId === selectedPipeline.id ? activeView : null

  const runLabel =
    matchedView?.runStatus === 'running'
      ? 'Ejecutando ahora…'
      : matchedView?.runStatus === 'success'
        ? 'Última ejecución OK'
        : matchedView?.runStatus === 'error'
          ? 'Última ejecución falló'
          : selectedPipeline?.last_run
            ? 'Última corrida registrada'
            : 'Sin ejecuciones'

  return (
    <aside className="status-preview" aria-label="Previsualización y estado">
      <header className="status-preview__header">
        <h2 className="status-preview__title">Previsualización y Estado</h2>
        <p className="status-preview__subtitle">Documento · Pipeline · Integraciones</p>
      </header>

      {/* Documento primero — zona de preview siempre visible */}
      <section className="status-preview__section" aria-labelledby="status-preview-doc">
        <h3 id="status-preview-doc" className="status-preview__section-title">
          Documento
        </h3>
        {docPreview ? (
          <div className="status-preview__doc-card status-preview__doc-card--filled">
            <div className="status-preview__doc-row">
              <div className="status-preview__doc-thumb" aria-hidden>
                <div className="status-preview__doc-thumb-lines">
                  <span />
                  <span />
                  <span />
                  <span />
                </div>
                <span className="status-preview__doc-ext">
                  {docPreview.filename.split('.').pop()?.toUpperCase() || 'DOC'}
                </span>
              </div>
              <div className="status-preview__doc-info">
                <p className="status-preview__doc-eyebrow">Vista previa</p>
                <p className="status-preview__doc-name">{docPreview.filename}</p>
                <p className="status-preview__doc-path" title={docPreview.path}>
                  {docPreview.path}
                </p>
              </div>
            </div>
            <div className="status-preview__doc-actions">
              <button
                type="button"
                className="status-preview__integration-btn status-preview__integration-btn--primary"
                onClick={() => void handleOpenDocument()}
              >
                Abrir
              </button>
              <button
                type="button"
                className="status-preview__integration-btn"
                onClick={() => void handleShareWhatsApp()}
                disabled={waSending}
                title={
                  waReady
                    ? 'Enviar este archivo a tu WhatsApp vinculado'
                    : 'Vincula WhatsApp en Integraciones para compartir'
                }
              >
                {waSending ? 'Enviando…' : 'Compartir por WA'}
              </button>
              <button
                type="button"
                className="status-preview__integration-btn"
                onClick={() => void handleCopyPath()}
              >
                {copiedPath ? 'Copiado' : 'Copiar ruta'}
              </button>
            </div>
          </div>
        ) : (
          <div className="status-preview__doc-empty" role="status">
            <div className="status-preview__doc-empty-frame" aria-hidden>
              <div className="status-preview__doc-empty-sheet">
                <span />
                <span />
                <span />
              </div>
            </div>
            <div className="status-preview__doc-empty-copy">
              <p className="status-preview__empty-title">Sin documento aún</p>
              <p className="status-preview__empty-text">
                Exporta o genera un archivo desde el chat. La miniatura y la ruta aparecerán aquí.
              </p>
            </div>
          </div>
        )}
      </section>

      <section className="status-preview__section" aria-labelledby="status-preview-pipeline">
        <h3 id="status-preview-pipeline" className="status-preview__section-title">
          Pipeline activo
        </h3>

        {!selectedPipeline ? (
          <div className="status-preview__empty-card">
            <p className="status-preview__empty-title">
              {pipelineCount === 0 ? 'Aún no hay pipelines' : 'Ningún pipeline seleccionado'}
            </p>
            {pipelineCount === 0 ? (
              <>
                <p className="status-preview__empty-text">
                  Crea un pipeline multi-paso en el panel izquierdo para ver aquí el progreso en vivo.
                </p>
                <ol className="status-preview__howto">
                  <li>Abre <strong>Pipelines</strong> a la izquierda</li>
                  <li>Pulsa <strong>+ Pipeline multi-paso</strong></li>
                  <li>Al guardar, el progreso se muestra aquí</li>
                </ol>
                {onCreatePipelineHint ? (
                  <button type="button" className="status-preview__cta" onClick={onCreatePipelineHint}>
                    Crear pipeline
                  </button>
                ) : onSelectPipelineHint ? (
                  <button type="button" className="status-preview__cta" onClick={onSelectPipelineHint}>
                    Ir a Pipelines
                  </button>
                ) : null}
              </>
            ) : (
              <>
                <p className="status-preview__empty-text">
                  Elige un pipeline en la lista izquierda para ver pasos, barra de progreso e integraciones.
                </p>
                <ol className="status-preview__howto">
                  <li>Expande la sección <strong>Pipelines</strong></li>
                  <li>Haz clic en una tarjeta (verás el badge <strong>En panel</strong>)</li>
                  <li>Ejecuta ▶ para animar los pasos aquí</li>
                </ol>
                {onSelectPipelineHint ? (
                  <button type="button" className="status-preview__cta" onClick={onSelectPipelineHint}>
                    Ir a Pipelines
                  </button>
                ) : null}
              </>
            )}
          </div>
        ) : (
          <div
            className={`status-preview__pipeline-card${
              matchedView?.runStatus === 'running' ? ' status-preview__pipeline-card--running' : ''
            }`}
          >
            <div className="status-preview__pipeline-head">
              <div className="status-preview__pipeline-name-row">
                <span className="status-preview__pipeline-arrow" aria-hidden>
                  →
                </span>
                <span className="status-preview__pipeline-name">{selectedPipeline.name}</span>
                <span
                  className={`status-preview__badge ${selectedPipeline.active ? 'status-preview__badge--ok' : 'status-preview__badge--off'}`}
                >
                  {selectedPipeline.active ? 'Activo' : 'Pausado'}
                </span>
              </div>
              <p className="status-preview__pipeline-meta">{runLabel}</p>
              {selectedPipeline.description ? (
                <p className="status-preview__pipeline-desc">{selectedPipeline.description}</p>
              ) : null}
            </div>

            {progress && progress.total > 0 ? (
              <div className="status-preview__progress" aria-label="Progreso del pipeline">
                <div className="status-preview__progress-top">
                  <span className="status-preview__progress-count">
                    {progress.done}/{progress.total} pasos
                  </span>
                  <span className="status-preview__progress-label">{progress.currentLabel}</span>
                </div>
                <div
                  className="status-preview__progress-track"
                  role="progressbar"
                  aria-valuenow={progressPct}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <div
                    className={`status-preview__progress-fill${
                      matchedView?.runStatus === 'error'
                        ? ' status-preview__progress-fill--error'
                        : matchedView?.runStatus === 'running'
                          ? ' status-preview__progress-fill--running'
                          : ''
                    }`}
                    style={{
                      width: `${matchedView?.runStatus === 'running' ? Math.max(progressPct, 8) : progressPct}%`,
                    }}
                  />
                </div>
              </div>
            ) : null}

            {selectedPipeline.steps.length === 0 ? (
              <p className="status-preview__empty-text">Este pipeline aún no tiene pasos definidos.</p>
            ) : (
              <ol className="status-preview__steps">
                {selectedPipeline.steps.map((step, index) => {
                  const status = deriveStepStatus(step.id, index, selectedPipeline, matchedView)
                  return (
                    <li
                      key={step.id}
                      className={`status-preview__step status-preview__step--${status}`}
                    >
                      <div className="status-preview__step-rail" aria-hidden>
                        <span
                          className={`status-preview__step-index status-preview__step-index--${status}`}
                        >
                          {stepGlyph(status)}
                        </span>
                        {index < selectedPipeline.steps.length - 1 ? (
                          <span className="status-preview__step-connector" />
                        ) : null}
                      </div>
                      <div className="status-preview__step-body">
                        <div className="status-preview__step-top">
                          <span className="status-preview__step-label">Paso {index + 1}</span>
                          <span
                            className={`status-preview__step-status status-preview__step-status--${status}`}
                          >
                            {stepStatusLabel(status)}
                          </span>
                        </div>
                        <p className="status-preview__step-instruction">
                          {step.instruction || step.integration}
                        </p>
                        <span className="status-preview__step-integration">{step.integration}</span>
                      </div>
                    </li>
                  )
                })}
              </ol>
            )}

            {matchedView?.runStatus === 'error' && matchedView.errorMessage ? (
              <div className="status-preview__error-box" role="alert">
                <strong>Error</strong>
                <p>{matchedView.errorMessage}</p>
                {matchedView.errorDetails ? (
                  <details className="status-preview__error-details">
                    <summary>Ver detalles</summary>
                    <pre>{matchedView.errorDetails}</pre>
                  </details>
                ) : null}
              </div>
            ) : null}

            {matchedView?.runStatus === 'success' && matchedView.finalOutput ? (
              <div className="status-preview__output-box">
                <strong>Salida</strong>
                <p>
                  {matchedView.finalOutput.slice(0, 280)}
                  {matchedView.finalOutput.length > 280 ? '…' : ''}
                </p>
              </div>
            ) : null}
          </div>
        )}
      </section>

      <section className="status-preview__section" aria-labelledby="status-preview-integrations">
        <h3 id="status-preview-integrations" className="status-preview__section-title">
          Integraciones
        </h3>
        <div className="status-preview__integrations">
          <div className={`status-preview__integration status-preview__integration--${waTone}`}>
            <div className="status-preview__integration-top">
              <div className="status-preview__integration-identity">
                <span
                  className={`status-preview__integration-dot status-preview__integration-dot--${waTone}`}
                  aria-hidden
                />
                <span className="status-preview__integration-name">WhatsApp</span>
              </div>
              <span className={`status-preview__toggle status-preview__toggle--${waTone}`} aria-hidden>
                <span className="status-preview__toggle-knob" />
              </span>
            </div>
            <p className="status-preview__integration-hint">
              {whatsappLabel(whatsappStatus)}
              {whatsappPhone ? ` · ${whatsappPhone}` : ''} · canal para notificaciones y
              automatizaciones.
            </p>
            {onOpenIntegrations ? (
              <div className="status-preview__integration-actions">
                {whatsappStatus === 'linked' ? (
                  <button
                    type="button"
                    className="status-preview__integration-btn status-preview__integration-btn--danger"
                    onClick={() => onOpenIntegrations('whatsapp')}
                  >
                    Desvincular
                  </button>
                ) : (
                  <button
                    type="button"
                    className="status-preview__integration-btn status-preview__integration-btn--primary"
                    onClick={() => onOpenIntegrations('whatsapp')}
                  >
                    Vincular
                  </button>
                )}
                <button
                  type="button"
                  className="status-preview__integration-btn"
                  onClick={() => onOpenIntegrations('whatsapp')}
                >
                  Gestionar
                </button>
              </div>
            ) : null}
          </div>
          <div
            className={`status-preview__integration status-preview__integration--${googleConnected ? 'ok' : 'off'}`}
          >
            <div className="status-preview__integration-top">
              <div className="status-preview__integration-identity">
                <span
                  className={`status-preview__integration-dot status-preview__integration-dot--${googleConnected ? 'ok' : 'off'}`}
                  aria-hidden
                />
                <span className="status-preview__integration-name">Google</span>
              </div>
              <span
                className={`status-preview__toggle status-preview__toggle--${googleConnected ? 'ok' : 'off'}`}
                aria-hidden
              >
                <span className="status-preview__toggle-knob" />
              </span>
            </div>
            <p className="status-preview__integration-hint">
              {googleConnected ? 'Conectado' : 'Desconectado'} · Gmail y Calendar para pipelines.
            </p>
            {onOpenIntegrations ? (
              <div className="status-preview__integration-actions">
                {googleConnected ? (
                  <button
                    type="button"
                    className="status-preview__integration-btn status-preview__integration-btn--danger"
                    onClick={() => onOpenIntegrations('google')}
                  >
                    Desconectar
                  </button>
                ) : (
                  <button
                    type="button"
                    className="status-preview__integration-btn status-preview__integration-btn--primary"
                    onClick={() => onOpenIntegrations('google')}
                  >
                    Conectar
                  </button>
                )}
                <button
                  type="button"
                  className="status-preview__integration-btn"
                  onClick={() => onOpenIntegrations('google')}
                >
                  Gestionar
                </button>
              </div>
            ) : null}
          </div>
        </div>
        {onOpenIntegrations ? (
          <button
            type="button"
            className="status-preview__cta status-preview__manage-sessions"
            onClick={() => onOpenIntegrations()}
          >
            Abrir panel de sesiones
          </button>
        ) : null}
      </section>
    </aside>
  )
}
