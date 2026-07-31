#!/usr/bin/env node
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Diagnóstico de detección USB (Windows).
 *
 * Uso:
 *   npm run usb:diagnose
 *   node scripts/diagnose-usb-drives.cjs --list-json
 */
const usbDetect = require('../electron/windows-usb-detect.cjs')

function parseArgs(argv) {
  return { listJson: argv.includes('--list-json') }
}

async function main() {
  const { listJson } = parseArgs(process.argv.slice(2))

  if (process.platform !== 'win32') {
    const payload = { ok: false, code: 'UNSUPPORTED_PLATFORM', message: 'Solo Windows.', devices: [], count: 0 }
    if (listJson) {
      console.log(JSON.stringify(payload))
    } else {
      console.error('[Nordik USB]', payload.message)
    }
    process.exitCode = 1
    return
  }

  const scriptPath = usbDetect.getEnumerateScriptPath()
  let devices = []
  let psError = null

  try {
    devices = await usbDetect.queryWindowsUsbDisks({ rethrow: true })
  } catch (err) {
    psError = err && err.message ? err.message : String(err)
    try {
      devices = await usbDetect.queryWindowsUsbDisks()
    } catch {
      devices = []
    }
  }

  const normalized = devices.map((d) => ({
    serial: d.serial,
    driveLetter: d.driveLetter,
    model: d.model,
    interfaceType: d.interfaceType,
    source: d.source,
  }))
  const withLetter = normalized.filter((d) => d.driveLetter)
  const payload = {
    ok: withLetter.length > 0,
    code: withLetter.length > 0 ? 'USB_DETECT_OK' : devices.length > 0 ? 'USB_NO_DRIVE_LETTER' : 'USB_NOT_FOUND',
    message:
      withLetter.length > 0
        ? `${withLetter.length} USB listo(s) para provisión.`
        : devices.length > 0
          ? 'USB detectado sin letra asignada.'
          : 'No se detectaron pendrives USB.',
    scriptPath,
    psError,
    count: normalized.length,
    readyCount: withLetter.length,
    devices: normalized,
  }

  if (listJson) {
    console.log(JSON.stringify(payload, null, 2))
    process.exitCode = payload.ok ? 0 : devices.length > 0 ? 2 : 2
    return
  }

  console.log('[Nordik USB] Escaneando pendrives...')
  console.log(`Script: ${scriptPath}`)
  if (psError) console.log(`Advertencia PS: ${psError}`)
  console.log('')

  if (!devices.length) {
    console.log('Resultado: 0 dispositivos detectados.')
    console.log('')
    console.log('Comprueba:')
    console.log('  - El USB aparece en Explorador con letra (ej. E:)')
    console.log('  - Reconecta el USB y espera 3-5 segundos')
    console.log('  - npm run usb:diagnose -- --list-json')
    process.exitCode = 2
    return
  }

  console.log(`Resultado: ${devices.length} dispositivo(s)\n`)
  devices.forEach((d, idx) => {
    const letter = d.driveLetter || '(sin letra)'
    console.log(
      `${idx + 1}. ${letter}  serial=${d.serial}  model=${d.model || '?'}  iface=${d.interfaceType || '?'}  source=${d.source || '?'}`,
    )
  })
  console.log('')
  console.log(`Listos para provisión (con letra): ${withLetter.length}`)
  process.exitCode = withLetter.length > 0 ? 0 : 2
}

main().catch((err) => {
  console.error('[Nordik USB] Error:', err && err.message ? err.message : err)
  process.exitCode = 1
})
