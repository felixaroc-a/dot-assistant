import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const {
  parseWindowsUsbEnumJson,
  normalizeEnumeratedDisks,
  queryWindowsUsbDisks,
  getEnumerateScriptPath,
  resolveScriptPathForExec,
} = require('./windows-usb-detect.cjs')

const fixturesDir = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures', 'wmi-usb-enum')

function loadFixture(name: string): string {
  return readFileSync(path.join(fixturesDir, name), 'utf8')
}

describe('windows-usb-detect', () => {
  it('getEnumerateScriptPath apunta al .ps1 dedicado', () => {
    const scriptPath = getEnumerateScriptPath()
    expect(scriptPath).toMatch(/enumerate-usb-disks\.ps1$/)
  })

  it('resolveScriptPathForExec redirige app.asar → app.asar.unpacked', () => {
    const asarPath =
      'C:\\app\\resources\\app.asar\\electron\\scripts\\enumerate-usb-disks.ps1'
    const unpackedPath =
      'C:\\app\\resources\\app.asar.unpacked\\electron\\scripts\\enumerate-usb-disks.ps1'
    expect(resolveScriptPathForExec(asarPath)).toBe(asarPath)
    const { writeFileSync, mkdirSync, rmSync } = require('node:fs')
    const { dirname } = require('node:path')
    mkdirSync(dirname(unpackedPath), { recursive: true })
    writeFileSync(unpackedPath, '# stub')
    try {
      expect(resolveScriptPathForExec(asarPath)).toBe(unpackedPath)
    } finally {
      rmSync(dirname(dirname(dirname(unpackedPath))), { recursive: true, force: true })
    }
  })

  it('parseWindowsUsbEnumJson acepta objeto único o arreglo', () => {
    const one = parseWindowsUsbEnumJson(JSON.stringify({ Serial: 'SN001122', Drive: 'E:' }))
    expect(one).toHaveLength(1)
    const many = parseWindowsUsbEnumJson(
      JSON.stringify([
        { Serial: 'A1', Drive: 'E:' },
        { Serial: 'B2', Drive: 'F:' },
      ]),
    )
    expect(many).toHaveLength(2)
  })

  it('Kingston SCSI: serial WMI basura → fallback PNP con letra', async () => {
    const stdout = loadFixture('kingston-scsi-pnp.json')
    const devices = await queryWindowsUsbDisks({ fixtureStdout: stdout })
    expect(devices).toHaveLength(1)
    expect(devices[0].serial).toBe('2CFDA1BBB4CF1931090703CE')
    expect(devices[0].driveLetter).toBe('E:')
    expect(devices[0].source).toBe('usb')
    expect(devices[0].interfaceType).toBe('SCSI')
  })

  it('unidad removible (DriveType=2) sin InterfaceType USB', async () => {
    const devices = await queryWindowsUsbDisks({
      fixtureStdout: loadFixture('removable-only.json'),
    })
    expect(devices[0].serial).toBe('0123456789AB')
    expect(devices[0].driveLetter).toBe('F:')
    expect(devices[0].source).toBe('removable')
  })

  it('deduplica por serial (mismo disco vía usb + removable)', () => {
    const items = parseWindowsUsbEnumJson(loadFixture('dedupe-by-serial.json'))
    const devices = normalizeEnumeratedDisks(items)
    expect(devices).toHaveLength(1)
    expect(devices[0].serial).toBe('ABCD1234EFGH')
  })

  it('ignora entrada sin serial válido ni PNP útil', () => {
    const devices = normalizeEnumeratedDisks([
      { Serial: 'none', Drive: 'G:', PNPDeviceID: 'SCSI\\DISK&VEN_WDC' },
    ])
    expect(devices).toHaveLength(0)
  })
})
