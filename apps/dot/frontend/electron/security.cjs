/** Anti-DevTools y comprobaciones básicas en producción empaquetada. */
const { app } = require('electron')

function isProductionPackaged() {
  return app.isPackaged
}

function attachDevToolsProtection(win) {
  if (!isProductionPackaged() || !win?.webContents) return

  const wc = win.webContents
  wc.on('devtools-opened', () => {
    wc.closeDevTools()
  })

  const interval = setInterval(() => {
    if (win.isDestroyed()) {
      clearInterval(interval)
      return
    }
    if (wc.isDevToolsOpened()) {
      wc.closeDevTools()
    }
  }, 2000)

  win.on('closed', () => clearInterval(interval))
}

module.exports = { attachDevToolsProtection, isProductionPackaged }
