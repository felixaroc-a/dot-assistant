/**
 * Entry point ESM para DOT (Electron 40+).
 *
 * Electron 40 + Node v24 tiene problemas con import ESM de 'electron'.
 * Usamos createRequire para cargar electron como CJS.
 */
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const require = createRequire(import.meta.url);

// Cargar electron con require() en lugar de import ESM
const electron = require('electron');
const { app, BrowserWindow, Notification, dialog, ipcMain, nativeTheme, shell, session } = electron;

if (!app) {
  console.error('[DOT] electron.app es undefined');
  process.exit(1);
}

// Variables de entorno
require('./load-backend-env.cjs');

// Módulos propios
const secureStorage = require('./secure-storage.cjs');
const localTools = require('./local-tools.cjs');
const { attachDevToolsProtection } = require('./security.cjs');
const usbSerial = require('./usb-serial.cjs');
const pendriveGate = require('./pendrive-gate.cjs');
const pendriveCrypto = require('./pendrive-crypto.cjs');
const autoLaunch = require('./auto-launch.cjs');
const whatsappService = require('./api/whatsapp-service.cjs');
const registerIpcHandlers = require('./ipc-handlers.cjs');

const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;

/** @type {BrowserWindow | null} */
let mainWindow = null;
function getMainWindow() { return mainWindow; }

// ─── Helpers ──────────────────────────────────────────────────
const fs = require('node:fs');
const path = require('node:path');

