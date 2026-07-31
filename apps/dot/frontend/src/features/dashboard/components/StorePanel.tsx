import { useState, useEffect, useCallback } from 'react'
import type { GetAccessToken } from '@/lib/api/api-client'
import { translateError } from '@/lib/error-messages'

// ─── Types ────────────────────────────────────────────

export interface StoreSkill {
  id: string
  name: string
  description: string
  instruction: string
  author_name: string
  installs_count: number
  rating: number
  created_at: string
  category: string
  backend_provisioned?: boolean
  requires_user_api_key?: boolean
  ready_to_use?: boolean
}

export interface StorePanelProps {
  open: boolean
  onClose: () => void
  getAccessToken: GetAccessToken
  installedSkillIds: Set<string>
  onInstalled: (skill: StoreSkill) => void
  onUninstalled?: (skillId: string) => void
}

const CATEGORIES = [
  { value: 'todas', label: 'Todas', icon: '📦' },
  { value: 'productividad', label: 'Productividad', icon: '⚡' },
  { value: 'finanzas', label: 'Finanzas', icon: '💰' },
  { value: 'entretenimiento', label: 'Entretenimiento', icon: '🎮' },
  { value: 'utilidades', label: 'Utilidades', icon: '🔧' },
  { value: 'noticias', label: 'Noticias', icon: '📰' },
  { value: 'clima', label: 'Clima', icon: '🌤' },
]

const CATEGORY_ICONS: Record<string, string> = {
  productividad: '⚡',
  finanzas: '💰',
  entretenimiento: '🎮',
  utilidades: '🔧',
  noticias: '📰',
  clima: '🌤',
  gmail: '📧',
  whatsapp: '💬',
  documentos: '📄',
  ia: '🤖',
  empleo: '💼',
}

function getSkillIcon(skill: StoreSkill): string {
  return CATEGORY_ICONS[skill.category.toLowerCase()] || '📦'
}

function skillBadge(skill: StoreSkill): { label: string; tone: 'ready' | 'soon' } | null {
  if (skill.requires_user_api_key) {
    return null
  }
  if (skill.backend_provisioned) {
    return skill.ready_to_use
      ? { label: 'Listo para usar', tone: 'ready' }
      : { label: 'Activación en curso', tone: 'soon' }
  }
  return { label: 'Sin configuración', tone: 'ready' }
}

