/**
 * Copia ADMIN_API_KEY del backend a VITE_ADMIN_API_KEY en frontend/.env
 * y asegura VITE_API_BASE_URL (prioriza valor existente en frontend/.env).
 *
 * Uso: npm run setup:env:backend
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const backendEnvPath = path.join(root, '..', '..', 'backend', '.env')
const frontendEnvPath = path.join(root, '.env')

function parseDotEnv(text) {
  /** @type {Record<string, string>} */
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

function serializeEnv(vars) {
  const order = [
    'VITE_API_BASE_URL',
    'VITE_ADMIN_API_KEY',
    'VITE_DOT_PROVISIONER',
    'VITE_PANEL_ONLY_USB',
    'VITE_FIREBASE_API_KEY',
    'VITE_FIREBASE_APP_ID',
    'VITE_FIREBASE_AUTH_DOMAIN',
    'VITE_FIREBASE_PROJECT_ID',
  ]
  const lines = [
    '# Nordik frontend — generado/actualizado por npm run setup:env:backend',
    '# VITE_ADMIN_API_KEY debe coincidir con ADMIN_API_KEY en backend/.env',
    '',
  ]
  for (const k of order) {
    if (vars[k] !== undefined) lines.push(`${k}=${vars[k]}`)
  }
  for (const k of Object.keys(vars).sort()) {
    if (!order.includes(k)) lines.push(`${k}=${vars[k]}`)
  }
  return `${lines.join('\n')}\n`
}

function main() {
  if (!existsSync(backendEnvPath)) {
    console.error('[Nordik] Falta', backendEnvPath)
    process.exit(1)
  }

  const backendVars = parseDotEnv(readFileSync(backendEnvPath, 'utf8'))
  const adminKey = (backendVars.ADMIN_API_KEY || '').trim()
  if (!adminKey) {
    console.error('[Nordik] ADMIN_API_KEY vacia en backend/.env')
    process.exit(1)
  }

  let frontendVars = {}
  if (existsSync(frontendEnvPath)) {
    frontendVars = parseDotEnv(readFileSync(frontendEnvPath, 'utf8'))
  }

  frontendVars.VITE_ADMIN_API_KEY = adminKey

  if (!(frontendVars.VITE_API_BASE_URL || '').trim()) {
    frontendVars.VITE_API_BASE_URL = 'http://127.0.0.1:8000'
  }

  writeFileSync(frontendEnvPath, serializeEnv(frontendVars), 'utf8')
  console.log('[Nordik] Escrito', frontendEnvPath)
  console.log('[Nordik]   VITE_ADMIN_API_KEY = (copiada desde backend,', adminKey.length, 'chars)')
  console.log('[Nordik]   VITE_API_BASE_URL =', frontendVars.VITE_API_BASE_URL)
  console.log('')
  console.log('[Nordik] Reinicia Vite/Electron: npm run desktop:provisioner')
  console.log('[Nordik] Para .exe en USB: npm run desktop:provisioner:dist (tras este paso)')
}

main()
