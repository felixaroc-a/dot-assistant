import './progress-bar.css'

type ProgressBarProps = {
  currentStep: number   // 1-4
  totalSteps?: number    // default 4
}

export function ProgressBar({ currentStep, totalSteps = 4 }: ProgressBarProps) {
  if (currentStep <= 0 || currentStep > totalSteps) return null

  return (
    <div className="progress-bar" role="progressbar" aria-valuenow={currentStep} aria-valuemin={1} aria-valuemax={totalSteps} aria-label={`Paso ${currentStep} de ${totalSteps}`}>
      <p className="progress-bar__label">Paso {currentStep} de {totalSteps}</p>
      <div className="progress-bar__track">
        <div
          className="progress-bar__fill"
          style={{ width: `${(currentStep / totalSteps) * 100}%` }}
        />
      </div>
    </div>
  )
}
