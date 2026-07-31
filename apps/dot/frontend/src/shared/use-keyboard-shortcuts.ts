import { useEffect } from 'react'

interface Shortcut {
  key: string
  ctrl?: boolean
  alt?: boolean
  shift?: boolean
  handler: () => void
  description: string
}

export function useKeyboardShortcuts(shortcuts: Shortcut[]) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      for (const s of shortcuts) {
        const matchCtrl = s.ctrl ? e.ctrlKey || e.metaKey : true
        const matchAlt = s.alt ? e.altKey : true
        const matchShift = s.shift ? e.shiftKey : true
        const matchKey = e.key.toLowerCase() === s.key.toLowerCase()

        if (matchCtrl && matchAlt && matchShift && matchKey) {
          e.preventDefault()
          e.stopPropagation()
          s.handler()
          return
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [shortcuts])
}
