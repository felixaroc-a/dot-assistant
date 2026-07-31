/**
 * Embebe secretos de runtime Electron (pepper pendrive) antes de desktop:dist.
 * Lee frontend/backend/.env y escribe electron/build-secrets.json (no commitear).
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const backendEnv = path.join(root, '..', 'backend', '.env')
const outPath = path.join(root, 'electron', 'build-secrets.json')

function parseDotEnv(text) {
  const vars = {}
  for (const line of text.split(/\r?\n/)) {
    const t = line.trim()
    if (!t || t.startsWith('#')) continue
    const i = line.indexOf('=')
    if (i <= 0) continue
    vars[line.slice(0, i).trim()] = line.slice(i + 1).trim()
  }
  return vars
}

function main() {
  if (!existsSync(backendEnv)) {
    console.error('[Nordik] Falta', backendEnv)
    process.exit(1)
  }
  const vars = parseDotEnv(readFileSync(backendEnv, 'utf8'))
  const pepper = (vars.HARDWARE_TOKEN_PEPPER || '').trim()
  if (pepper.length < 32) {
    console.error('[DOT] HARDWARE_TOKEN_PEPPER invalida o ausente en backend/.env')
    process.exit(1)
  }
  let apiBase = (vars.DOT_API_BASE_URL || vars.NORDIK_API_BASE_URL || '').trim()
  if (!apiBase) {
    const frontendEnv = path.join(root, '.env')
    if (existsSync(frontendEnv)) {
      apiBase = (parseDotEnv(readFileSync(frontendEnv, 'utf8')).VITE_API_BASE_URL || '').trim()
    }
  }
  if (!apiBase) {
    console.error(
      '[DOT] VITE_API_BASE_URL no configurada.\n' +
      'Establece VITE_API_BASE_URL en frontend/.env o DOT_API_BASE_URL en backend/.env.\n' +
      'Ejemplo: VITE_API_BASE_URL=http://127.0.0.1:8000'
    )
    process.exit(1)
  }

  const updaterUrl = (vars.DOT_UPDATER_URL || vars.NORDIK_UPDATER_URL || '').trim()

  writeFileSync(
    outPath,
    JSON.stringify(
      {
        HARDWARE_TOKEN_PEPPER: pepper,
        DOT_API_BASE_URL: apiBase.replace(/\/$/, ''),
        ...(updaterUrl ? { DOT_UPDATER_URL: updaterUrl } : {}),
      },
      null,
      2,
    ) + '\n',
    'utf8',
  )
  console.log('[DOT] Escrito', outPath)
  console.log('[DOT]   HARDWARE_TOKEN_PEPPER:', pepper.length, 'chars')
  console.log('[DOT]   DOT_API_BASE_URL:', apiBase)
  if (updaterUrl) {
    console.log('[DOT]   DOT_UPDATER_URL:', updaterUrl)
  } else {
    console.log('[DOT]   DOT_UPDATER_URL: (no configurada, auto-updater desactivado)')
  }
}

main()
