import { useState, useCallback, useRef, useEffect, type DragEvent } from 'react'

import type { PipelineStep } from '@/features/dashboard/model/types'

// ─── Block definitions ───────────────────────────────

export type VisualBlockType =
  | 'trigger_time'
  | 'trigger_manual'
  | 'action_gmail'
  | 'action_whatsapp'
  | 'action_file'
  | 'action_document'
  | 'filter_contains'

export interface VisualBlock {
  id: string
  type: VisualBlockType
  label: string
  color: string
  config: Record<string, string>
}

export interface VisualPipeline {
  blocks: VisualBlock[]
}

interface BlockDefinition {
  type: VisualBlockType
  label: string
  icon: string
  color: string
  paletteLabel: string
}

const BLOCK_DEFS: BlockDefinition[] = [
  { type: 'trigger_time', label: 'Disparador: Hora/Día', icon: '🕐', color: '#6366f1', paletteLabel: 'Trigger: Hora/Día' },
  { type: 'trigger_manual', label: 'Disparador: Manual', icon: '👆', color: '#6366f1', paletteLabel: 'Trigger: Manual' },
  { type: 'action_gmail', label: 'Acción: Buscar Gmail', icon: '📧', color: '#10b981', paletteLabel: 'Acción: Buscar Gmail' },
  { type: 'action_whatsapp', label: 'Acción: Enviar WA', icon: '💬', color: '#10b981', paletteLabel: 'Acción: Enviar WA' },
  { type: 'action_file', label: 'Acción: Leer Archivo', icon: '📁', color: '#10b981', paletteLabel: 'Acción: Leer Archivo' },
  { type: 'action_document', label: 'Acción: Generar Documento', icon: '📄', color: '#10b981', paletteLabel: 'Acción: Generar Documento' },
  { type: 'filter_contains', label: 'Filtro: Si contiene...', icon: '🔍', color: '#f59e0b', paletteLabel: 'Filtro: Si contiene...' },
]

const DAY_LABELS: Record<string, string> = {
  mon: 'lunes', tue: 'martes', wed: 'miércoles', thu: 'jueves',
  fri: 'viernes', sat: 'sábado', sun: 'domingo',
}

let blockIdCounter = 0
function nextBlockId(): string {
  blockIdCounter++
  return `vb_${Date.now()}_${blockIdCounter}`
}

function blockForType(type: VisualBlockType): VisualBlock {
  const def = BLOCK_DEFS.find((d) => d.type === type)!
  return {
    id: nextBlockId(),
    type: def.type,
    label: def.label,
    color: def.color,
    config: {},
  }
}

function instructionForBlock(block: VisualBlock): string {
  const c = block.config
  switch (block.type) {
    case 'trigger_time': {
      const day = DAY_LABELS[c.day || 'mon'] || 'lunes'
      const time = c.time || '09:00'
      return `Ejecutar cada ${day} a las ${time}`
    }
    case 'trigger_manual':
      return 'Ejecutar manualmente cuando el usuario lo pida'
    case 'action_gmail':
      return c.query
        ? `Buscar en Gmail: ${c.query}`
        : 'Revisar correos nuevos en Gmail'
    case 'action_whatsapp':
      return c.message
        ? `Enviar por WhatsApp: ${c.message}`
        : 'Notificar por WhatsApp con el resultado'
    case 'action_file':
      return c.path
        ? `Leer archivo en ${c.path}`
        : 'Leer archivos locales relevantes'
    case 'action_document':
      return `Generar documento ${c.docType || 'reporte'}${c.filename ? ` (${c.filename})` : ''}`
    case 'filter_contains':
      return c.contains
        ? `Continuar solo si ${c.field || 'result'} contiene "${c.contains}"`
        : 'Continuar solo si el resultado cumple la condición'
    default:
      return block.label
  }
}

