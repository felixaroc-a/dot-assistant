import { useEffect, useRef, useState, useCallback } from 'react'

export type AvailableModel = {
  id: string
  provider: string
  display_name: string
  context_window: number
  capabilities: string[]
  tier: 'free' | 'standard' | 'premium'
  is_default: boolean
  cost: {
    input_1m: number
    output_1m: number
  }
}

type ModelSelectorProps = {
  currentModel: string
  availableModels: AvailableModel[]
  onSelect: (modelId: string) => void
  loading?: boolean
}

/** Íconos por proveedor (SVG inline simples) */
function providerIcon(provider: string): string {
  switch (provider.toLowerCase()) {
    case 'deepseek': return '🔵'
    case 'openai': return '🟢'
    case 'anthropic': return '🟣'
    case 'groq': return '🟠'
    case 'gemini': return '🔷'
    default: return '⚪'
  }
}

/** Etiqueta de precio $/$$/$$$ */
function priceLabel(tier: string, costOutput: number): string {
  if (tier === 'free') return 'FREE'
  if (costOutput <= 0.60) return '$'
  if (costOutput <= 3.50) return '$$'
  return '$$$'
}

/** Nombre corto del modelo para mostrar en el dropdown */
function shortModelName(displayName: string): string {
  // Remover paréntesis y acortar
  return displayName.replace(/\s*\(.*?\)\s*/g, '').trim()
}

export function ModelSelector({ currentModel, availableModels, onSelect, loading = false }: ModelSelectorProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Cerrar al hacer clic fuera
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) {
      document.addEventListener('mousedown', handler)
      return () => document.removeEventListener('mousedown', handler)
    }
  }, [open])

  const handleSelect = useCallback((modelId: string) => {
    onSelect(modelId)
    setOpen(false)
  }, [onSelect])

  const currentInfo = availableModels.find(m => m.id === currentModel)
  const selectedProvider = currentInfo?.provider || 'unknown'
  const selectedName = currentInfo ? shortModelName(currentInfo.display_name) : currentModel
  const selectedTier = currentInfo?.tier || 'standard'
  const selectedCost = currentInfo?.cost?.output_1m || 0

  return (
    <div className="model-selector" ref={ref}>
      <button
        type="button"
        className="model-selector__trigger"
        onClick={() => setOpen(!open)}
        disabled={loading}
        title={`Modelo actual: ${selectedName} (${selectedProvider})`}
      >
        <span className="model-selector__icon">
          {providerIcon(selectedProvider)}
        </span>
        <span className="model-selector__name">{selectedName}</span>
        <span className="model-selector__price model-selector__price--trigger">
          {priceLabel(selectedTier, selectedCost)}
        </span>
        <svg
          className={`model-selector__chevron ${open ? 'model-selector__chevron--open' : ''}`}
          width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {open ? (
        <div className="model-selector__dropdown">
          {availableModels.map((model) => (
            <button
              key={model.id}
              type="button"
              className={`model-selector__option ${model.id === currentModel ? 'model-selector__option--active' : ''}`}
              onClick={() => handleSelect(model.id)}
            >
              <span className="model-selector__icon">
                {providerIcon(model.provider)}
              </span>
              <span className="model-selector__option-info">
                <span className="model-selector__option-name">
                  {shortModelName(model.display_name)}
                </span>
                <span className="model-selector__option-provider">
                  {model.provider.charAt(0).toUpperCase() + model.provider.slice(1)}
                  {' · '}
                  {model.context_window >= 1000000
                    ? `${(model.context_window / 1000000).toFixed(0)}M contexto`
                    : model.context_window >= 1000
                      ? `${(model.context_window / 1000).toFixed(0)}K contexto`
                      : `${model.context_window} contexto`}
                </span>
              </span>
              <span className="model-selector__price" data-tier={model.tier}>
                {priceLabel(model.tier, model.cost.output_1m)}
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}
