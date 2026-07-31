import type { PipelineStep } from '@/features/dashboard/model/types'

type PipelineChainProps = {
  steps: PipelineStep[]
  result?: {
    steps: Array<{ step_id: string; error: string | null; output: string }>
    success: boolean
  } | null
}

const STEP_COLORS: Record<string, string> = {
  action: '#4285f4',
  condition: '#f9ab00',
  output: '#34a853',
  trigger: '#ea4335',
}

const STEP_LABELS: Record<string, string> = {
  action: 'Accion',
  condition: 'Condicion',
  output: 'Salida',
  trigger: 'Trigger',
}

const INTEGRATION_ICONS: Record<string, string> = {
  gmail: '\u2709',
  'google-calendar': '\u{1F4C5}',
  chat: '\u{1F916}',
  whatsapp: '\u{1F4AC}',
  web_search: '\u{1F50D}',
  file: '\u{1F4C4}',
  condition: '\u{1F500}',
  output: '\u{1F514}',
}

function getStepResult(stepId: string, result: PipelineChainProps['result']): { error: string | null; output: string } | null {
  if (!result?.steps) return null
  return result.steps.find((s) => s.step_id === stepId) || null
}

export function PipelineChain({ steps, result }: PipelineChainProps) {
  if (!steps || steps.length === 0) {
    return (
      <div className="main-dashboard__pipeline-chain-empty">
        Sin pasos definidos
      </div>
    )
  }

  return (
    <div className="main-dashboard__pipeline-chain-visual">
      {steps.map((step, i) => {
        const stepResult = getStepResult(step.id, result)
        const isError = !!stepResult?.error
        const isSuccess = result?.success && !stepResult?.error
        const color = STEP_COLORS[step.type] || '#999'

        return (
          <div key={step.id} className="main-dashboard__pipeline-chain-node-row">
            <div
              className={`main-dashboard__pipeline-chain-node ${isError ? 'main-dashboard__pipeline-chain-node--error' : ''} ${isSuccess ? 'main-dashboard__pipeline-chain-node--success' : ''}`}
              style={{ borderColor: color }}
            >
              <div className="main-dashboard__pipeline-chain-node-header">
                <span className="main-dashboard__pipeline-chain-node-badge" style={{ backgroundColor: color }}>
                  {STEP_LABELS[step.type] || step.type}
                </span>
                <span className="main-dashboard__pipeline-chain-node-icon">
                  {INTEGRATION_ICONS[step.integration] || '\u25CF'}
                </span>
              </div>
              <p className="main-dashboard__pipeline-chain-node-text">{step.instruction}</p>
              {step.condition_operator !== 'always' && (
                <span className="main-dashboard__pipeline-chain-node-condition">
                  Si {step.condition_operator.replace('if_result_contains', 'contiene').replace('if_result_matches', 'coincide con')} "{step.condition_value}"
                </span>
              )}
              {isError && (
                <span className="main-dashboard__pipeline-chain-node-error">
                  Error: {stepResult?.error}
                </span>
              )}
              {isSuccess && stepResult?.output && (
                <span className="main-dashboard__pipeline-chain-node-output">
                  {stepResult.output.slice(0, 80)}
                </span>
              )}
            </div>

            {i < steps.length - 1 && (
              <div className="main-dashboard__pipeline-chain-connector">
                <div className="main-dashboard__pipeline-chain-arrow-line" />
                <span className="main-dashboard__pipeline-chain-arrow-head">{'\u2193'}</span>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
