/**
 * Huella del pendrive enlazada a la sesión (Electron safeStorage).
 */

function hasDesktopBind(): boolean {
  return typeof window !== 'undefined' && !!window.desktop?.hardwareBind
}

export async function loadHardwareBindFingerprint(): Promise<string | null> {
  if (hasDesktopBind()) {
    return window.desktop!.hardwareBind!.load()
  }
  return null
}

export async function saveHardwareBindFingerprint(fingerprint: string): Promise<void> {
  if (hasDesktopBind()) {
    await window.desktop!.hardwareBind!.save(fingerprint)
  }
}

export async function clearHardwareBindFingerprint(): Promise<void> {
  if (hasDesktopBind()) {
    await window.desktop!.hardwareBind!.clear()
  }
}