function resolveAppIcon() {
  const candidates = [join(__dirname, 'icon.ico'), join(__dirname, 'icon.png')];
  for (const c of candidates) { if (fs.existsSync(c)) return c; }
  return undefined;
}
function buildDesktopCsp() {
  const apiBase = (process.env.DOT_API_BASE_URL || process.env.NORDIK_API_BASE_URL || '').trim().replace(/\/$/, '');
  const connect = new Set(["'self'"]);
  if (apiBase) connect.add(apiBase);
  if (isDev) { connect.add('http://127.0.0.1:5173'); connect.add('ws://127.0.0.1:5173'); }
  return [
    "default-src 'self'", "script-src 'self'", "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:", "font-src 'self' data:",
    `connect-src ${Array.from(connect).join(' ')}`,
    "frame-ancestors 'none'", "base-uri 'self'", "object-src 'none'",
  ].join('; ');
}
function configureSessionSecurity() {}
function ensureSecureStorageAvailability() { return true; }
function sanitizeTaskSegment(value, fallback = 'item') {
  const raw = typeof value === 'string' ? value : '';
  return raw.replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 40) || fallback;
}
function sanitizeReminderText(text) {
  const raw = typeof text === 'string' ? text : '';
  return raw.replace(/[\r\n\t]+/g, ' ').replace(/"/g, "'").trim().slice(0, 180);
}
function sanitizeNotificationText(text, max = 220) {
  const raw = typeof text === 'string' ? text : '';
  return raw.replace(/[\r\n\t]+/g, ' ').trim().slice(0, max);
}
function formatSchtasksDate(value) {
  return `${value.getFullYear()}/${String(value.getMonth()+1).padStart(2,'0')}/${String(value.getDate()).padStart(2,'0')}`;
}
function formatSchtasksTime(value) {
  return `${String(value.getHours()).padStart(2,'0')}:${String(value.getMinutes()).padStart(2,'0')}`;
}
function parseBooleanEnv(value, fallback = false) {
  if (typeof value !== 'string') return fallback;
  const n = value.trim().toLowerCase();
  if (!n) return fallback;
  if (['1','true','yes','on'].includes(n)) return true;
  if (['0','false','no','off'].includes(n)) return false;
  return fallback;
}
function buildUpdaterFeedConfig() {
  const genericUrl = (process.env.DOT_UPDATER_URL || process.env.NORDIK_UPDATER_URL || '').trim();
  if (genericUrl) return { provider: 'generic', url: genericUrl, channel: (process.env.DOT_UPDATER_CHANNEL || process.env.NORDIK_UPDATER_CHANNEL || 'latest').trim() || 'latest', useMultipleRangeRequest: false };
  const owner = (process.env.DOT_UPDATER_GH_OWNER || process.env.NORDIK_UPDATER_GH_OWNER || '').trim();
  const repo = (process.env.DOT_UPDATER_GH_REPO || process.env.NORDIK_UPDATER_GH_REPO || '').trim();
  if (!owner || !repo) return null;
  const isPrivate = parseBooleanEnv(process.env.DOT_UPDATER_GH_PRIVATE || process.env.NORDIK_UPDATER_GH_PRIVATE, false);
  const token = (process.env.DOT_UPDATER_GH_TOKEN || process.env.NORDIK_UPDATER_GH_TOKEN || process.env.GH_TOKEN || '').trim();
  return { provider: 'github', owner, repo, private: isPrivate, releaseType: 'release', ...(token ? { token } : {}) };
}
function configureAutoUpdater() {
  if (process.platform !== 'win32' || !app.isPackaged) return;
  if (!parseBooleanEnv(process.env.DOT_AUTO_UPDATE_ENABLED || process.env.NORDIK_AUTO_UPDATE_ENABLED, true)) return;
  let autoUpdater;
  try { autoUpdater = require('electron-updater').autoUpdater; } catch (err) { console.warn('[updater]', err.message); return; }
  const feedConfig = buildUpdaterFeedConfig();
  if (!feedConfig) { console.info('[updater] Desactivado: falta configurar feed.'); return; }
  try { autoUpdater.setFeedURL(feedConfig); } catch (error) { console.error('[updater] Error feed:', error); return; }
  autoUpdater.autoDownload = true; autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.allowPrerelease = parseBooleanEnv(process.env.DOT_UPDATER_ALLOW_PRERELEASE || process.env.NORDIK_UPDATER_ALLOW_PRERELEASE, false);
  let hasDownloadedUpdate = false;
  autoUpdater.on('update-available', (info) => {
    try { if (!Notification.isSupported()) return; new Notification({ title: 'Actualización disponible', body: `Descargando versión ${info?.version || ''}`, silent: true }).show(); } catch {}
  });
  autoUpdater.on('update-downloaded', (info) => {
    try { if (!Notification.isSupported()) return; const toast = new Notification({ title: 'Actualización lista', body: 'Reinicia para instalar', silent: false }); toast.on('click', () => { try { autoUpdater.quitAndInstall(false, true); } catch {} }); toast.show(); } catch {}
  });
  autoUpdater.on('error', (error) => console.error('[updater] Error:', error));
  void autoUpdater.checkForUpdates().catch((error) => console.error('[updater] Error check:', error));
}
function createWindow() {
  nativeTheme.themeSource = 'dark';
  const win = new BrowserWindow({
    width: 1280, height: 800, minWidth: 960, minHeight: 640,
    title: 'DOT', icon: resolveAppIcon(), backgroundColor: '#000000',
    show: false, autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, 'preload.cjs'),
      contextIsolation: true, nodeIntegration: false,
      sandbox: true, webSecurity: true, allowRunningInsecureContent: false,
    },
  });
  win.once('ready-to-show', () => win.show());
  mainWindow = win;
  attachDevToolsProtection(win);
  win.on('closed', () => { if (mainWindow === win) mainWindow = null; });
  if (isDev) {
    win.loadURL('http://127.0.0.1:5173/');
    if (process.env.ELECTRON_OPEN_DEVTOOLS === '1') win.webContents.openDevTools({ mode: 'detach' });
  } else {
    win.loadFile(join(__dirname, '..', 'dist', 'index.html'));
  }
}

// ─── Arranque ─────────────────────────────────────────────────
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    const [win] = BrowserWindow.getAllWindows();
    if (win) { if (win.isMinimized()) win.restore(); win.focus(); }
  });

  app.whenReady().then(() => {
    if (!ensureSecureStorageAvailability()) return;
    configureSessionSecurity();

    registerIpcHandlers({
      ipcMain, BrowserWindow, Notification, shell, secureStorage, usbSerial,
      pendriveCrypto, pendriveGate, localTools, whatsappService, app,
      mainWindowRef: getMainWindow,
      sanitizeNotificationText, sanitizeTaskSegment, sanitizeReminderText,
      formatSchtasksDate, formatSchtasksTime,
    });

    configureAutoUpdater();
    createWindow();

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
}
