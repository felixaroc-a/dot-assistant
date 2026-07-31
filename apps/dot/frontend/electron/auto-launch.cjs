'use strict'

/**
 * Auto-arranque de DOT al conectar el pendrive (Windows).
 *
 * Cuando el cliente conecta el pendrive DOT en su PC, la aplicacion
 * debe iniciarse automaticamente "como si fuera un malware".
 * Dado que Windows 10/11 bloquea autorun.inf por seguridad, usamos
 * el registro de Windows (Run key en HKCU).
 *
 * Estrategia:
 * - Al ejecutar DOT por primera vez (instalado o desde el pendrive),
 *   se agrega una entrada en HKCU\Software\Microsoft\Windows\CurrentVersion\Run
 * - Asi, cuando el cliente conecta el pendrive y la PC arranca (o el usuario
 *   inicia sesion), DOT se lanza solo.
 * - La deteccion del pendrive y dot.vault ocurre en pendrive-gate.cjs,
 *   que despues de validar el vault permite abrir la ventana de login.
 */

const { execFile } = require('node:child_process')
const { promisify } = require('node:util')

const execFileAsync = promisify(execFile)

const RUN_KEY = 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run'
const VALUE_NAME = 'DOT'

/**
 * Verifica si DOT ya esta registrado en el Run key de Windows.
 * @returns {Promise<boolean>}
 */
async function isRegistered() {
  if (process.platform !== 'win32') return false

  try {
    const { stdout } = await execFileAsync(
      'reg',
      ['query', RUN_KEY, '/v', VALUE_NAME],
      { timeout: 5000, windowsHide: true },
    )
    return stdout.includes(VALUE_NAME)
  } catch {
    return false
  }
}

/**
 * Agrega DOT al Run key de Windows (HKCU).
 * Esto hace que la aplicacion se inicie automaticamente cuando
 * el usuario inicia sesion en Windows.
 *
 * @returns {Promise<{ ok: boolean, message?: string, error?: string }>}
 */
async function ensureAutoLaunch() {
  if (process.platform !== 'win32') {
    return { ok: false, error: 'UNSUPPORTED_PLATFORM' }
  }

  try {
    const already = await isRegistered()
    if (already) {
      return { ok: true, message: 'already_registered' }
    }

    const appPath = process.execPath
    if (!appPath) {
      return { ok: false, error: 'NO_EXECUTABLE_PATH' }
    }

    await execFileAsync(
      'reg',
      [
        'add',
        RUN_KEY,
        '/v',
        VALUE_NAME,
        '/t',
        'REG_SZ',
        '/d',
        `"${appPath}"`,
        '/f',
      ],
      { timeout: 10000, windowsHide: true },
    )

    return { ok: true, message: 'registered' }
  } catch (err) {
    const message =
      err && typeof err === 'object' && err.message
        ? err.message
        : 'REG_ADD_FAILED'
    return { ok: false, error: message }
  }
}

/**
 * Quita DOT del Run key de Windows.
 * @returns {Promise<{ ok: boolean, error?: string }>}
 */
async function removeAutoLaunch() {
  if (process.platform !== 'win32') {
    return { ok: false, error: 'UNSUPPORTED_PLATFORM' }
  }

  try {
    await execFileAsync(
      'reg',
      ['delete', RUN_KEY, '/v', VALUE_NAME, '/f'],
      { timeout: 10000, windowsHide: true },
    )
    return { ok: true }
  } catch (err) {
    const message =
      err && typeof err === 'object' && err.message
        ? err.message
        : 'REG_DELETE_FAILED'
    return { ok: false, error: message }
  }
}

module.exports = {
  isRegistered,
  ensureAutoLaunch,
  removeAutoLaunch,
}
