/**
 * Modal para crear documentos (Word, Excel, TXT) que se guardan
 * en la carpeta DOT Trabajos del escritorio del usuario.
 */
import { AnimatePresence, motion } from 'framer-motion'
import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  createDocumentTemplate,
  deleteDocumentTemplate,
  listDocumentTemplates,
  renderDocumentTemplate,
  type DocumentTemplate,
  type GenerateDocumentType,
  type TemplateDocumentType,
} from '@/lib/api/documents'
import { useDocumentGenerator } from '@/lib/documents/useDocumentGenerator'
import type { GetAccessToken } from '@/lib/api/client'

export type DocumentCreatorModalProps = {
  open: boolean
  onClose: () => void
  getAccessToken: GetAccessToken
  provider?: string | null
}

const DOCUMENT_TYPES: { value: GenerateDocumentType; label: string; icon: string }[] = [
  { value: 'docx', label: 'Word (.docx)', icon: '📄' },
  { value: 'xlsx', label: 'Excel (.xlsx)', icon: '📊' },
  { value: 'txt', label: 'Texto (.txt)', icon: '📝' },
  { value: 'pdf', label: 'PDF (.pdf)', icon: '📕' },
]

const TEMPLATE_DOCUMENT_TYPES: { value: TemplateDocumentType; label: string; icon: string }[] = [
  { value: 'docx', label: 'Word (.docx)', icon: '📄' },
  { value: 'xlsx', label: 'Excel (.xlsx)', icon: '📊' },
  { value: 'txt', label: 'Texto (.txt)', icon: '📝' },
]

