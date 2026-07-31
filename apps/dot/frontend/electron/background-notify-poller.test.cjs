'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const { automationToastTitle } = require('./background-notify-poller.cjs')

test('automationToastTitle — briefing matutino', () => {
  assert.equal(
    automationToastTitle({ last_auto_id: 'morning-briefing-v1', last_auto_name: 'Tu día en 30s' }),
    'DOT — Tu día en 30s',
  )
})

test('automationToastTitle — cron recordatorio', () => {
  assert.equal(
    automationToastTitle({ last_auto_id: 'cron_reminder', last_auto_name: 'Recordatorio' }),
    'DOT — Recordatorio programado',
  )
})

test('automationToastTitle — aviso proactivo', () => {
  assert.equal(
    automationToastTitle({ last_auto_id: 'proactive_calendar', last_auto_name: 'Aviso proactivo calendario' }),
    'DOT — Aviso proactivo',
  )
})

test('automationToastTitle — automatización genérica', () => {
  assert.equal(
    automationToastTitle({ last_auto_id: 'auto-1', last_auto_name: 'Revisar correo' }),
    'DOT — Revisar correo',
  )
})
