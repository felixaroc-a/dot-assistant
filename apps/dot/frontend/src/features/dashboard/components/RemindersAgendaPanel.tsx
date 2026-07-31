import { useCallback, useState } from 'react'

import type { ReminderItem } from '@/features/dashboard/hooks/useRemindersPanel'
import type { AgendaSidebarEvent } from '@/features/dashboard/hooks/useAgendaSidebar'

export type RemindersAgendaPanelProps = {
  reminders: ReminderItem[]
  remindersLoading: boolean
  remindersError: string | null
  onDismissReminder: (id: string) => Promise<void>
  onSnoozeReminder: (id: string, text: string, minutes: number) => Promise<void>
  agendaLinked: boolean
  agendaEvents: AgendaSidebarEvent[]
  agendaLoading: boolean
  agendaError: string | null
  agendaMessage: string | null
  onOpenIntegrations?: (focus?: 'whatsapp' | 'google') => void
}

const SNOOZE_OPTIONS = [
  { label: '15 min', minutes: 15 },
  { label: '1 h', minutes: 60 },
  { label: 'Mañana 9:00', minutes: -1 },
] as const

function formatEventTime(raw: string | null): string {
  if (!raw) return 'Sin hora'
  try {
    const normalized = raw.replace('Z', '+00:00')
    const dt = new Date(normalized)
    if (Number.isNaN(dt.getTime())) return raw
    return dt.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return raw
  }
}

