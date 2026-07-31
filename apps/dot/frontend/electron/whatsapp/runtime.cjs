'use strict'

const { spawn } = require('node:child_process')

/**
 * @param {string} command
 * @param {string[]} args
 * @param {(chunk: { stream: 'stdout' | 'stderr'; text: string }) => void} onChunk
 * @returns {Promise<{ code: number; acc: string }>}
 */
function runToCompletion(command, args, onChunk) {
  return new Promise((resolve, reject) => {
    const childProcess = spawn(command, args, {
      env: { ...process.env, FORCE_COLOR: '0', NO_COLOR: '1', CI: '1' },
      windowsHide: true,
      shell: false,
    })

    let acc = ''
    childProcess.stdout.setEncoding('utf8')
    childProcess.stderr.setEncoding('utf8')

    childProcess.stdout.on('data', (text) => {
      const t = String(text)
      acc += t
      onChunk({ stream: 'stdout', text: t })
    })
    childProcess.stderr.on('data', (text) => {
      const t = String(text)
      acc += t
      onChunk({ stream: 'stderr', text: t })
    })
    childProcess.on('error', (err) => {
      onChunk({ stream: 'stderr', text: `${err.message}\n` })
      reject(err)
    })
    childProcess.on('close', (code) => resolve({ code: code ?? 1, acc }))
  })
}

module.exports = {
  runToCompletion,
  /**
   * A03: Intenta restaurar sesión WhatsApp desde safeStorage sin pasar por QR.
   *
   * @param {{
   *   secureStorage: { loadWhatsAppCreds: () => (string|null), saveWhatsAppCreds: (s: string) => object, clearWhatsAppCreds: () => object },
   *   transport: import('./transport/whatsapp-transport.cjs').WhatsappTransport & { restoreSession: () => Promise<object>, authDir?: string, _restoreCredsFromSafeStorage?: () => boolean }
   * }} deps
   * @returns {Promise<{ ok: boolean; needs_qr: boolean; linked: boolean; phone_number?: string | null; error?: string }>}
   */
  async restoreFromSavedCreds({ secureStorage, transport }) {
    const fs = require('node:fs')
    const path = require('node:path')

    try {
      // Si el transport tiene restoreSession, delegar en él (método más completo)
      if (typeof transport.restoreSession === 'function') {
        const result = await transport.restoreSession()
        return {
          ok: result.ok,
          needs_qr: result.needs_qr !== false,
          linked: result.linked || false,
          phone_number: result.phone_number || null,
          error: result.error || undefined,
        }
      }

      // Fallback: restaurar manualmente desde safeStorage
      const raw = secureStorage.loadWhatsAppCreds()
      if (!raw || !raw.trim()) {
        return { ok: false, needs_qr: true, linked: false, error: 'no_saved_creds' }
      }

      // Validar JSON
      JSON.parse(raw)

      // Escribir credenciales al authDir si tenemos acceso
      const authDir = transport._authDir || transport.authDir
      if (authDir) {
        fs.mkdirSync(authDir, { recursive: true })
        fs.writeFileSync(path.join(authDir, 'creds.json'), raw, 'utf8')
      }

      // Arrancar daemon
      if (typeof transport.startDaemon === 'function') {
        const started = await transport.startDaemon('restore_session')
        if (!started.ok) {
          return { ok: false, needs_qr: true, linked: false, error: started.error || 'daemon_failed' }
        }
      }

      return { ok: true, needs_qr: false, linked: true, phone_number: null }
    } catch (err) {
      return {
        ok: false,
        needs_qr: true,
        linked: false,
        error: err instanceof Error ? err.message : String(err),
      }
    }
  },
}
