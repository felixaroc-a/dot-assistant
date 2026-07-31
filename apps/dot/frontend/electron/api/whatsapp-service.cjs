'use strict'

/**
 * whatsapp-service.cjs — Fachada WhatsApp para Electron IPC.
 *
 * Reemplazo de openclaw-process.cjs (FASE 1.1).
 * Delega toda la lógica de transporte a BaileysTransport vía transport/index.cjs.
 * OpenClaw eliminado; no hay fallback legacy.
 */

const { getTransport } = require('../whatsapp/transport/index.cjs')

/**
 * Inicia login QR en el transporte activo (Baileys).
 * @param {{ clearSession?: boolean } | undefined} opts
 * @returns {Promise<{ ok: true } | { ok: false; error: string }>}
 */
function startWhatsAppLogin(opts) {
  return getTransport().startLogin(opts)
}

/** Detiene el proceso de login QR. */
function stop() {
  return getTransport().stopLogin()
}

/** ¿Hay un login en curso? */
function isRunning() {
  return getTransport().isLoginRunning()
}

/**
 * Instalación de plugins de automatización.
 * OpenClaw fue eliminado; esta función retorna error informativo.
 * @returns {Promise<{ ok: false; error: string }>}
 */
async function installAutomationPlugins() {
  return {
    ok: false,
    error: 'OpenClaw eliminado — FASE 1.1 completa. Las automatizaciones usan Baileys nativamente.',
  }
}

/** No-op: Baileys no necesita pre-calentamiento. */
function warmup() {
  // No-op intencional
}

module.exports = {
  startWhatsAppLogin,
  stop,
  isRunning,
  installAutomationPlugins,
  warmup,
}
