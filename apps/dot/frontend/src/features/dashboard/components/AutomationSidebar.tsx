import { useCallback, useEffect, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'

import { getIntegrationById } from '@/features/integrations'

import type { PipelineDef, PipelineTemplate, SavedAutomation } from '@/features/dashboard/model/types'
import { PipelineCard } from './automations/PipelineCard'
import { PipelineTemplateCard } from './automations/PipelineTemplateCard'

export type AutomationSidebarProps = {
  automations: SavedAutomation[]
  onOpenDrawer: () => void
  onOpenDocumentCreator: () => void
  onOpenStore?: () => void
  onToggleActive?: (id: string) => void
  onExecuteNow?: (id: string) => void
  onEdit?: (id: string) => void
  hasPendingResults?: boolean
  onViewResults?: () => void

  // C2: Pipelines
  pipelines?: PipelineDef[]
  selectedPipelineId?: string | null
  onSelectPipeline?: (id: string) => void
  onOpenPipelineEditor?: () => void
  onPipelineExecute?: (id: string) => void
  onPipelineToggleActive?: (id: string) => void
  onPipelineEdit?: (id: string) => void
  onPipelineDelete?: (id: string) => void
  onPipelineSaveAsTemplate?: (pipeline: PipelineDef) => void

  // C3: Pipeline Templates
  templates?: PipelineTemplate[]
  onCloneTemplate?: (id: string) => void
  cloningTemplateId?: string | null
  loadingTemplates?: boolean

  /** Incrementar para expandir Pipelines y hacer scroll a esa sección. */
  focusPipelinesNonce?: number
}

type AutomationListItemProps = {
  item: SavedAutomation
  onToggleActive?: (id: string) => void
  onExecuteNow?: (id: string) => void
  onEdit?: (id: string) => void
}

function AutomationListItem({ item, onToggleActive, onExecuteNow, onEdit }: AutomationListItemProps) {
  const reduceMotion = useReducedMotion()
  const meta = getIntegrationById(item.integrationId)

  return (
    <motion.li
      className="main-dashboard__list-item"
      initial={reduceMotion ? false : { opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.22 }}
      layout
    >
      <span className="main-dashboard__list-icon" aria-hidden>
        {meta.logoSrc ? <img src={meta.logoSrc} alt="" draggable={false} /> : <span className="main-dashboard__list-placeholder">•</span>}
      </span>
      <div className="main-dashboard__list-text-group">
        <p className="main-dashboard__list-text">{item.name}</p>
        <span className={`main-dashboard__auto-badge ${item.active ? 'main-dashboard__auto-badge--active' : 'main-dashboard__auto-badge--inactive'}`}>
          {item.active ? 'Activo' : 'Inactivo'}
        </span>
      </div>
      <div className="main-dashboard__list-actions">
        {item.active ? (
          <button type="button" className="main-dashboard__list-action-btn" onClick={(e) => { e.stopPropagation(); onExecuteNow?.(item.id) }} title="Ejecutar ahora" aria-label={`Ejecutar ${item.name}`}>▶</button>
        ) : null}
        <button type="button" className="main-dashboard__list-action-btn" onClick={(e) => { e.stopPropagation(); onToggleActive?.(item.id) }} aria-label={item.active ? 'Desactivar automatización' : 'Activar automatización'}>
          {item.active ? '⏸' : '▶'}
        </button>
        {onEdit ? (
          <button
            type="button"
            className="main-dashboard__list-action-btn"
            onClick={(e) => { e.stopPropagation(); onEdit(item.id) }}
            title="Editar"
            aria-label={`Editar ${item.name}`}
          >
            ✎
          </button>
        ) : null}
      </div>
    </motion.li>
  )
}

type SidebarSectionId = 'automations' | 'documents' | 'pipelines' | 'templates'

export function AutomationSidebar({
  automations,
  onOpenDrawer,
  onOpenDocumentCreator,
  onOpenStore,
  onToggleActive,
  onExecuteNow,
  onEdit,
  hasPendingResults,
  onViewResults,
  // C2: Pipelines
  pipelines = [],
  selectedPipelineId = null,
  onSelectPipeline,
  onOpenPipelineEditor,
  onPipelineExecute,
  onPipelineToggleActive,
  onPipelineEdit,
  onPipelineDelete,
  onPipelineSaveAsTemplate,
  // C3: Templates
  templates = [],
  onCloneTemplate,
  cloningTemplateId = null,
  loadingTemplates = false,
  focusPipelinesNonce = 0,
}: AutomationSidebarProps) {
  const reduceMotion = useReducedMotion()
  const pipelinesBlockRef = useRef<HTMLDivElement>(null)
  const [collapsed, setCollapsed] = useState<Record<SidebarSectionId, boolean>>({
    automations: false,
    documents: true,
    pipelines: false,
    templates: true,
  })

  const toggleSection = useCallback((id: SidebarSectionId) => {
    setCollapsed((prev) => ({ ...prev, [id]: !prev[id] }))
  }, [])

  useEffect(() => {
    if (!focusPipelinesNonce) return
    setCollapsed((prev) => ({ ...prev, pipelines: false }))
    const id = window.setTimeout(() => {
      pipelinesBlockRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }, 40)
    return () => window.clearTimeout(id)
  }, [focusPipelinesNonce])

  return (
    <aside className="main-dashboard__sidebar" aria-label="Panel de control">
      <div className="main-dashboard__sidebar-brand">
        <span className="main-dashboard__sidebar-brand-label">Panel de control</span>
      </div>

      {/* ── Sección AUTOMATIZACIONES ── */}
      <div className={`main-dashboard__sidebar-block${collapsed.automations ? ' main-dashboard__sidebar-block--collapsed' : ''}`}>
        <button
          type="button"
          className="main-dashboard__sidebar-section-toggle"
          onClick={() => toggleSection('automations')}
          aria-expanded={!collapsed.automations}
        >
          <h2 className="main-dashboard__sidebar-title">Automatizaciones</h2>
          <span className="main-dashboard__sidebar-chevron" aria-hidden>
            {collapsed.automations ? '+' : '−'}
          </span>
        </button>
        {!collapsed.automations ? (
          <>
            <button
              type="button"
              className="main-dashboard__sidebar-btn main-dashboard__sidebar-btn--accent"
              onClick={onOpenDrawer}
            >
              ¿Qué quieres automatizar?
            </button>

            {hasPendingResults ? (
              <motion.button
                type="button"
                className="main-dashboard__pending-results"
                onClick={onViewResults}
                initial={reduceMotion ? false : { scale: 0.98, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ duration: 0.22 }}
              >
                <span className="main-dashboard__pending-dot" />
                Resultados nuevos
              </motion.button>
            ) : null}

            <div className="main-dashboard__sidebar-scroll">
              {automations.length === 0 ? (
                <p className="main-dashboard__sidebar-empty">Aún no hay automatizaciones guardadas.</p>
              ) : (
                automations.map((item) => (
                  <AutomationListItem
                    key={item.id}
                    item={item}
                    onToggleActive={onToggleActive}
                    onExecuteNow={onExecuteNow}
                    onEdit={onEdit}
                  />
                ))
              )}
            </div>
          </>
        ) : null}
      </div>

      {/* ── Sección DOCUMENTOS ── */}
      <div className={`main-dashboard__sidebar-block${collapsed.documents ? ' main-dashboard__sidebar-block--collapsed' : ''}`}>
        <button
          type="button"
          className="main-dashboard__sidebar-section-toggle"
          onClick={() => toggleSection('documents')}
          aria-expanded={!collapsed.documents}
        >
          <h2 className="main-dashboard__sidebar-title">Documentos</h2>
          <span className="main-dashboard__sidebar-chevron" aria-hidden>
            {collapsed.documents ? '+' : '−'}
          </span>
        </button>
        {!collapsed.documents ? (
          <button type="button" className="main-dashboard__sidebar-btn" onClick={onOpenDocumentCreator}>
            + Crear documento
          </button>
        ) : null}
      </div>

      {/* ── C2: Sección PIPELINES ── */}
      <div
        ref={pipelinesBlockRef}
        className={`main-dashboard__sidebar-block${collapsed.pipelines ? ' main-dashboard__sidebar-block--collapsed' : ''}`}
      >
        <button
          type="button"
          className="main-dashboard__sidebar-section-toggle"
          onClick={() => toggleSection('pipelines')}
          aria-expanded={!collapsed.pipelines}
        >
          <h2 className="main-dashboard__sidebar-title">Pipelines</h2>
          <span className="main-dashboard__sidebar-chevron" aria-hidden>
            {collapsed.pipelines ? '+' : '−'}
          </span>
        </button>
        {!collapsed.pipelines ? (
          <>
            <button
              type="button"
              className="main-dashboard__sidebar-btn main-dashboard__sidebar-btn--pipeline"
              onClick={onOpenPipelineEditor}
            >
              + Pipeline multi-paso
            </button>
            <p className="main-dashboard__sidebar-hint">
              Selecciona un pipeline para ver su progreso a la derecha.
            </p>

            <div className="main-dashboard__sidebar-scroll">
              {pipelines.length === 0 ? (
                <p className="main-dashboard__sidebar-empty">
                  Aún no hay pipelines. Crea uno con varios pasos encadenados.
                </p>
              ) : (
                pipelines.map((pipeline) => (
                  <PipelineCard
                    key={pipeline.id}
                    pipeline={pipeline}
                    selected={selectedPipelineId === pipeline.id}
                    onSelect={onSelectPipeline}
                    onExecuteNow={onPipelineExecute}
                    onToggleActive={onPipelineToggleActive}
                    onEdit={onPipelineEdit}
                    onDelete={onPipelineDelete}
                    onSaveAsTemplate={onPipelineSaveAsTemplate}
                  />
                ))
              )}
            </div>
          </>
        ) : null}
      </div>

      {/* ── C05: Sección TIENDA ── */}
      {onOpenStore ? (
        <div className="main-dashboard__sidebar-block" style={{ marginTop: '0.25rem' }}>
          <button
            type="button"
            className="main-dashboard__sidebar-btn main-dashboard__sidebar-btn--accent"
            onClick={onOpenStore}
            style={{
              background: 'linear-gradient(135deg, rgba(255,255,255,0.08), rgba(255,255,255,0.04))',
              color: 'var(--dash-text-primary)',
              border: '1px solid var(--dash-border)',
              fontWeight: 500,
              display: 'flex',
              alignItems: 'center',
              gap: '0.45rem',
            }}
          >
            <span aria-hidden style={{ fontSize: '1.05rem' }}>🛍️</span> Tienda DOT
          </button>
        </div>
      ) : null}

      {/* ── C3: Sección PLANTILLAS ── */}
      <div className={`main-dashboard__sidebar-block${collapsed.templates ? ' main-dashboard__sidebar-block--collapsed' : ''}`}>
        <button
          type="button"
          className="main-dashboard__sidebar-section-toggle"
          onClick={() => toggleSection('templates')}
          aria-expanded={!collapsed.templates}
        >
          <h2 className="main-dashboard__sidebar-title">Plantillas</h2>
          <span className="main-dashboard__sidebar-chevron" aria-hidden>
            {collapsed.templates ? '+' : '−'}
          </span>
        </button>
        {!collapsed.templates ? (
          <>
            <p className="main-dashboard__sidebar-hint">
              Automatizaciones listas para usar. Clona una y personalízala.
            </p>

            <div className="main-dashboard__sidebar-scroll">
              {loadingTemplates ? (
                <p className="main-dashboard__sidebar-empty">Cargando plantillas...</p>
              ) : templates.length === 0 ? (
                <p className="main-dashboard__sidebar-empty">
                  No hay plantillas disponibles todavía.
                </p>
              ) : (
                templates.map((template) => (
                  <PipelineTemplateCard
                    key={template.id}
                    template={template}
                    onClone={onCloneTemplate ?? (() => {})}
                    cloning={cloningTemplateId === template.id}
                  />
                ))
              )}
            </div>
          </>
        ) : null}
      </div>
    </aside>
  )
}