/** Convierte bloques visuales a pasos API (sin LLM). */
export function visualBlocksToSteps(blocks: VisualBlock[]): PipelineStep[] {
  return blocks.map((block, i) => {
    let type: PipelineStep['type'] = 'action'
    let integration = 'chat'
    let condition_operator: PipelineStep['condition_operator'] = 'always'
    let condition_value = ''

    switch (block.type) {
      case 'trigger_time':
      case 'trigger_manual':
        type = 'trigger'
        integration = 'chat'
        break
      case 'action_gmail':
        type = 'action'
        integration = 'gmail'
        break
      case 'action_whatsapp':
        type = 'output'
        integration = 'whatsapp'
        break
      case 'action_file':
        type = 'action'
        integration = 'file'
        break
      case 'action_document':
        type = 'action'
        integration = 'chat'
        break
      case 'filter_contains':
        type = 'condition'
        integration = 'condition'
        condition_operator = 'if_result_contains'
        condition_value = block.config.contains || ''
        break
    }

    return {
      id: `step_${i + 1}`,
      type,
      integration,
      instruction: instructionForBlock(block),
      condition_operator,
      condition_value,
      depends_on: i > 0 ? [`step_${i}`] : [],
      on_failure: type === 'condition' ? 'skip' : 'log',
      timeout_seconds: 30,
    }
  })
}

/** Resumen NL a partir de bloques visuales (fallback / auditoría). */
export function visualBlocksToNaturalLanguage(blocks: VisualBlock[]): string {
  if (blocks.length === 0) return ''
  return blocks.map((b) => instructionForBlock(b)).join('. ')
}

// ─── Text ⟷ Visual conversion ─────────────────────────

const PARSE_RULES: { pattern: RegExp; type: VisualBlockType }[] = [
  { pattern: /cada\s+(lunes|martes|miércoles|jueves|viernes|sábado|domingo|dia|día)/i, type: 'trigger_time' },
  { pattern: /(a las|a la)\s+\d{1,2}(:\d{2})?(\s*(am|pm))?/i, type: 'trigger_time' },
  { pattern: /(diario|diaria|diariamente|todos los días|semanal|semanalmente)/i, type: 'trigger_time' },
  { pattern: /(cuando ejecute|manual|cuando yo quiera)/i, type: 'trigger_manual' },
  { pattern: /(revisa|busca|buscar|lee|leer)\s+(mi\s+)?(gmail|correo|email|bandeja)/i, type: 'action_gmail' },
  { pattern: /(env[ií]a|enviar|manda|mandar|avisa|avisar|notifica)\s+.*(whatsapp|wa|mensaje)/i, type: 'action_whatsapp' },
  { pattern: /(lee|leer|abre|abrir)\s+(el\s+)?(archivo|documento|pdf|fichero)/i, type: 'action_file' },
  { pattern: /(genera|generar|crea|crear|escribe|escribir)\s+(el\s+)?(documento|docx|pdf|reporte|informe)/i, type: 'action_document' },
  { pattern: /si\s+(contiene|dice|incluye|tiene|hay)/i, type: 'filter_contains' },
]

function parseTextToVisual(text: string): VisualPipeline {
  if (!text.trim()) return { blocks: [] }
  const blocks: VisualBlock[] = []
  const addedTypes = new Set<VisualBlockType>()

  for (const rule of PARSE_RULES) {
    if (rule.pattern.test(text) && !addedTypes.has(rule.type)) {
      blocks.push(blockForType(rule.type))
      addedTypes.add(rule.type)
    }
  }

  if (blocks.length === 0) {
    blocks.push(blockForType('trigger_manual'))
  }

  return { blocks }
}

// ─── Main component ───────────────────────────────────

export interface PipelineVisualEditorProps {
  naturalLanguage: string
  onNaturalLanguageChange: (value: string) => void
  onVisualBlocksChange?: (blocks: VisualBlock[]) => void
  onModeChange?: (mode: 'text' | 'visual') => void
}

