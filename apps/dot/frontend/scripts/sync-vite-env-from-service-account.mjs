/**
 * Rellena VITE_FIREBASE_PROJECT_ID y VITE_FIREBASE_AUTH_DOMAIN desde
 * backend/firebase-service-account.json. apiKey y appId solo vienen de la consola Web.
 *
 * Uso: npm run setup:env:vite
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const saPath = path.join(root, '..', '..', 'backend', 'firebase-service-account.json')
const envPath = path.join(root, '.env')
const examplePath = path.join(root, '.env.example')

function parseDotEnv(text) {
  /** @type {Record<string, string>} */
  const vars = {}
  const comments = []
  for (const line of text.split(/\r?\n/)) {
    const t = line.trim()
    if (!t || t.startsWith('#')) {
      comments.push(line)
      continue
    }
    const i = line.indexOf('=')
    if (i <= 0) continue
    const key = line.slice(0, i).trim()
    const val = line.slice(i + 1).trim()
    vars[key] = val
  }
  return { vars, comments }
}

function serializeEnv(vars) {
  const order = [
    'VITE_API_BASE_URL',
    'VITE_FIREBASE_API_KEY',
    'VITE_FIREBASE_APP_ID',
    'VITE_FIREBASE_AUTH_DOMAIN',
    'VITE_FIREBASE_PROJECT_ID',
  ]
  const lines = [
    '# Generado/actualizado por npm run setup:env:vite (projectId + authDomain desde cuenta de servicio).',
    '# Rellena en Firebase Console (app Web): VITE_FIREBASE_API_KEY y VITE_FIREBASE_APP_ID.',
    '',
  ]
  for (const k of order) {
    if (vars[k] !== undefined) lines.push(`${k}=${vars[k]}`)
  }
  for (const k of Object.keys(vars).sort()) {
    if (!order.includes(k)) lines.push(`${k}=${vars[k]}`)
  }
  return lines.join('\n') + '\n'
}

function main() {
  if (!existsSync(saPath)) {
    console.error('[Nordik] Falta', saPath)
    process.exit(1)
  }
  const sa = JSON.parse(readFileSync(saPath, 'utf8'))
  const projectId = sa.project_id
  if (!projectId) {
    console.error('[Nordik] JSON de servicio sin project_id')
    process.exit(1)
  }
  const authDomain = `${projectId}.firebaseapp.com`

  let text = ''
  if (existsSync(envPath)) text = readFileSync(envPath, 'utf8')
  else if (existsSync(examplePath)) text = readFileSync(examplePath, 'utf8')
  const { vars } = parseDotEnv(text)

  vars.VITE_API_BASE_URL = vars.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
  vars.VITE_FIREBASE_PROJECT_ID = projectId
  vars.VITE_FIREBASE_AUTH_DOMAIN = authDomain
  if (vars.VITE_FIREBASE_API_KEY === undefined) vars.VITE_FIREBASE_API_KEY = ''
  if (vars.VITE_FIREBASE_APP_ID === undefined) vars.VITE_FIREBASE_APP_ID = ''

  writeFileSync(envPath, serializeEnv(vars), 'utf8')
  console.log('[Nordik] Escrito', envPath)
  console.log('[Nordik]   VITE_FIREBASE_PROJECT_ID =', projectId)
  console.log('[Nordik]   VITE_FIREBASE_AUTH_DOMAIN =', authDomain)

  const miss = []
  if (!(vars.VITE_FIREBASE_API_KEY ?? '').trim()) miss.push('VITE_FIREBASE_API_KEY')
  if (!(vars.VITE_FIREBASE_APP_ID ?? '').trim()) miss.push('VITE_FIREBASE_APP_ID')
  if (miss.length) {
    console.log('')
    console.log('[Nordik] Falta pegar en . desde Firebase (app Web → firebaseConfig):', miss.join(', '))
    process.exit(2)
  }
  console.log('[Nordik] Variables Web completas.')
}

main()
