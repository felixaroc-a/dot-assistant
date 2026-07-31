import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const pendriveCrypto = require('./pendrive-crypto.cjs')
const usbDetect = require('./windows-usb-detect.cjs')

const { sanitizeSerial, serialFromPnp, parseWindowsUsbEnumJson } = pendriveCrypto
const { queryWindowsUsbDisks } = usbDetect

describe('pendrive-crypto USB parsing', () => {
  it('sanitizeSerial rechaza seriales inválidos', () => {
    expect(sanitizeSerial('')).toBeNull()
    expect(sanitizeSerial('none')).toBeNull()
    expect(sanitizeSerial('abc')).toBeNull()
    expect(sanitizeSerial('0000000005')).toBeNull()
    expect(sanitizeSerial('000000000000')).toBeNull()
    expect(sanitizeSerial('ABCD-1234')).toBe('ABCD-1234')
    expect(sanitizeSerial('ABCD1234&0')).toBe('ABCD1234')
  })

  it('serialFromPnp extrae serial cuando WMI trae caracteres de control', () => {
    expect(sanitizeSerial('0000000005\u0006\u0018')).toBeNull()
    const pnp =
      'USBSTOR\\DISK&VEN_KINGSTON&PROD_DATATRAVELER_3.0&REV_0000\\2CFDA1BBB4CF1931090703CE&0'
    expect(serialFromPnp(pnp)).toBe('2CFDA1BBB4CF1931090703CE')
  })

  it('Kingston fixture: PNP fallback vía windows-usb-detect', async () => {
    const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures', 'wmi-usb-enum')
    const stdout = readFileSync(path.join(dir, 'kingston-scsi-pnp.json'), 'utf8')
    const devices = await queryWindowsUsbDisks({ fixtureStdout: stdout })
    expect(devices[0].serial).toBe('2CFDA1BBB4CF1931090703CE')
    expect(devices[0].driveLetter).toBe('E:')
  })

  it('parseWindowsUsbEnumJson acepta objeto único o arreglo', () => {
    const one = parseWindowsUsbEnumJson(
      JSON.stringify({ Serial: 'SN001122', Drive: 'E:', Source: 'usb' }),
    )
    expect(one).toHaveLength(1)
    expect(one[0].Serial).toBe('SN001122')

    const many = parseWindowsUsbEnumJson(
      JSON.stringify([
        { Serial: 'A1', Drive: 'E:' },
        { Serial: 'B2', Drive: 'F:' },
      ]),
    )
    expect(many).toHaveLength(2)
  })
})
