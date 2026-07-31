function hasDesktopRecoveryKey(): boolean {
  return typeof window !== 'undefined' && !!window.desktop?.recoveryKey
}

export async function saveRecoveryKeyLocal(key: string): Promise<boolean> {
  if (hasDesktopRecoveryKey()) {
    const result = await window.desktop!.recoveryKey!.save(key)
    return result?.ok === true
  }
  // Fallback: localStorage (solo dev, no seguro)
  try {
    localStorage.setItem('dot_recovery_key_backup', key)
    return true
  } catch {
    return false
  }
}

export async function loadRecoveryKeyLocal(): Promise<string | null> {
  if (hasDesktopRecoveryKey()) {
    return await window.desktop!.recoveryKey!.load()
  }
  try {
    return localStorage.getItem('dot_recovery_key_backup')
  } catch {
    return null
  }
}

export async function hasRecoveryKeyLocal(): Promise<boolean> {
  const key = await loadRecoveryKeyLocal()
  return key !== null && key.length > 0
}
