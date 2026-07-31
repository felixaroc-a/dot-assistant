#!/usr/bin/env node
'use strict'
/* eslint-disable @typescript-eslint/no-require-imports */

/**
 * CLI de provisión USB para entrega comercial (delega en electron/usb-provision-delivery.cjs).
 */

const usbProvision = require('../electron/usb-provision-delivery.cjs')

const DEFAULT_API_BASE = usbProvision.DEFAULT_API_BASE

function printUsage() {
  console.log(
    [
      'Uso:',
      '  node scripts/provision-pendrive-delivery.cjs [opciones]',
      '',
      'Opciones:',
      '  --serial <serial>            Serial USB objetivo (si hay varios USB conectados).',
      '  --drive <letra>              Letra de unidad (ej: E:). Opcional.',
      '  --select-drive <letra>       Alias de --drive.',
      '  --drive-index <n>            Selecciona por índice (1..N) si hay múltiples USB.',
      '  --api-base <url>             Base URL Nordik API (default: http://127.0.0.1:8000).',
      '  --require-registered         Falla si el serial no está registrado en backend.',
      '  --force                      Reescribe vault aunque ya exista uno válido.',
      '  --no-installer               No copia instalador al USB.',
      '  --installer <ruta.exe>       Ruta explícita de instalador a copiar al USB.',
      '  --recovery-out <ruta.txt>    Guarda recovery key generada en archivo local.',
      '  --list-json                  Devuelve JSON con USB detectados y termina.',
      '  --json                       Devuelve salida estructurada JSON para integración.',
      '  --help                       Muestra esta ayuda.',
      '',
      'Ejemplos:',
      '  node scripts/provision-pendrive-delivery.cjs --require-registered',
      '  node scripts/provision-pendrive-delivery.cjs --serial 123ABC --drive E:',
      '  node scripts/provision-pendrive-delivery.cjs --drive-index 2',
      '  node scripts/provision-pendrive-delivery.cjs --installer "C:\\builds\\NordikIA.exe"',
    ].join('\n'),
  )
}

function parseArgs(argv) {
  const out = {
    serial: null,
    drive: null,
    driveIndex: null,
    apiBase: DEFAULT_API_BASE,
    requireRegistered: false,
    force: false,
    noInstaller: false,
    installer: null,
    recoveryOut: null,
    listJson: false,
    json: false,
    help: false,
  }

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (arg === '--help' || arg === '-h') {
      out.help = true
      continue
    }
    if (arg === '--list-json') {
      out.listJson = true
      continue
    }
    if (arg === '--json') {
      out.json = true
      continue
    }
    if (arg === '--require-registered') {
      out.requireRegistered = true
      continue
    }
    if (arg === '--force') {
      out.force = true
      continue
    }
    if (arg === '--no-installer') {
      out.noInstaller = true
      continue
    }

    const next = argv[i + 1]
    if (!next) {
      throw new Error(`Falta valor para ${arg}`)
    }
    if (arg === '--serial') {
      out.serial = next
      i += 1
      continue
    }
    if (arg === '--drive') {
      out.drive = next
      i += 1
      continue
    }
    if (arg === '--select-drive') {
      out.drive = next
      i += 1
      continue
    }
    if (arg === '--drive-index') {
      out.driveIndex = next
      i += 1
      continue
    }
    if (arg === '--api-base') {
      out.apiBase = next
      i += 1
      continue
    }
    if (arg === '--installer') {
      out.installer = next
      i += 1
      continue
    }
    if (arg === '--recovery-out') {
      out.recoveryOut = next
      i += 1
      continue
    }
    throw new Error(`Opción no reconocida: ${arg}`)
  }
  return out
}

function hasJsonFlag(argv) {
  return argv.includes('--json') || argv.includes('--list-json')
}

function writeJson(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`)
}

async function main() {
  const argv = process.argv.slice(2)
  const args = parseArgs(argv)

  if (args.help) {
    printUsage()
    return
  }

  if (args.listJson) {
    const listed = await usbProvision.listUsbDevices()
    writeJson(
      listed.ok
        ? {
            ok: true,
            code: listed.code || 'USB_LIST_OK',
            message: 'Lectura de USB completada.',
            devices: listed.devices,
            count: listed.count,
            serial: null,
            drive: null,
            recoveryKey: null,
            installerPath: null,
            error: null,
          }
        : {
            ok: false,
            code: listed.code || 'USB_LIST_FAILED',
            message: listed.error || 'No se pudieron listar dispositivos USB.',
            error: listed.error || 'No se pudieron listar dispositivos USB.',
            devices: listed.devices || [],
            count: listed.count || 0,
            serial: null,
            drive: null,
            recoveryKey: null,
            installerPath: null,
          },
    )
    if (!listed.ok) process.exitCode = 1
    return
  }

  if (!args.json) {
    console.log('\n[Nordik] Iniciando provisión de pendrive para entrega...\n')
  }

  const core = await usbProvision.provisionUsbDelivery({
    serial: args.serial,
    drive: args.drive,
    driveIndex: args.driveIndex,
    apiBase: args.apiBase,
    requireRegistered: args.requireRegistered,
    force: args.force,
    copyInstaller: !args.noInstaller,
    installer: args.installer,
    recoveryOut: args.recoveryOut,
  })

  const payload = usbProvision.toLegacyCliPayload(core)

  if (args.json) {
    writeJson(payload)
    if (!payload.ok) process.exitCode = 1
    return
  }

  if (!payload.ok) {
    throw new Error(payload.message || payload.error || 'Error de provisión USB.')
  }

  const result = payload.result || {}
  const steps = Array.isArray(payload.steps) ? payload.steps : []
  for (const step of steps) {
    const prefix = step.status === 'error' ? '[ERROR]' : step.status === 'warn' ? '[WARN]' : '[OK]'
    if (!args.json) {
      console.log(`${prefix} ${step.message || step.key || 'paso'}`)
    }
  }

  console.log('\nResumen de provisión')
  console.log('--------------------')
  console.log(`USB: ${result.driveLetter || payload.drive}`)
  console.log(`Serial: ${result.serial || payload.serial}`)
  console.log(`Vault regenerado: ${result.vaultRegenerated ? 'si' : 'no'}`)
  console.log(`Instalador copiado: ${result.installerCopied ? 'si' : 'no'}`)
  if (result.installerPath || payload.installerPath) {
    console.log(`Ruta instalador USB: ${result.installerPath || payload.installerPath}`)
  }
  if (result.recoveryKey || payload.recoveryKey) {
    console.log(`Recovery key nueva: ${result.recoveryKey || payload.recoveryKey}`)
  }
  if (result.recoveryFile) {
    console.log(`Archivo recovery guardado en: ${result.recoveryFile}`)
  }
  console.log('\nListo. El USB quedó preparado para entrega de Nordik.\n')
}

main().catch((err) => {
  const message = err && err.message ? err.message : 'Error inesperado en provisión USB.'
  if (hasJsonFlag(process.argv.slice(2))) {
    writeJson({
      ok: false,
      code: 'PROVISION_UNEXPECTED_ERROR',
      message,
      error: message,
      serial: null,
      drive: null,
      recoveryKey: null,
      installerPath: null,
    })
    process.exit(1)
    return
  }
  console.error(`\n[ERROR] ${message}\n`)
  process.exit(1)
})
