'use strict';

/**
 * Detección USB en Windows (WMI/CIM vía script .ps1 dedicado).
 * Lógica compartida: docs/windows-usb-detection.md
 * Seriales: usb-serial-policy.cjs (espejo Python base.py + billing hardware_token).
 */
const fs = require('node:fs');
const path = require('node:path');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const usbSerialPolicy = require('./usb-serial-policy.cjs');

const execFileAsync = promisify(execFile);

const DEFAULT_PS_SCRIPT = path.join(__dirname, 'scripts', 'enumerate-usb-disks.ps1');

const sanitizeSerial = usbSerialPolicy.sanitizeUsbSerial;
const serialFromPnp = usbSerialPolicy.serialFromPnpDeviceId;

/**
 * @param {string} stdout
 * @returns {Array<Record<string, unknown>>}
 */
function parseWindowsUsbEnumJson(stdout) {
  const body = (stdout || '').trim();
  if (!body) return [];
  const parsed = JSON.parse(body);
  if (Array.isArray(parsed)) return parsed;
  if (parsed && typeof parsed === 'object') return [parsed];
  return [];
}

/**
 * @param {Array<Record<string, unknown>>} items
 * @returns {Array<{ serial: string, driveLetter: string, model: string, interfaceType: string, source: string, diskIndex: number | null }>}
 */
function normalizeEnumeratedDisks(items) {
  const seenSerials = new Set();
  const results = [];

  for (const item of items) {
    let serial = sanitizeSerial(item.Serial);
    if (!serial) serial = serialFromPnp(item.PNPDeviceID);
    if (!serial || seenSerials.has(serial.toLowerCase())) continue;
    seenSerials.add(serial.toLowerCase());

    const driveRaw = String(item.Drive || '').trim().toUpperCase();
    const driveLetter = /^[A-Z]:$/.test(driveRaw) ? driveRaw : '';

    results.push({
      serial,
      driveLetter,
      model: String(item.Model || '').trim(),
      interfaceType: String(item.InterfaceType || '').trim(),
      source: String(item.Source || '').trim() || 'unknown',
      diskIndex: Number.isFinite(Number(item.DiskIndex)) ? Number(item.DiskIndex) : null,
    });
  }

  return results;
}

/**
 * PowerShell no ejecuta .ps1 empaquetados dentro de app.asar; usar app.asar.unpacked.
 * @param {string} scriptPath
 * @returns {string}
 */
function resolveScriptPathForExec(scriptPath) {
  if (process.env.NORDIK_USB_ENUM_SCRIPT) return scriptPath;
  if (!scriptPath.includes('app.asar')) return scriptPath;
  const unpacked = scriptPath.replace('app.asar', 'app.asar.unpacked');
  if (fs.existsSync(unpacked)) return unpacked;
  return scriptPath;
}

/**
 * @returns {string}
 */
function getEnumerateScriptPath() {
  const configured = process.env.NORDIK_USB_ENUM_SCRIPT;
  if (configured) return configured;
  return resolveScriptPathForExec(DEFAULT_PS_SCRIPT);
}

/**
 * @param {{ scriptPath?: string, fixtureStdout?: string, timeoutMs?: number, rethrow?: boolean }} [options]
 * @returns {Promise<Array<{ serial: string, driveLetter: string, model: string, interfaceType: string, source: string, diskIndex: number | null }>>}
 */
async function queryWindowsUsbDisks(options = {}) {
  if (process.platform !== 'win32' && options.fixtureStdout == null) return [];

  try {
    let stdout;
    if (options.fixtureStdout != null) {
      stdout = options.fixtureStdout;
    } else {
      const scriptPath = options.scriptPath || getEnumerateScriptPath();
      const { stdout: psOut } = await execFileAsync(
        'powershell.exe',
        ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', scriptPath],
        { timeout: options.timeoutMs ?? 20000 },
      );
      stdout = psOut;
    }
    return normalizeEnumeratedDisks(parseWindowsUsbEnumJson(stdout));
  } catch (err) {
    if (options.rethrow) throw err;
    return [];
  }
}

/**
 * @param {{ scriptPath?: string, fixtureStdout?: string }} [options]
 * @returns {Promise<Array<{ serial: string, driveLetter: string, model?: string, interfaceType?: string, source?: string }>>}
 */
async function listAllUsbDrives(options = {}) {
  const disks = await queryWindowsUsbDisks(options);
  return disks.map((d) => ({
    serial: d.serial,
    driveLetter: d.driveLetter,
    model: d.model || undefined,
    interfaceType: d.interfaceType || undefined,
    source: d.source || undefined,
  }));
}

module.exports = {
  getEnumerateScriptPath,
  resolveScriptPathForExec,
  sanitizeSerial,
  serialFromPnp,
  parseWindowsUsbEnumJson,
  normalizeEnumeratedDisks,
  queryWindowsUsbDisks,
  listAllUsbDrives,
};
