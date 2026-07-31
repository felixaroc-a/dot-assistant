import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import { RemindersAgendaPanel } from './RemindersAgendaPanel'

describe('RemindersAgendaPanel', () => {
  it('muestra recordatorios pendientes y permite descartar', async () => {
    const onDismiss = vi.fn().mockResolvedValue(undefined)
    const onSnooze = vi.fn().mockResolvedValue(undefined)

    render(
      <RemindersAgendaPanel
        reminders={[{ id: 'r1', text: 'Llamar a mamá', due_at: '2026-07-24T14:00:00+00:00' }]}
        remindersLoading={false}
        remindersError={null}
        onDismissReminder={onDismiss}
        onSnoozeReminder={onSnooze}
        agendaLinked={true}
        agendaEvents={[{ summary: 'Reunión', start: '2026-07-24T10:00:00+00:00', end: '2026-07-24T11:00:00+00:00', html_link: null }]}
        agendaLoading={false}
        agendaError={null}
        agendaMessage={null}
      />,
    )

    expect(screen.getByText('Recordatorios')).toBeInTheDocument()
    expect(screen.getByText('Llamar a mamá')).toBeInTheDocument()
    expect(screen.getByText('Agenda de hoy')).toBeInTheDocument()
    expect(screen.getByText('Reunión')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Descartar recordatorio/i }))
    expect(onDismiss).toHaveBeenCalledWith('r1')
  })

  it('muestra CTA de Google cuando la agenda no está vinculada', () => {
    const onOpenIntegrations = vi.fn()

    render(
      <RemindersAgendaPanel
        reminders={[]}
        remindersLoading={false}
        remindersError={null}
        onDismissReminder={vi.fn()}
        onSnoozeReminder={vi.fn()}
        agendaLinked={false}
        agendaEvents={[]}
        agendaLoading={false}
        agendaError={null}
        agendaMessage="Google Calendar no está vinculado."
        onOpenIntegrations={onOpenIntegrations}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Vincular Google' }))
    expect(onOpenIntegrations).toHaveBeenCalledWith('google')
  })
})