export function DocumentCreatorModal({
  open,
  onClose,
  getAccessToken,
  provider,
}: DocumentCreatorModalProps) {
  const [mode, setMode] = useState<'manual' | 'template'>('manual')
  const [docType, setDocType] = useState<GenerateDocumentType>('docx')
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [templates, setTemplates] = useState<DocumentTemplate[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [templateInput, setTemplateInput] = useState('')
  const [newTemplateName, setNewTemplateName] = useState('')
  const [newTemplateType, setNewTemplateType] = useState<TemplateDocumentType>('docx')
  const [newTemplateStructure, setNewTemplateStructure] = useState('')
  const [templatesError, setTemplatesError] = useState<string | null>(null)
  const [isLoadingTemplates, setIsLoadingTemplates] = useState(false)
  const [isSavingTemplate, setIsSavingTemplate] = useState(false)
  const [isDeletingTemplate, setIsDeletingTemplate] = useState(false)
  const docGen = useDocumentGenerator(getAccessToken)

  const selectedTemplate = useMemo(
    () => templates.find((tpl) => tpl.id === selectedTemplateId) ?? null,
    [selectedTemplateId, templates],
  )

  const canGenerateManual = title.trim().length > 0 && content.trim().length > 0 && !docGen.isGenerating
  const canGenerateFromTemplate =
    selectedTemplateId.trim().length > 0 &&
    templateInput.trim().length > 0 &&
    !docGen.isGenerating &&
    !isLoadingTemplates

  const canSaveTemplate =
    newTemplateName.trim().length > 0 &&
    newTemplateStructure.trim().length > 0 &&
    !isSavingTemplate

  const loadTemplates = useCallback(() => {
    setIsLoadingTemplates(true)
    setTemplatesError(null)
    void listDocumentTemplates(getAccessToken)
      .then((res) => {
        setTemplates(res.templates ?? [])
      })
      .catch(() => {
        setTemplatesError('No pude cargar plantillas ahora. Revisa tu sesión.')
      })
      .finally(() => {
        setIsLoadingTemplates(false)
      })
  }, [getAccessToken])

  useEffect(() => {
    if (!open) return
    loadTemplates()
  }, [loadTemplates, open])

  const handleGenerate = useCallback(() => {
    if (mode === 'manual') {
      if (!canGenerateManual) return
      setTemplatesError(null)
      void docGen
        .generate({
          document_type: docType,
          title: title.trim(),
          content: content.trim(),
        })
        .then(() => {
          setTitle('')
          setContent('')
          setDocType('docx')
        })
      return
    }

    if (!canGenerateFromTemplate || !selectedTemplate) return
    setTemplatesError(null)

    void renderDocumentTemplate(
      selectedTemplate.id,
      {
        user_input: templateInput.trim(),
        provider: provider ?? undefined,
      },
      getAccessToken,
    )
      .then((rendered) =>
        docGen.generate({
          document_type: rendered.document_type,
          title: rendered.title,
          content: rendered.content,
        }),
      )
      .then(() => {
        setTemplateInput('')
      })
      .catch(() => {
        setTemplatesError(
          'No pude generar el documento desde la plantilla. Verifica estructura, datos y proveedor IA.',
        )
      })
  }, [
    canGenerateFromTemplate,
    canGenerateManual,
    content,
    docGen,
    docType,
    getAccessToken,
    mode,
    provider,
    selectedTemplate,
    templateInput,
    title,
  ])

  const handleSaveTemplate = useCallback(() => {
    if (!canSaveTemplate) return
    setTemplatesError(null)
    setIsSavingTemplate(true)
    void createDocumentTemplate(
      {
        name: newTemplateName.trim(),
        document_type: newTemplateType,
        structure: newTemplateStructure.trim(),
      },
      getAccessToken,
    )
      .then((created) => {
        setTemplates((prev) => [created, ...prev.filter((item) => item.id !== created.id)])
        setSelectedTemplateId(created.id)
        setNewTemplateName('')
        setNewTemplateStructure('')
      })
      .catch(() => {
        setTemplatesError('No pude guardar la plantilla. Verifica tu sesión.')
      })
      .finally(() => {
        setIsSavingTemplate(false)
      })
  }, [
    canSaveTemplate,
    getAccessToken,
    newTemplateName,
    newTemplateStructure,
    newTemplateType,
  ])

  const handleDeleteTemplate = useCallback(() => {
    if (!selectedTemplateId || isDeletingTemplate) return
    setTemplatesError(null)
    setIsDeletingTemplate(true)
    void deleteDocumentTemplate(selectedTemplateId, getAccessToken)
      .then(() => {
        setTemplates((prev) => prev.filter((item) => item.id !== selectedTemplateId))
        setSelectedTemplateId('')
      })
      .catch(() => {
        setTemplatesError('No pude eliminar la plantilla seleccionada.')
      })
      .finally(() => {
        setIsDeletingTemplate(false)
      })
  }, [getAccessToken, isDeletingTemplate, selectedTemplateId])

  const handleBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === e.currentTarget) onClose()
    },
    [onClose],
  )

  return (
    <AnimatePresence>
      {open ? (
        <>
          <motion.div
            key="doc-creator-backdrop"
            className="doc-creator__backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={handleBackdropClick}
          />
          <motion.div
            key="doc-creator-modal"
            className="doc-creator__modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="doc-creator-title"
            initial={{ opacity: 0, scale: 0.96, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 12 }}
            transition={{ type: 'spring', stiffness: 420, damping: 34 }}
          >
            <div className="doc-creator__head">
              <h2 id="doc-creator-title" className="doc-creator__title">
                Crear documento
              </h2>
              <button
                type="button"
                className="doc-creator__close"
                onClick={onClose}
                aria-label="Cerrar"
              >
                ×
              </button>
            </div>

            <div className="doc-creator__mode-row">
              <button
                type="button"
                className={`doc-creator__mode-btn${mode === 'manual' ? ' doc-creator__mode-btn--active' : ''}`}
                onClick={() => setMode('manual')}
              >
                Manual
              </button>
              <button
                type="button"
                className={`doc-creator__mode-btn${mode === 'template' ? ' doc-creator__mode-btn--active' : ''}`}
                onClick={() => setMode('template')}
              >
                Plantilla IA
              </button>
            </div>

            {mode === 'manual' ? (
              <>
                {/* Selector de tipo de documento */}
                <div className="doc-creator__type-grid">
                  {DOCUMENT_TYPES.map((dt) => (
                    <button
                      key={dt.value}
                      type="button"
                      className={`doc-creator__type-tile${docType === dt.value ? ' doc-creator__type-tile--active' : ''}`}
                      onClick={() => setDocType(dt.value)}
                    >
                      <span className="doc-creator__type-icon">{dt.icon}</span>
                      <span className="doc-creator__type-label">{dt.label}</span>
                    </button>
                  ))}
                </div>

                {/* Título */}
                <label className="doc-creator__field">
                  <span className="doc-creator__field-label">Título del documento</span>
                  <input
                    className="doc-creator__input"
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="Ej: Reporte mensual"
                    maxLength={200}
                  />
                </label>

                {/* Contenido */}
                <label className="doc-creator__field">
                  <span className="doc-creator__field-label">Contenido</span>
                  <textarea
                    className="doc-creator__textarea"
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    placeholder={
                      docType === 'xlsx'
                        ? 'Escribe cada fila separada por comas o pipes (|)\nEj: Nombre,Edad,Ciudad\nJuan,30,Bogotá'
                        : 'Escribe o pega el contenido aquí…'
                    }
                    rows={8}
                  />
                </label>
              </>
            ) : (
              <>
                <label className="doc-creator__field">
                  <span className="doc-creator__field-label">Plantilla guardada</span>
                  <select
                    className="doc-creator__input doc-creator__select"
                    value={selectedTemplateId}
                    onChange={(e) => setSelectedTemplateId(e.target.value)}
                    disabled={isLoadingTemplates}
                  >
                    <option value="">Selecciona una plantilla...</option>
                    {templates.map((tpl) => (
                      <option key={tpl.id} value={tpl.id}>
                        {tpl.name} ({tpl.document_type})
                      </option>
                    ))}
                  </select>
                </label>

                {selectedTemplate ? (
                  <p className="doc-creator__helper">
                    Estructura base: {selectedTemplate.structure.slice(0, 140)}
                    {selectedTemplate.structure.length > 140 ? '…' : ''}
                  </p>
                ) : null}

                <label className="doc-creator__field">
                  <span className="doc-creator__field-label">Datos para completar plantilla</span>
                  <textarea
                    className="doc-creator__textarea"
                    value={templateInput}
                    onChange={(e) => setTemplateInput(e.target.value)}
                    placeholder='Ej: Cliente ACME, monto 12.000 USD, tono formal y firma del gerente'
                    rows={6}
                  />
                </label>

                <div className="doc-creator__template-actions">
                  <button
                    type="button"
                    className="doc-creator__btn doc-creator__btn--secondary"
                    disabled={!selectedTemplateId || isDeletingTemplate}
                    onClick={handleDeleteTemplate}
                  >
                    {isDeletingTemplate ? 'Eliminando…' : 'Eliminar plantilla seleccionada'}
                  </button>
                </div>

                <div className="doc-creator__template-divider" />

                <label className="doc-creator__field">
                  <span className="doc-creator__field-label">Nueva plantilla: nombre</span>
                  <input
                    className="doc-creator__input"
                    type="text"
                    value={newTemplateName}
                    onChange={(e) => setNewTemplateName(e.target.value)}
                    placeholder="Ej: Factura comercial"
                    maxLength={120}
                  />
                </label>

                <div className="doc-creator__type-grid">
                  {TEMPLATE_DOCUMENT_TYPES.map((dt) => (
                    <button
                      key={`tpl-${dt.value}`}
                      type="button"
                      className={`doc-creator__type-tile${newTemplateType === dt.value ? ' doc-creator__type-tile--active' : ''}`}
                      onClick={() => setNewTemplateType(dt.value)}
                    >
                      <span className="doc-creator__type-icon">{dt.icon}</span>
                      <span className="doc-creator__type-label">{dt.label}</span>
                    </button>
                  ))}
                </div>

                <label className="doc-creator__field">
                  <span className="doc-creator__field-label">Estructura de plantilla</span>
                  <textarea
                    className="doc-creator__textarea"
                    value={newTemplateStructure}
                    onChange={(e) => setNewTemplateStructure(e.target.value)}
                    placeholder='Ej: Encabezado\nCliente: {{cliente}}\nDetalle: {{detalle}}\nTotal: {{total}}'
                    rows={6}
                  />
                </label>

                <button
                  type="button"
                  className="doc-creator__btn doc-creator__btn--secondary"
                  onClick={handleSaveTemplate}
                  disabled={!canSaveTemplate}
                >
                  {isSavingTemplate ? 'Guardando plantilla…' : 'Guardar nueva plantilla'}
                </button>
              </>
            )}

            {/* Feedback */}
            {templatesError ? (
              <p className="doc-creator__error">{templatesError}</p>
            ) : null}
            {docGen.error ? (
              <p className="doc-creator__error">{docGen.error}</p>
            ) : null}
            {docGen.lastResult ? (
              <p className="doc-creator__success">
                Listo: <strong>{docGen.lastResult.filename}</strong> guardado en DOT Trabajos.
              </p>
            ) : null}

            {/* Acciones */}
            <div className="doc-creator__actions">
              <button
                type="button"
                className="doc-creator__btn doc-creator__btn--secondary"
                onClick={onClose}
              >
                Cancelar
              </button>
              <button
                type="button"
                className="doc-creator__btn doc-creator__btn--primary"
                disabled={mode === 'manual' ? !canGenerateManual : !canGenerateFromTemplate}
                onClick={handleGenerate}
              >
                {docGen.isGenerating
                  ? 'Generando…'
                  : mode === 'manual'
                    ? 'Generar y guardar'
                    : 'Generar desde plantilla'}
              </button>
            </div>
          </motion.div>
        </>
      ) : null}
    </AnimatePresence>
  )
}
