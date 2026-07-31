'use strict'

const fs = require('node:fs')
const path = require('node:path')

/**
 * Carga variables desde .env del proyecto sin sobrescribir las ya definidas
 * (salvo cadenas vacías, que se rellenan desde el archivo).
 *
 * Orden: apps/dot/backend/.env → apps/autoventa/backend/.env
 */
function parseDotEnv(text) {
  /** @type {Record<string, string>} */
  const vars = {}
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const eq = line.indexOf('=')
    if (eq <= 0) continue
    const key = line.slice(0, eq).trim()
    const value = line.slice(eq + 1).trim()
    if (key) vars[key] = value
  }
  return vars
}

function applyEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return
  const vars = parseDotEnv(fs.readFileSync(filePath, 'utf8'))
  for (const [key, value] of Object.entries(vars)) {
    const current = process.env[key]
    if (current === undefined || String(current).trim() === '') {
      process.env[key] = value
    }
  }
}

function loadBuildSecrets() {
  const secretsPath = path.join(__dirname, 'build-secrets.json')
  if (!fs.existsSync(secretsPath)) return
  try {
    const data = JSON.parse(fs.readFileSync(secretsPath, 'utf8'))
    if (data.HARDWARE_TOKEN_PEPPER && !String(process.env.HARDWARE_TOKEN_PEPPER || '').trim()) {
      process.env.HARDWARE_TOKEN_PEPPER = String(data.HARDWARE_TOKEN_PEPPER).trim()
    }
    const keyApi = data.DOT_API_BASE_URL || data.NORDIK_API_BASE_URL
    if (keyApi && !String(process.env.DOT_API_BASE_URL || process.env.NORDIK_API_BASE_URL || '').trim()) {
      process.env.DOT_API_BASE_URL = String(keyApi).trim()
    }
    const keyUpdater = data.DOT_UPDATER_URL || data.NORDIK_UPDATER_URL
    if (keyUpdater && !String(process.env.DOT_UPDATER_URL || process.env.NORDIK_UPDATER_URL || '').trim()) {
      process.env.DOT_UPDATER_URL = String(keyUpdater).trim()
    }
  } catch {
    // ignorar JSON corrupto
  }
}

function loadBackendEnv() {
  const electronDir = __dirname
  const frontendRoot = path.join(electronDir, '..')
  // apps/dot/frontend → apps/dot → repo root (Nordik-IA)
  const dotRoot = path.join(frontendRoot, '..')
  const repoRoot = path.join(dotRoot, '..', '..')

  loadBuildSecrets()
  // Primario: apps/dot/backend/.env (bridge secret, API, etc.)
  applyEnvFile(path.join(dotRoot, 'backend', '.env'))
  // Legacy / monorepo vecinos
  applyEnvFile(path.join(repoRoot, 'apps', 'dot', 'backend', '.env'))
  applyEnvFile(path.join(repoRoot, 'apps', 'autoventa', 'backend', '.env'))
}

loadBackendEnv()

module.exports = { loadBackendEnv, applyEnvFile, parseDotEnv }