export function StorePanel({
  open,
  onClose,
  getAccessToken,
  installedSkillIds,
  onInstalled,
  onUninstalled,
}: StorePanelProps) {
  const [skills, setSkills] = useState<StoreSkill[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [category, setCategory] = useState('todas')
  const [search, setSearch] = useState('')
  const [installingId, setInstallingId] = useState<string | null>(null)

  const fetchSkills = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const token = await getAccessToken()
      if (!token) {
        setError('No se pudo autenticar. Recarga la página.')
        return
      }

      const params = new URLSearchParams()
      if (category && category !== 'todas') params.set('category', category)
      if (search.trim()) params.set('search', search.trim())

      const queryString = params.toString()
      const url = `/v1/store/skills${queryString ? `?${queryString}` : ''}`

      const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
      const resp = await fetch(`${baseUrl}${url}`, {
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      })

      if (!resp.ok) {
        throw new Error('No se pudieron cargar las skills.')
      }

      const data = await resp.json()
      setSkills(data.skills || [])
    } catch (err) {
      setError(translateError(err, 'No se pudo cargar la Tienda. Intenta de nuevo.'))
      console.error('[StorePanel] fetch error:', err)
    } finally {
      setLoading(false)
    }
  }, [getAccessToken, category, search])

  useEffect(() => {
    if (open) {
      void fetchSkills()
    }
  }, [open, fetchSkills])

  const handleInstall = useCallback(async (skill: StoreSkill) => {
    setInstallingId(skill.id)
    try {
      const token = await getAccessToken()
      if (!token) return

      const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
      const resp = await fetch(`${baseUrl}/v1/store/skills/${skill.id}/install`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      })

      if (!resp.ok) {
        throw new Error('No se pudo instalar la skill.')
      }

      onInstalled(skill)
    } catch (err) {
      console.error('[StorePanel] install error:', err)
    } finally {
      setInstallingId(null)
    }
  }, [getAccessToken, onInstalled])

  const handleUninstall = useCallback(async (skillId: string) => {
    try {
      const token = await getAccessToken()
      if (!token) return

      const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
      const resp = await fetch(`${baseUrl}/v1/store/skills/${skillId}/uninstall`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      })

      if (!resp.ok) {
        throw new Error('No se pudo quitar la skill.')
      }

      onUninstalled?.(skillId)
    } catch (err) {
      console.error('[StorePanel] uninstall error:', err)
    }
  }, [getAccessToken, onUninstalled])

  if (!open) return null

  return (
    <div className="store-panel__backdrop" onClick={onClose}>
      <div className="store-panel" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="store-panel__head">
          <div>
            <h2 className="store-panel__title">Tienda DOT</h2>
            <p className="store-panel__subtitle">
              Agrega habilidades con un clic — sin claves ni pasos extra
            </p>
          </div>
          <button
            type="button"
            className="store-panel__close"
            onClick={onClose}
            aria-label="Cerrar Tienda"
          >
            ×
          </button>
        </div>

        {/* Filters */}
        <div className="store-panel__filters">
          <input
            type="text"
            className="store-panel__search"
            placeholder="Buscar habilidades..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className="store-panel__categories">
            {CATEGORIES.map((cat) => (
              <button
                key={cat.value}
                type="button"
                className={`store-panel__cat-btn ${category === cat.value ? 'store-panel__cat-btn--active' : ''}`}
                onClick={() => setCategory(cat.value)}
              >
                <span aria-hidden>{cat.icon}</span> {cat.label}
              </button>
            ))}
          </div>
        </div>

        {/* Content */}
        <div className="store-panel__content">
          {loading && (
            <div className="store-panel__state">
              <p>Cargando habilidades...</p>
            </div>
          )}

          {error && (
            <div className="store-panel__state store-panel__state--error">
              <p>{error}</p>
              <button
                type="button"
                className="store-panel__retry-btn"
                onClick={() => void fetchSkills()}
              >
                Reintentar
              </button>
            </div>
          )}

          {!loading && !error && skills.length === 0 && (
            <div className="store-panel__state">
              <span style={{ fontSize: '2rem', opacity: 0.3 }} role="img" aria-label="caja">📦</span>
              <p>No hay habilidades disponibles en esta categoría.</p>
            </div>
          )}

          {!loading && !error && skills.length > 0 && (
            <div className="store-panel__grid">
              {skills.map((skill) => {
                const installed = installedSkillIds.has(skill.id)
                const isInstalling = installingId === skill.id
                const icon = getSkillIcon(skill)
                const badge = skillBadge(skill)

                return (
                  <div key={skill.id} className="store-card">
                    <div className="store-card__body">
                      <div className="store-card__header">
                        <span className="store-card__icon" aria-hidden>{icon}</span>
                        <h3 className="store-card__name">{skill.name}</h3>
                      </div>
                      {badge ? (
                        <span
                          className={`store-card__badge store-card__badge--${badge.tone}`}
                        >
                          {badge.label}
                        </span>
                      ) : null}
                      <p className="store-card__desc">{skill.description}</p>
                      <div className="store-card__meta">
                        <span className="store-card__author">{skill.author_name}</span>
                        <span className="store-card__installs">
                          {skill.installs_count} {skill.installs_count === 1 ? 'usuario' : 'usuarios'}
                        </span>
                      </div>
                    </div>
                    <div className="store-card__footer">
                      {installed ? (
                        <button
                          type="button"
                          className="store-card__action-btn store-card__action-btn--remove"
                          onClick={() => handleUninstall(skill.id)}
                        >
                          Quitar
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="store-card__action-btn store-card__action-btn--add"
                          disabled={isInstalling}
                          onClick={() => void handleInstall(skill)}
                        >
                          {isInstalling ? 'Agregando...' : 'Agregar'}
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default StorePanel
