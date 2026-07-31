'use strict'

/**
 * Interfaz abstracta WhatsappTransport.
 *
 * Define el contrato que toda implementación de transporte WhatsApp debe cumplir.
 * Cualquier método no sobrescrito lanza un error indicando que no está implementado.
 */
class WhatsappTransport {

  // ─── Ciclo de vida ─────────────────────────────────────

  /**
   * Inicializa el transporte (verifica dependencias, prepara recursos).
   * @returns {Promise<{ ok: boolean; error?: string }>}
   */
  async initialize() {
    throw new Error('WhatsappTransport#initialize: método no implementado')
  }

  /**
   * Inicia el flujo de login/vinculación (QR).
   * @param {{ onChunk: (chunk: { stream: 'stdout' | 'stderr'; text: string }) => void; onLinked?: (data: { linked: boolean; phone_number?: string }) => void; onExit?: (info: { code: number | null; signal: string | null }) => void }} opts
   * @returns {Promise<{ ok: boolean; error?: string }>}
   */
  async startLogin(opts) {
    throw new Error('WhatsappTransport#startLogin: método no implementado')
  }

  /**
   * Inicia el daemon/gateway persistente de WhatsApp.
   * @param {string} [reason]
   * @returns {Promise<{ ok: boolean; error?: string }>}
   */
  async startDaemon(reason) {
    throw new Error('WhatsappTransport#startDaemon: método no implementado')
  }

  /**
   * Detiene el daemon.
   * @returns {{ ok: boolean }}
   */
  stopDaemon() {
    throw new Error('WhatsappTransport#stopDaemon: método no implementado')
  }

  /**
   * Detiene el flujo de login.
   * @returns {{ ok: boolean }}
   */
  stopLogin() {
    throw new Error('WhatsappTransport#stopLogin: método no implementado')
  }

  /**
   * Detiene login + daemon.
   * @returns {{ ok: boolean }}
   */
  stopAll() {
    throw new Error('WhatsappTransport#stopAll: método no implementado')
  }

  /**
   * Libera todos los recursos, mata procesos, limpia timers.
   */
  shutdown() {
    throw new Error('WhatsappTransport#shutdown: método no implementado')
  }

  // ─── Estado ────────────────────────────────────────────

  /**
   * @returns {object} Estado actual del transporte
   */
  getStatus() {
    throw new Error('WhatsappTransport#getStatus: método no implementado')
  }

  /**
   * Registra un listener para cambios de estado.
   * @param {(status: object) => void} listener
   * @returns {() => void} Función para desuscribirse
   */
  onStatusChange(listener) {
    throw new Error('WhatsappTransport#onStatusChange: método no implementado')
  }

  /**
   * @returns {boolean}
   */
  isLoginRunning() {
    throw new Error('WhatsappTransport#isLoginRunning: método no implementado')
  }

  /**
   * @returns {boolean}
   */
  isDaemonRunning() {
    throw new Error('WhatsappTransport#isDaemonRunning: método no implementado')
  }

  // ─── Mensajería ────────────────────────────────────────

  /**
   * Envía un mensaje de WhatsApp.
   * @param {string} to
   * @param {string} text
   * @returns {Promise<{ ok: boolean; message_id?: string; error?: string }>}
   */
  async sendMessage(to, text) {
    throw new Error('WhatsappTransport#sendMessage: método no implementado')
  }

  /**
   * Envía imagen o documento por WhatsApp.
   * @param {string} to
   * @param {string} filePath
   * @param {{ mediaType?: 'image' | 'document'; caption?: string; mimetype?: string; fileName?: string }} [opts]
   * @returns {Promise<{ ok: boolean; message_id?: string; error?: string }>}
   */
  async sendMedia(to, filePath, opts) {
    throw new Error('WhatsappTransport#sendMedia: método no implementado')
  }

  /**
   * Registra un callback para mensajes entrantes.
   * @param {(payload: Record<string, unknown>) => Promise<void> | void} callback
   * @returns {() => void} Función para desuscribirse
   */
  onInboundMessage(callback) {
    throw new Error('WhatsappTransport#onInboundMessage: método no implementado')
  }

  /**
   * Registra un callback para descargas de media (T13).
   * @param {(payload: { message_id: string; ok: boolean; file_path?: string; mime_type?: string; size?: number; error?: string }) => void} callback
   * @returns {() => void} Función para desuscribirse
   */
  onMediaDownloaded(callback) {
    // Default no-op: implementaciones que no soportan media no rompen.
    return () => {}
  }

  // ─── Utilidad ──────────────────────────────────────────

  /**
   * Verifica si hay una configuración local de WhatsApp.
   * @returns {Promise<{ configured: boolean; raw?: string }>}
   */
  async probeConfigured() {
    throw new Error('WhatsappTransport#probeConfigured: método no implementado')
  }

  /**
   * Resuelve/asegura el número de teléfono propio.
   * @param {string | null | undefined} hint
   * @returns {string | null}
   */
  ensureOwnPhone(hint) {
    throw new Error('WhatsappTransport#ensureOwnPhone: método no implementado')
  }

  /**
   * Aplica política de seguridad del transporte (p. ej. allowlist de grupos).
   * @param {{ linkedPhone?: string | null; allowRestart?: boolean }} [opts]
   * @returns {object}
   */
  applyPolicy(opts) {
    throw new Error('WhatsappTransport#applyPolicy: método no implementado')
  }

  /**
   * Pre-calentamiento opcional del transporte (OpenClaw fallback; Baileys no-op).
   */
  warmup() {
    throw new Error('WhatsappTransport#warmup: método no implementado')
  }
}

module.exports = { WhatsappTransport }
