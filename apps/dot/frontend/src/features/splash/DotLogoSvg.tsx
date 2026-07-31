import type { SVGAttributes } from 'react'

export function DotLogoSvg(props: SVGAttributes<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 180 60"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="DOT"
      {...props}
    >
      <defs>
        <linearGradient id="dot-grad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#3B82F6" />
          <stop offset="50%" stopColor="#6366F1" />
          <stop offset="100%" stopColor="#8B5CF6" />
        </linearGradient>
      </defs>

      {/* D */}
      <path
        d="M10 10 L10 50 L38 50 C45 50 50 44 50 37 L50 23 C50 16 45 10 38 10 Z"
        stroke="url(#dot-grad)"
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />

      {/* O */}
      <ellipse
        cx="87"
        cy="30"
        rx="20"
        ry="20"
        stroke="url(#dot-grad)"
        strokeWidth="3.5"
        fill="none"
      />

      {/* T */}
      <path
        d="M120 10 L155 10 M137.5 10 L137.5 50"
        stroke="url(#dot-grad)"
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />

      {/* Dot accent */}
      <circle cx="167" cy="14" r="4" fill="url(#dot-grad)" opacity="0.8" />
    </svg>
  )
}
