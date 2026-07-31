'use strict'

/**
 * Toast nativo de Windows para DOT (funciona con ventana oculta en bandeja).
 */

/**
 * @param {{
 *   Notification: typeof import('electron').Notification
 *   sanitizeNotificationText: (text: string, max?: number) => string
 *   showMainWindow?: () => void
 *   onClick?: () => void
 * }} deps
 */
function createSystemNotifier(deps) {
  const { Notification, sanitizeNotificationText, showMainWindow, onClick } = deps

  /**
   * @param {string} title
   * @param {string} body
   * @returns {boolean}
   */
  function showSystemToast(title, body) {
    try {
      if (process.platform !== 'win32' || !Notification.isSupported()) {
        return false
      }
      const safeTitle = sanitizeNotificationText(title, 120)
      const safeBody = sanitizeNotificationText(body, 300)
      if (!safeTitle || !safeBody) return false

      const toast = new Notification({ title: safeTitle, body: safeBody, silent: false })
      toast.on('click', () => {
        if (typeof showMainWindow === 'function') {
          showMainWindow()
        }
        if (typeof onClick === 'function') {
          onClick()
        }
      })
      toast.show()
      return true
    } catch {
      return false
    }
  }

  return { showSystemToast }
}

module.exports = { createSystemNotifier }
