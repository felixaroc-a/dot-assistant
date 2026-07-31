'use strict'

/**
 * Smoke unitario sin Electron: validateUrl allowlist (Fase 2 DoD parcial).
 */
const assert = require('node:assert/strict')
const { validateUrl } = require('./browser-automation.cjs')

assert.equal(validateUrl('https://example.com/x').ok, true)
assert.equal(validateUrl('http://127.0.0.1/').ok, false)
assert.equal(validateUrl('file:///etc/passwd').ok, false)
assert.equal(validateUrl('ftp://x').ok, false)
assert.equal(validateUrl('').ok, false)

const mod = require('./browser-automation.cjs')
assert.equal(typeof mod.click, 'function')
assert.equal(typeof mod.type, 'function')
assert.equal(typeof mod.waitFor, 'function')
assert.equal(typeof mod.extractPrice, 'function')
assert.equal(typeof mod.screenshot, 'function')
assert.equal(typeof mod.fill, 'function')
assert.equal(typeof mod.openSession, 'function')
assert.equal(typeof mod.doAction, 'function')
assert.equal(typeof mod.closeSessionExtract, 'function')

// M1S2-B: nuevas operaciones CDP
assert.equal(typeof mod.screenshotElement, 'function', 'screenshotElement debe ser function')
assert.equal(typeof mod.fillFormAdvanced, 'function', 'fillFormAdvanced debe ser function')

console.log('browser-automation validateUrl + API smoke OK (BR02-BR06 + M1S2-B included)')
