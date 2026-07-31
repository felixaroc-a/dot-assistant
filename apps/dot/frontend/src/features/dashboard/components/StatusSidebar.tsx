import type { UsageDailyItem, UsageSummary } from '@/lib/api/usage'
import {
  USAGE_WARNING_MESSAGE,
  USAGE_WARNING_THRESHOLD_PERCENT,
} from '@/lib/usage-messages'
import type { WhatsAppLinkStatus } from '@/lib/api/whatsapp'
import type {
  ActivePipelineView,
  GeneratedDocPreview,
  PipelineDef,
} from '@/features/dashboard/model/types'
import { RemindersAgendaPanel } from '@/features/dashboard/components/RemindersAgendaPanel'
import { StatusPreviewPanel } from '@/features/dashboard/components/StatusPreviewPanel'
import { UsageMeter } from '@/features/dashboard/components/UsageMeter'
import { UsageRechargeGuide } from '@/features/dashboard/components/UsageRechargeGuide'
import { PendriveIndicator } from '@/features/dashboard/components/PendriveIndicator'
import type { ReminderItem } from '@/features/dashboard/hooks/useRemindersPanel'
import type { AgendaSidebarEvent } from '@/features/dashboard/hooks/useAgendaSidebar'

export type StatusSidebarProps = {
  selectedPipeline: PipelineDef | null
  activeView: ActivePipelineView | null
  docPreview: GeneratedDocPreview | null
  whatsappStatus: WhatsAppLinkStatus
  whatsappPhone?: string | null
  googleConnected: boolean
  pipelineCount?: number
  usageSummary?: UsageSummary | null
  usageLoading?: boolean
  usageError?: string | null
  usageDailyHistory?: UsageDailyItem[] | null
  onSelectPipelineHint?: () => void
  onCreatePipelineHint?: () => void
  onOpenIntegrations?: (focus?: 'whatsapp' | 'google') => void
  reminders?: ReminderItem[]
  remindersLoading?: boolean
  remindersError?: string | null
  onDismissReminder?: (id: string) => Promise<void>
  onSnoozeReminder?: (id: string, text: string, minutes: number) => Promise<void>
  agendaLinked?: boolean
  agendaEvents?: AgendaSidebarEvent[]
  agendaLoading?: boolean
  agendaError?: string | null
  agendaMessage?: string | null
}

export function StatusSidebar({
  selectedPipeline,
  activeView,
  docPreview,
  whatsappStatus,
  whatsappPhone = null,
  googleConnected,
  pipelineCount = 0,
  usageSummary = null,
  usageLoading = false,
  usageError = null,
  usageDailyHistory = null,
  onSelectPipelineHint,
  onCreatePipelineHint,
  onOpenIntegrations,
  reminders = [],
  remindersLoading = false,
  remindersError = null,
  onDismissReminder,
  onSnoozeReminder,
  agendaLinked = false,
  agendaEvents = [],
  agendaLoading = false,
  agendaError = null,
  agendaMessage = null,
}: StatusSidebarProps) {
  const percent = usageSummary?.consumed_percent ?? 0

  return (
    <aside className="status-sidebar" aria-label="Panel de estado y previsualización">
      {/* Medidor de consumo IA */}
      <section className="status-sidebar__usage" aria-labelledby="status-sidebar-usage">
        <UsageMeter
          summary={usageSummary}
          loading={usageLoading}
          error={usageError}
          detailed={true}
          dailyHistory={usageDailyHistory}
        />

        {/* Alerta 80% — IA casi agotada */}
        {usageSummary && !usageSummary.blocked && percent >= USAGE_WARNING_THRESHOLD_PERCENT && (
          <div className="status-sidebar__alert status-sidebar__alert--warning" role="alert">
            <span className="status-sidebar__alert-icon">&#9888;</span>
            <span className="status-sidebar__alert-text">{USAGE_WARNING_MESSAGE}</span>
          </div>
        )}

        {/* Alerta 100% — bloqueado */}
        {usageSummary?.blocked && (
          <div className="status-sidebar__alert status-sidebar__alert--danger" role="alert">
            <span className="status-sidebar__alert-icon">&#10060;</span>
            <div className="status-sidebar__alert-body">
              <UsageRechargeGuide variant="sidebar" />
            </div>
          </div>
        )}
      </section>

      {onDismissReminder && onSnoozeReminder ? (
        <RemindersAgendaPanel
          reminders={reminders}
          remindersLoading={remindersLoading}
          remindersError={remindersError}
          onDismissReminder={onDismissReminder}
          onSnoozeReminder={onSnoozeReminder}
          agendaLinked={agendaLinked}
          agendaEvents={agendaEvents}
          agendaLoading={agendaLoading}
          agendaError={agendaError}
          agendaMessage={agendaMessage}
          onOpenIntegrations={onOpenIntegrations}
        />
      ) : null}

      <StatusPreviewPanel
        selectedPipeline={selectedPipeline}
        activeView={activeView}
        docPreview={docPreview}
        whatsappStatus={whatsappStatus}
        whatsappPhone={whatsappPhone}
        googleConnected={googleConnected}
        pipelineCount={pipelineCount}
        onSelectPipelineHint={onSelectPipelineHint}
        onCreatePipelineHint={onCreatePipelineHint}
        onOpenIntegrations={onOpenIntegrations}
      />
      <PendriveIndicator />
    </aside>
  )
}
