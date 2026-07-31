/**
 * Descarga binarios de Electron con reintentos y mirrors (útil si GitHub/cierra TLS da ECONNRESET).
 */
import { existsSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const installJs = join(root, 'node_modules', 'electron', 'install.js')

if (!existsSync(installJs)) {
  console.error('No se encontró Electron. Ejecuta antes: npm install --ignore-scripts')
  process.exit(1)
}

const mirrors = [
  'https://npmmirror.com/mirrors/electron/',
  'https://cdn.npmmirror.com/binaries/electron/',
  '',
]

async function main() {
  for (let i = 0; i < mirrors.length; i++) {
    const mirror = mirrors[i]
    const env = { ...process.env }
    if (mirror) {
      env.ELECTRON_MIRROR = mirror
      console.log(`[electron] Origen ${i + 1}/${mirrors.length}: mirror`)
    } else {
      delete env.ELECTRON_MIRROR
      console.log(`[electron] Origen ${i + 1}/${mirrors.length}: GitHub Releases (predeterminado)`)
    }

    const r = spawnSync(process.execPath, [installJs], { cwd: root, env, stdio: 'inherit' })
    if (r.status === 0) {
      console.log('[electron] Descarga instalada correctamente.')
      process.exit(0)
    }

    if (i < mirrors.length - 1) {
      console.warn('[electron] Falló esta ruta; probando la siguiente en 6s…')
      await delay(6000)
    }
  }

  console.error('[electron] No fue posible completar la descarga. Revisa firewall/VPN/red.')
  process.exit(1)
}

await main()
