export type OnboardingFlowStep =
  | 'welcome'
  | 'whatsapp'
  | 'google'
  | 'personalize'
  | 'completion'
  | 'dashboard'

/** Paso actual del onboarding (1-4). 0 = dashboard/completado. */
export function stepToNumber(step: OnboardingFlowStep): number {
  switch (step) {
    case 'welcome': return 1
    case 'whatsapp': return 2
    case 'google': return 3
    case 'personalize': return 4
    case 'completion': return 5
    case 'dashboard': return 0
  }
}

export const TOTAL_ONBOARDING_STEPS = 4
