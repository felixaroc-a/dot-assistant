import { useEffect, useMemo, useState } from 'react'

import type { ProviderBreakdownItem, UsageDailyItem, UsageSummary } from '@/lib/api/usage'
import { UsageRechargeGuide } from '@/features/dashboard/components/UsageRechargeGuide'
import {
  USAGE_WARNING_MESSAGE,
  USAGE_WARNING_THRESHOLD_PERCENT,
  usageRemainingPercent,
} from '@/lib/usage-messages'


/** Label por proveedor para mostrar en UI */
function providerLabel(provider: string): string {
  const labels: Record<string, string> = {
    deepseek: 'DeepSeek',
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    groq: 'Groq',
    gemini: 'Gemini',
  }
  return labels[provider.toLowerCase()] || provider
}

/** Color por proveedor */
function providerColor(provider: string): string {
  const colors: Record<string, string> = {
    deepseek: '#4caf50',
    gemini: '#2196F3',
    openai: '#ff9800',
    anthropic: '#9c27b0',
    groq: '#00bcd4',
  }
  return colors[provider.toLowerCase()] || '#888'
}

export type UsageMeterProps = {
  summary: UsageSummary | null
  loading?: boolean
  error?: string | null
  detailed?: boolean
  dailyHistory?: UsageDailyItem[] | null
}

function usageColor(percent: number): string {
  if (percent < 50) return 'var(--usage-green)'
  if (percent <= USAGE_WARNING_THRESHOLD_PERCENT) return 'var(--usage-yellow)'
  return 'var(--usage-red)'
}

function formatDayLabel(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString('es-ES', { weekday: 'short' }).slice(0, 3)
}