function formatReminderDue(iso: string): string {
  if (!iso) return ''
  try {
    const dt = new Date(iso.replace('Z', '+00:00'))
    if (Number.isNaN(dt.getTime())) return iso
    return dt.toLocaleString('es-ES', {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function minutesUntilTomorrowNine(): number {
  const now = new Date()
  const target = new Date(now)
  target.setDate(target.getDate() + 1)
  target.setHours(9, 0, 0, 0)
  return Math.max(1, Math.round((target.getTime() - now.getTime()) / 60_000))
}

type ReminderRowProps = {
  item: ReminderItem
  busy: boolean
  onDismiss: (id: string) => void
  onSnooze: (id: string, text: string, minutes: number) => void
}

function ReminderRow({ item, busy, onDismiss, onSnooze }: ReminderRowProps) {
  const [menuOpen, setMenuOpen] = useState(false)

  const handleSnooze = useCallback(
    (minutes: number) => {
      setMenuOpen(false)
      const resolved = minutes === -1 ? minutesUntilTomorrowNine() : minutes
      onSnooze(item.id, item.text, resolved)
    },
    [item.id, item.text, onSnooze],
  )

  return (
    <li className="reminders-agenda__item">
      <div className="reminders-agenda__item-body">
        <p className="reminders-agenda__item-text">{item.text}</p>
        {item.due_at ? (
          <time className="reminders-agenda__item-meta" dateTime={item.due_at}>
            Venció: {formatReminderDue(item.due_at)}
          </time>
        ) : null}
      </div>
      <div className="reminders-agenda__item-actions">
        <div className="reminders-agenda__snooze-wrap">
          <button
            type="button"
            className="reminders-agenda__action-btn"
            disabled={busy}
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            title="Posponer recordatorio"
            onClick={() => setMenuOpen((open) => !open)}
          >
            ⏰
          </button>
          {menuOpen ? (
            <ul className="reminders-agenda__snooze-menu" role="menu">
              {SNOOZE_OPTIONS.map((opt) => (
                <li key={opt.label} role="none">
                  <button
                    type="button"
                    role="menuitem"
                    className="reminders-agenda__snooze-option"
                    disabled={busy}
                    onClick={() => handleSnooze(opt.minutes)}
                  >
                    {opt.label}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <button
          type="button"
          className="reminders-agenda__action-btn reminders-agenda__action-btn--dismiss"
          disabled={busy}
          title="Descartar"
          aria-label={`Descartar recordatorio: ${item.text}`}
          onClick={() => onDismiss(item.id)}
        >
          ✓
        </button>
      </div>
    </li>
  )
}

export function RemindersAgendaPanel({
  reminders,
  remindersLoading,
  remindersError,
  onDismissReminder,
  onSnoozeReminder,
  agendaLinked,
  agendaEvents,
  agendaLoading,
  agendaError,
  agendaMessage,
  onOpenIntegrations,
}: RemindersAgendaPanelProps) {
  const [busyId, setBusyId] = useState<string | null>(null)

  const runReminderAction = useCallback(
    async (id: string, action: () => Promise<void>) => {
      setBusyId(id)
      try {
        await action()
      } finally {
        setBusyId(null)
      }
    },
    [],
  )

  const handleDismiss = useCallback(
    (id: string) => {
      void runReminderAction(id, () => onDismissReminder(id))
    },
    [onDismissReminder, runReminderAction],
  )

  const handleSnooze = useCallback(
    (id: string, text: string, minutes: number) => {
      void runReminderAction(id, () => onSnoozeReminder(id, text, minutes))
    },
    [onSnoozeReminder, runReminderAction],
  )

  return (
    <section className="reminders-agenda" aria-label="Recordatorios y agenda">
      <div className="reminders-agenda__block">
        <div className="reminders-agenda__head">
          <h3 className="status-sidebar__section-title">Recordatorios</h3>
          {reminders.length > 0 ? (
            <span className="reminders-agenda__badge" aria-label={`${reminders.length} pendientes`}>
              {reminders.length}
            </span>
          ) : null}
        </div>

        {remindersLoading && reminders.length === 0 ? (
          <p className="reminders-agenda__empty">Cargando recordatorios…</p>
        ) : remindersError ? (
          <p className="reminders-agenda__empty reminders-agenda__empty--error" role="alert">
            {remindersError}
          </p>
        ) : reminders.length === 0 ? (
          <p className="reminders-agenda__empty">No tienes recordatorios pendientes.</p>
        ) : (
          <ul className="reminders-agenda__list">
            {reminders.map((item) => (
              <ReminderRow
                key={item.id}
                item={item}
                busy={busyId === item.id}
                onDismiss={handleDismiss}
                onSnooze={handleSnooze}
              />
            ))}
          </ul>
        )}
      </div>

      <div className="reminders-agenda__block">
        <h3 className="status-sidebar__section-title">Agenda de hoy</h3>

        {agendaLoading && agendaEvents.length === 0 ? (
          <p className="reminders-agenda__empty">Cargando agenda…</p>
        ) : agendaError ? (
          <p className="reminders-agenda__empty reminders-agenda__empty--error" role="alert">
            {agendaError}
          </p>
        ) : !agendaLinked ? (
          <div className="reminders-agenda__cta">
            <p className="reminders-agenda__empty">
              {agendaMessage ?? 'Vincula Google Calendar para ver tu agenda aquí.'}
            </p>
            {onOpenIntegrations ? (
              <button
                type="button"
                className="status-sidebar__cta-btn"
                onClick={() => onOpenIntegrations('google')}
              >
                Vincular Google
              </button>
            ) : null}
          </div>
        ) : agendaEvents.length === 0 ? (
          <p className="reminders-agenda__empty">
            {agendaMessage ?? 'Hoy no tienes eventos en Google Calendar.'}
          </p>
        ) : (
          <ul className="reminders-agenda__agenda-list">
            {agendaEvents.map((event, index) => {
              const key = `${event.summary}-${event.start ?? index}`
              const timeLabel =
                event.start && event.end
                  ? `${formatEventTime(event.start)} – ${formatEventTime(event.end)}`
                  : formatEventTime(event.start)

              return (
                <li key={key} className="reminders-agenda__agenda-item">
                  <span className="reminders-agenda__agenda-time">{timeLabel}</span>
                  {event.html_link ? (
                    <a
                      className="reminders-agenda__agenda-title reminders-agenda__agenda-title--link"
                      href={event.html_link}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {event.summary}
                    </a>
                  ) : (
                    <span className="reminders-agenda__agenda-title">{event.summary}</span>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </section>
  )
}
