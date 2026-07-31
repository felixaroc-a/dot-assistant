/** Duraciones en segundos — sincronizadas entre animación y navegación. */
export const SPLASH_FALL_BOUNCE_S = 0.95
export const SPLASH_HOLD_S = 0.22
export const SPLASH_LETTERS_IN_S = 0.22
export const SPLASH_IA_IN_S = 0.28
export const SPLASH_LOGO_HOLD_S = 0.18
export const SPLASH_FADE_S = 0.28

export const SPLASH_LOGO_START_S = SPLASH_FALL_BOUNCE_S + SPLASH_HOLD_S
export const SPLASH_IA_START_S = SPLASH_LOGO_START_S + SPLASH_LETTERS_IN_S
export const SPLASH_EXIT_START_S = SPLASH_IA_START_S + SPLASH_IA_IN_S + SPLASH_LOGO_HOLD_S
export const SPLASH_TOTAL_MS = Math.round((SPLASH_EXIT_START_S + SPLASH_FADE_S) * 1000)

/** Escala de la esfera durante caída/rebote vs. tamaño final en el wordmark (0.9em × 1). */
export const SPLASH_SPHERE_DROP_SCALE = 2.75
export const SPLASH_SPHERE_IMPACT_SCALE = 1.05
export const SPLASH_SPHERE_FINAL_SCALE = 1

export const APPLE_EASE = [0.16, 1, 0.3, 1] as const

/** Caída acelerada (ease-in). */
export const SPLASH_FALL_EASE = [0.55, 0.085, 0.68, 0.53] as const
/** Rebote hacia arriba rápido (ease-out). */
export const SPLASH_BOUNCE_UP_EASE = [0.22, 1, 0.36, 1] as const
/** Caída final con gravedad fuerte — se clava en el centro. */
export const SPLASH_DROP_EASE = [0.75, 0, 0.95, 0.4] as const
