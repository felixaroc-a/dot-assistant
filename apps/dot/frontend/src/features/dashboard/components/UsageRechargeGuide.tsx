import {
  USAGE_LIMIT_BLOCKED_MESSAGE,
  USAGE_LIMIT_BLOCKED_TITLE,
  USAGE_RECHARGE_BRING_ITEMS,
  USAGE_RECHARGE_INTRO,
  USAGE_RECHARGE_STEPS,
  USAGE_STORE_LOCATOR_HINT,
} from '@/lib/usage-messages'

export type UsageRechargeGuideVariant = 'overlay' | 'sidebar' | 'meter' | 'composer'

export type UsageRechargeGuideProps = {
  variant?: UsageRechargeGuideVariant
  className?: string
}

export function UsageRechargeGuide({ variant = 'sidebar', className }: UsageRechargeGuideProps) {
  const rootClass = ['usage-recharge-guide', `usage-recharge-guide--${variant}`, className]
    .filter(Boolean)
    .join(' ')

  if (variant === 'composer') {
    return (
      <div className={rootClass}>
        <p className="usage-recharge-guide__lead">{USAGE_LIMIT_BLOCKED_MESSAGE}</p>
        <ol className="usage-recharge-guide__steps usage-recharge-guide__steps--compact">
          {USAGE_RECHARGE_STEPS.map((step, index) => (
            <li key={index}>{step}</li>
          ))}
        </ol>
      </div>
    )
  }

  if (variant === 'meter') {
    return (
      <div className={rootClass}>
        <p className="usage-recharge-guide__lead usage-recharge-guide__lead--danger">
          {USAGE_LIMIT_BLOCKED_MESSAGE}
        </p>
        <ol className="usage-recharge-guide__steps usage-recharge-guide__steps--compact">
          {USAGE_RECHARGE_STEPS.map((step, index) => (
            <li key={index}>{step}</li>
          ))}
        </ol>
        <p className="usage-recharge-guide__store-hint">{USAGE_STORE_LOCATOR_HINT}</p>
      </div>
    )
  }

  return (
    <div className={rootClass}>
      {variant === 'overlay' ? (
        <h2 className="usage-recharge-guide__title">{USAGE_LIMIT_BLOCKED_TITLE}</h2>
      ) : null}
      <p className="usage-recharge-guide__lead">
        {variant === 'overlay' ? USAGE_RECHARGE_INTRO : USAGE_LIMIT_BLOCKED_MESSAGE}
      </p>
      <ol className="usage-recharge-guide__steps">
        {USAGE_RECHARGE_STEPS.map((step, index) => (
          <li key={index}>{step}</li>
        ))}
      </ol>
      <div className="usage-recharge-guide__bring">
        <span className="usage-recharge-guide__bring-label">Qué llevar:</span>
        <ul className="usage-recharge-guide__bring-list">
          {USAGE_RECHARGE_BRING_ITEMS.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </div>
      <p className="usage-recharge-guide__store-hint">{USAGE_STORE_LOCATOR_HINT}</p>
    </div>
  )
}