/** Animated number counter (de 0 al valor objetivo) */
function AnimatedNumber({ value, suffix = '', decimals = 0 }: { value: number; suffix?: string; decimals?: number }) {
  const [display, setDisplay] = useState(0)

  useEffect(() => {
    if (value === 0) {
      setDisplay(0)
      return
    }
    const duration = 600
    const start = performance.now()
    const from = display
    const to = value
    let raf: number

    const step = (now: number) => {
      const elapsed = now - start
      const progress = Math.min(elapsed / duration, 1)
      const eased = 1 - (1 - progress) ** 3
      setDisplay(from + (to - from) * eased)
      if (progress < 1) {
        raf = requestAnimationFrame(step)
      }
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  return <span>{display.toFixed(decimals)}{suffix}</span>
}

/** Solo % al usuario: no exponer dólares ni tope en USD (secreto de negocio). */
export function UsageMeter({ summary, loading = false, error = null, detailed = false, dailyHistory = null }: UsageMeterProps) {
  const percent = summary?.consumed_percent ?? 0
  const remainingPercent = usageRemainingPercent(percent)
  const color = usageColor(percent)
  const blocked = Boolean(summary?.blocked || percent >= 100)

  const breakdownTooltip = useMemo(() => {
    if (!summary?.breakdown) return undefined
    const { chat_usd, reasoning_usd, vision_usd, image_usd } = summary.breakdown
    const total =
      Number(chat_usd || 0) +
      Number(reasoning_usd || 0) +
      Number(vision_usd || 0) +
      Number(image_usd || 0)
    if (total <= 0) return undefined
    const parts: string[] = []
    if (Number(chat_usd) > 0) parts.push('Chat')
    if (Number(reasoning_usd) > 0) parts.push('Razonamiento')
    if (Number(vision_usd) > 0) parts.push('Visión')
    if (Number(image_usd) > 0) parts.push('Imágenes')
    return parts.length ? `Incluye: ${parts.join(', ')}` : undefined
  }, [summary?.breakdown])

  const hasDailyData = dailyHistory && dailyHistory.length > 0
  const maxDaily = hasDailyData ? Math.max(...dailyHistory.map(d => d.usd), 0.01) : 0

  if (loading && !summary) {
    return (
      <div className="usage-meter" role="status" aria-live="polite" aria-busy="true">
        <div className="usage-meter__header">
          <span className="usage-meter__label usage-meter__label--dim">Consumo IA</span>
        </div>
        <div className="usage-meter__bar">
          <div className="usage-meter__skeleton">
            <div className="usage-meter__skeleton-shimmer" />
          </div>
        </div>
        <span className="usage-meter__text usage-meter__text--dim">Cargando…</span>
      </div>
    )
  }

  if (error && !summary) {
    return (
      <div className="usage-meter" role="status" aria-live="polite">
        <div className="usage-meter__header">
          <span className="usage-meter__label usage-meter__label--dim">Consumo IA</span>
        </div>
        <div className="usage-meter__bar usage-meter__bar--error">
          <div className="usage-meter__fill usage-meter__fill--none" />
        </div>
        <span className="usage-meter__text usage-meter__text--dim">--</span>
      </div>
    )
  }

  const footerHint = blocked
    ? null
    : percent >= USAGE_WARNING_THRESHOLD_PERCENT
      ? USAGE_WARNING_MESSAGE
      : percent <= 0
        ? 'Sin uso este mes'
        : `Queda ${remainingPercent}% del plan mensual`

  return (
    <div
      className="usage-meter"
      role="progressbar"
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={`Consumo IA: ${percent}% usado, queda ${remainingPercent}%`}
    >
      <div className="usage-meter__header">
        <span className="usage-meter__label">Consumo IA</span>
        <span className="usage-meter__percent" style={{ color }}>
          <AnimatedNumber value={percent} suffix="%" />
        </span>
      </div>

      <div className="usage-meter__bar" title={breakdownTooltip}>
        <div
          className="usage-meter__fill usage-meter__fill--animated"
          style={{
            width: `${Math.min(percent, 100)}%`,
            backgroundColor: color,
          }}
        />
      </div>

      {/* OB04: Mini chart de consumo diario últimos 7 días */}
      {detailed && hasDailyData ? (
        <div className="usage-meter__daily-chart">
          <span className="usage-meter__daily-chart-title">Últimos 7 días</span>
          <div className="usage-meter__daily-bars">
            {dailyHistory.map((day) => {
              const barHeight = maxDaily > 0 ? (day.usd / maxDaily) * 100 : 0
              return (
                <div
                  key={day.date}
                  className="usage-meter__daily-bar-wrap"
                  title={`${formatDayLabel(day.date)}: $${day.usd.toFixed(4)}`}
                >
                  <div
                    className="usage-meter__daily-bar"
                    style={{ height: `${Math.max(barHeight, 4)}%`, backgroundColor: color }}
                  />
                  <span className="usage-meter__daily-bar-label">{formatDayLabel(day.date)}</span>
                </div>
              )
            })}
          </div>
        </div>
      ) : null}

      <div className="usage-meter__footer">
        {!blocked && percent > 0 && percent < USAGE_WARNING_THRESHOLD_PERCENT ? (
          <span className="usage-meter__remaining">Queda {remainingPercent}%</span>
        ) : null}
        {blocked ? (
          <UsageRechargeGuide variant="meter" />
        ) : (
          <span className="usage-meter__text">{footerHint}</span>
        )}
      </div>

      {/* OB04: Proyección de agotamiento */}
      {summary?.projected_depletion_date && percent < 100 ? (
        <div className="usage-meter__projection">
          <span className="usage-meter__projection-icon">&#9200;</span>
          <span className="usage-meter__projection-text">
            A este ritmo, tu saldo alcanza hasta el {summary.projected_depletion_date}
          </span>
        </div>
      ) : null}

      {detailed && summary?.breakdown ? (
        <div className="usage-meter__breakdown">
          <span className="usage-meter__breakdown-title">Desglose estimado</span>
          <div className="usage-meter__breakdown-items">
            {Number(summary.breakdown.chat_usd) > 0 ? (
              <div className="usage-meter__breakdown-item">
                <span className="usage-meter__breakdown-label">Chat</span>
                <span className="usage-meter__breakdown-value">${Number(summary.breakdown.chat_usd).toFixed(4)}</span>
              </div>
            ) : null}
            {Number(summary.breakdown.reasoning_usd) > 0 ? (
              <div className="usage-meter__breakdown-item">
                <span className="usage-meter__breakdown-label">Razonamiento</span>
                <span className="usage-meter__breakdown-value">${Number(summary.breakdown.reasoning_usd).toFixed(4)}</span>
              </div>
            ) : null}
            {Number(summary.breakdown.vision_usd) > 0 ? (
              <div className="usage-meter__breakdown-item">
                <span className="usage-meter__breakdown-label">Visión</span>
                <span className="usage-meter__breakdown-value">${Number(summary.breakdown.vision_usd).toFixed(4)}</span>
              </div>
            ) : null}
            {Number(summary.breakdown.image_usd) > 0 ? (
              <div className="usage-meter__breakdown-item">
                <span className="usage-meter__breakdown-label">Imágenes</span>
                <span className="usage-meter__breakdown-value">${Number(summary.breakdown.image_usd).toFixed(4)}</span>
              </div>
            ) : null}
          </div>

          {/* Per-provider breakdown */}
          {summary.provider_breakdown && summary.provider_breakdown.length > 0 ? (
            <div className="usage-meter__provider-breakdown">
              <span className="usage-meter__breakdown-title">Por proveedor</span>
              <div className="usage-meter__breakdown-items">
                {summary.provider_breakdown.map((pb: ProviderBreakdownItem) => {
                  const totalAll = summary.provider_breakdown!.reduce(
                    (acc: number, p: ProviderBreakdownItem) => acc + (p.total_usd || 0), 0
                  )
                  const pct = totalAll > 0 ? ((pb.total_usd || 0) / totalAll) * 100 : 0
                  return (
                    <div key={pb.provider} className="usage-meter__provider-item">
                      <div className="usage-meter__provider-item-header">
                        <span
                          className="usage-meter__provider-dot"
                          style={{ backgroundColor: providerColor(pb.provider) }}
                        />
                        <span className="usage-meter__breakdown-label">{providerLabel(pb.provider)}</span>
                        <span className="usage-meter__breakdown-value">
                          ${(pb.total_usd || 0).toFixed(4)}
                        </span>
                      </div>
                      <div className="usage-meter__provider-bar">
                        <div
                          className="usage-meter__provider-bar-fill"
                          style={{
                            width: `${Math.max(pct, 1)}%`,
                            backgroundColor: providerColor(pb.provider),
                          }}
                        />
                      </div>
                      {pb.models && Object.keys(pb.models).length > 0 ? (
                        <div className="usage-meter__provider-models">
                          {Object.entries(pb.models)
                            .filter(([, cost]) => (cost as number) > 0)
                            .map(([model, cost]) => (
                              <span key={model} className="usage-meter__provider-model">
                                {model}: ${(cost as number).toFixed(4)}
                              </span>
                            ))}
                        </div>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            </div>
          ) : null}

          <div className="usage-meter__breakdown-footer">
            <span className="usage-meter__breakdown-total">
              Total: ${Number(summary.consumed_usd || 0).toFixed(4)} de ${Number(summary.limit_usd || 7.50).toFixed(2)}
            </span>
          </div>
        </div>
      ) : null}
    </div>
  )
}