export function PipelineVisualEditor({
  naturalLanguage,
  onNaturalLanguageChange,
  onVisualBlocksChange,
  onModeChange,
}: PipelineVisualEditorProps) {
  const [mode, setMode] = useState<'text' | 'visual'>('text')
  const [visualPipeline, setVisualPipeline] = useState<VisualPipeline>(() => parseTextToVisual(naturalLanguage))
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null)

  const canvasRef = useRef<HTMLDivElement>(null)
  const dragOverCounter = useRef(0)
  const draggingBlockTypeRef = useRef<VisualBlockType | null>(null)
  const [isDragOver, setIsDragOver] = useState(false)

  useEffect(() => {
    onVisualBlocksChange?.(visualPipeline.blocks)
  }, [visualPipeline.blocks, onVisualBlocksChange])

  useEffect(() => {
    onModeChange?.(mode)
  }, [mode, onModeChange])

  const setEditorMode = useCallback((next: 'text' | 'visual') => {
    setMode(next)
    setSelectedBlockId(null)
  }, [])

  const updateBlocks = useCallback((updater: (prev: VisualBlock[]) => VisualBlock[]) => {
    setVisualPipeline((prev) => ({ blocks: updater(prev.blocks) }))
  }, [])

  const switchToVisual = useCallback(() => {
    const parsed = parseTextToVisual(naturalLanguage)
    setVisualPipeline(parsed)
    setEditorMode('visual')
  }, [naturalLanguage, setEditorMode])

  const handleDragStart = useCallback((e: DragEvent<HTMLDivElement>, blockType: VisualBlockType) => {
    draggingBlockTypeRef.current = blockType
    e.dataTransfer.setData('text/plain', blockType)
    e.dataTransfer.setData('application/visual-block-type', blockType)
    e.dataTransfer.effectAllowed = 'copy'
  }, [])

  const handleDragEnd = useCallback(() => {
    draggingBlockTypeRef.current = null
    setIsDragOver(false)
    dragOverCounter.current = 0
  }, [])

  const handleDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    e.dataTransfer.dropEffect = 'copy'
  }, [])

  const handleCanvasDragEnter = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    dragOverCounter.current++
    if (dragOverCounter.current === 1) setIsDragOver(true)
  }, [])

  const handleCanvasDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    dragOverCounter.current = Math.max(0, dragOverCounter.current - 1)
    if (dragOverCounter.current === 0) setIsDragOver(false)
  }, [])

  const resolveDroppedBlockType = useCallback((e: DragEvent<HTMLDivElement>): VisualBlockType | null => {
    const fromPlain = e.dataTransfer.getData('text/plain') as VisualBlockType
    const fromCustom = e.dataTransfer.getData('application/visual-block-type') as VisualBlockType
    const fromRef = draggingBlockTypeRef.current
    const candidate = fromPlain || fromCustom || fromRef
    if (!candidate) return null
    return BLOCK_DEFS.some((d) => d.type === candidate) ? candidate : null
  }, [])

  const addBlock = useCallback((blockType: VisualBlockType) => {
    const newBlock = blockForType(blockType)
    updateBlocks((prev) => [...prev, newBlock])
    setSelectedBlockId(newBlock.id)
  }, [updateBlocks])

  const handleDrop = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    dragOverCounter.current = 0
    setIsDragOver(false)
    const blockType = resolveDroppedBlockType(e)
    draggingBlockTypeRef.current = null
    if (!blockType) return
    addBlock(blockType)
  }, [resolveDroppedBlockType, addBlock])

  const handleBlockClick = useCallback((blockId: string) => {
    setSelectedBlockId((prev) => (prev === blockId ? null : blockId))
  }, [])

  const handleRemoveBlock = useCallback((blockId: string) => {
    updateBlocks((prev) => prev.filter((b) => b.id !== blockId))
    setSelectedBlockId(null)
  }, [updateBlocks])

  const handleConfigChange = useCallback((blockId: string, key: string, value: string) => {
    updateBlocks((prev) =>
      prev.map((b) =>
        b.id === blockId ? { ...b, config: { ...b.config, [key]: value } } : b,
      ),
    )
  }, [updateBlocks])

  const selectedBlock = visualPipeline.blocks.find((b) => b.id === selectedBlockId)

  return (
    <div className="pve">
      <div className="pve__mode-bar">
        <span className="pve__mode-label">Editor de Pipeline</span>
        <div className="pve__toggle-group">
          <button
            type="button"
            className={`pve__toggle-btn ${mode === 'text' ? 'pve__toggle-btn--active' : ''}`}
            onClick={() => setEditorMode('text')}
          >
            Texto
          </button>
          <button
            type="button"
            className={`pve__toggle-btn ${mode === 'visual' ? 'pve__toggle-btn--active' : ''}`}
            onClick={switchToVisual}
          >
            Visual
          </button>
        </div>
      </div>

      {mode === 'text' && (
        <div className="pve__text-mode">
          <p className="pve__hint">
            Describe lo que quieres automatizar. DOT lo convierte en pasos al crear el pipeline.
          </p>
          <textarea
            className="pve__textarea"
            value={naturalLanguage}
            onChange={(e) => onNaturalLanguageChange(e.target.value)}
            placeholder="Ej: cada lunes revisa mi Gmail, si hay PDFs guárdalos y avísame por WhatsApp"
            rows={4}
          />
        </div>
      )}

      {mode === 'visual' && (
        <div className="pve__visual-layout">
          <div className="pve__palette">
            <h4 className="pve__palette-title">Bloques</h4>
            <div className="pve__palette-list">
              {BLOCK_DEFS.map((def) => (
                <div
                  key={def.type}
                  className="pve__palette-block"
                  draggable
                  onDragStart={(e) => handleDragStart(e, def.type)}
                  onDragEnd={handleDragEnd}
                  onClick={() => addBlock(def.type)}
                  title="Clic o arrastra al flujo"
                >
                  <span className="pve__palette-icon">{def.icon}</span>
                  <span className="pve__palette-text">{def.paletteLabel}</span>
                </div>
              ))}
            </div>
          </div>

          <div
            ref={canvasRef}
            className={`pve__canvas${isDragOver ? ' pve__canvas--drag-over' : ''}`}
            onDragOver={handleDragOver}
            onDragEnter={handleCanvasDragEnter}
            onDragLeave={handleCanvasDragLeave}
            onDrop={handleDrop}
          >
            {visualPipeline.blocks.length === 0 ? (
              <div className="pve__canvas-empty">
                <p>Clic en un bloque o arrástralo aquí para armar el flujo</p>
              </div>
            ) : (
              <div className="pve__canvas-blocks">
                {visualPipeline.blocks.map((block, index) => (
                  <div key={block.id} className="pve__canvas-step">
                    {index > 0 ? <div className="pve__canvas-connector" aria-hidden /> : null}
                    <div
                      className={`pve__canvas-block ${selectedBlockId === block.id ? 'pve__canvas-block--selected' : ''}`}
                      style={{ '--block-accent': block.color } as React.CSSProperties}
                      onClick={() => handleBlockClick(block.id)}
                    >
                      <div className="pve__canvas-block-header">
                        <span className="pve__canvas-block-num">{index + 1}</span>
                        <span className="pve__canvas-block-label">{block.label}</span>
                        <button
                          type="button"
                          className="pve__canvas-block-remove"
                          onClick={(e) => { e.stopPropagation(); handleRemoveBlock(block.id) }}
                          title="Eliminar bloque"
                        >
                          ×
                        </button>
                      </div>
                      {selectedBlockId === block.id && selectedBlock ? (
                        <div
                          className="pve__config pve__config--inline"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {selectedBlock.type === 'trigger_time' && (
                            <>
                              <label className="pve__config-field">
                                <span>Día</span>
                                <select
                                  className="pve__config-input"
                                  value={selectedBlock.config.day || 'mon'}
                                  onChange={(e) => handleConfigChange(selectedBlock.id, 'day', e.target.value)}
                                >
                                  <option value="mon">Lunes</option>
                                  <option value="tue">Martes</option>
                                  <option value="wed">Miércoles</option>
                                  <option value="thu">Jueves</option>
                                  <option value="fri">Viernes</option>
                                  <option value="sat">Sábado</option>
                                  <option value="sun">Domingo</option>
                                </select>
                              </label>
                              <label className="pve__config-field">
                                <span>Hora</span>
                                <input
                                  type="time"
                                  className="pve__config-input"
                                  value={selectedBlock.config.time || '09:00'}
                                  onChange={(e) => handleConfigChange(selectedBlock.id, 'time', e.target.value)}
                                />
                              </label>
                            </>
                          )}
                          {selectedBlock.type === 'action_gmail' && (
                            <label className="pve__config-field">
                              <span>Buscar</span>
                              <input
                                type="text"
                                className="pve__config-input"
                                value={selectedBlock.config.query || ''}
                                onChange={(e) => handleConfigChange(selectedBlock.id, 'query', e.target.value)}
                                placeholder="Ej. factura OR invoice"
                              />
                            </label>
                          )}
                          {selectedBlock.type === 'action_whatsapp' && (
                            <label className="pve__config-field">
                              <span>Mensaje</span>
                              <input
                                type="text"
                                className="pve__config-input"
                                value={selectedBlock.config.message || ''}
                                onChange={(e) => handleConfigChange(selectedBlock.id, 'message', e.target.value)}
                                placeholder="Ej. Resumen de la semana"
                              />
                            </label>
                          )}
                          {selectedBlock.type === 'action_file' && (
                            <label className="pve__config-field">
                              <span>Ruta</span>
                              <input
                                type="text"
                                className="pve__config-input"
                                value={selectedBlock.config.path || ''}
                                onChange={(e) => handleConfigChange(selectedBlock.id, 'path', e.target.value)}
                                placeholder="Ej. Escritorio/factura.pdf"
                              />
                            </label>
                          )}
                          {selectedBlock.type === 'action_document' && (
                            <>
                              <label className="pve__config-field">
                                <span>Tipo</span>
                                <select
                                  className="pve__config-input"
                                  value={selectedBlock.config.docType || 'reporte'}
                                  onChange={(e) => handleConfigChange(selectedBlock.id, 'docType', e.target.value)}
                                >
                                  <option value="reporte">Reporte</option>
                                  <option value="carta">Carta</option>
                                  <option value="cv">CV</option>
                                  <option value="factura">Factura</option>
                                  <option value="presupuesto">Presupuesto</option>
                                </select>
                              </label>
                              <label className="pve__config-field">
                                <span>Archivo</span>
                                <input
                                  type="text"
                                  className="pve__config-input"
                                  value={selectedBlock.config.filename || ''}
                                  onChange={(e) => handleConfigChange(selectedBlock.id, 'filename', e.target.value)}
                                  placeholder="Ej. reporte_semanal"
                                />
                              </label>
                            </>
                          )}
                          {selectedBlock.type === 'filter_contains' && (
                            <>
                              <label className="pve__config-field">
                                <span>Campo</span>
                                <select
                                  className="pve__config-input"
                                  value={selectedBlock.config.field || 'result'}
                                  onChange={(e) => handleConfigChange(selectedBlock.id, 'field', e.target.value)}
                                >
                                  <option value="result">Resultado</option>
                                  <option value="subject">Asunto</option>
                                  <option value="body">Contenido</option>
                                  <option value="filename">Nombre archivo</option>
                                </select>
                              </label>
                              <label className="pve__config-field">
                                <span>Contiene</span>
                                <input
                                  type="text"
                                  className="pve__config-input"
                                  value={selectedBlock.config.contains || ''}
                                  onChange={(e) => handleConfigChange(selectedBlock.id, 'contains', e.target.value)}
                                  placeholder="Ej. factura"
                                />
                              </label>
                            </>
                          )}
                          {selectedBlock.type === 'trigger_manual' && (
                            <p className="pve__config-hint">Se activa solo al ejecutarlo. Sin config extra.</p>
                          )}
                        </div>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default PipelineVisualEditor
