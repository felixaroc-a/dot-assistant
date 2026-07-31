export function IconPaperclip(props: { className?: string }) {
  return (
    <svg className={props.className} width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M17.35 5.65L8.4 14.6a3 3 0 104.24 4.24l8.2-8.2a4.5 4.5 0 10-6.36-6.36l-8.6 8.6"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function IconImage(props: { className?: string }) {
  return (
    <svg className={props.className} width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="3" y="5" width="18" height="14" rx="2.25" stroke="currentColor" strokeWidth="1.75" />
      <circle cx="8.25" cy="10" r="1.25" fill="currentColor" />
      <path
        d="M21 16l-4.8-4.8a1.2 1.2 0 00-1.7 0L8 18"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function IconMic(props: { className?: string }) {
  return (
    <svg className={props.className} width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 15.75v2.25M8.25 18h7.5M12 14.25a3.75 3.75 0 003.75-3.75V6a3.75 3.75 0 10-7.5 0v4.5a3.75 3.75 0 003.75 3.75z"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
