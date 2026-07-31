// code-executor.cjs — Sandbox de ejecucion de JavaScript con V8 aislado (isolated-vm)
// Parte de DOT M2S1-A: ejecucion segura de codigo generado por IA en Electron.
//
// NOTA: isolated-vm requiere electron-rebuild contra la version de Electron
// instalada. En desarrollo sin compilacion nativa, executeCode() retorna
// error claro en vez de crashear.

var ivm = null;
try {
  ivm = require('isolated-vm');
} catch (e) {
  console.warn('[code-executor] isolated-vm no disponible:', e.message);
}

// Constantes
var DEFAULT_MEMORY_LIMIT = 64;
var DEFAULT_TIMEOUT_MS = 30000;
var MAX_CODE_LENGTH = 100000;
var MAX_INPUT_LENGTH = 1000000;

/**
 * Valida que el codigo no exceda los limites de seguridad.
 */
function validateInput(code, inputData) {
  if (typeof code !== 'string' || code.trim().length === 0) {
    return { valid: false, error: 'El codigo es requerido' };
  }
  if (code.length > MAX_CODE_LENGTH) {
    return { valid: false, error: 'El codigo excede el limite de ' + MAX_CODE_LENGTH + ' caracteres' };
  }
  try {
    var serialized = JSON.stringify(inputData);
    if (serialized.length > MAX_INPUT_LENGTH) {
      return { valid: false, error: 'inputData excede el limite de ' + MAX_INPUT_LENGTH + ' caracteres' };
    }
  } catch (e) {
    return { valid: false, error: 'inputData no se puede serializar a JSON' };
  }
  return { valid: true };
}

/**
 * Envuelve el codigo en una IIFE para permitir return.
 */
function wrapCode(code) {
  return '(function(inputData) { ' + code + ' })(inputData)';
}

/**
 * Detecta si el error es de timeout.
 */
function isTimeoutError(err) {
  var msg = (err && err.message) ? String(err.message).toLowerCase() : '';
  return msg.indexOf('timed out') !== -1 || msg.indexOf('timeout') !== -1;
}

/**
 * Detecta violaciones de seguridad.
 */
function detectSecurityViolation(err) {
  var msg = (err && err.message) ? String(err.message) : '';
  if (/require is not defined/i.test(msg)) return 'require is not defined — sin acceso a modulos de Node.js';
  if (/process is not defined/i.test(msg)) return 'process is not defined — sin acceso a process';
  if (/fs is not defined/i.test(msg) || /child_process/i.test(msg)) return 'Acceso denegado — API no permitida (fs/child_process)';
  return null;
}

/**
 * Configura el contexto del sandbox con APIs permitidas.
 */
async function setupSandboxContext(context) {
  var jail = context.global;
  await jail.set('console', new ivm.Reference({
    log: function() {}
  }));
}

/**
 * Ejecuta codigo JavaScript en un sandbox V8 aislado.
 * @param {string} code — Codigo a ejecutar. Usa return para devolver valor.
 * @param {*} inputData — Datos accesibles como inputData dentro del codigo.
 * @param {number} timeoutMs — Timeout en ms (default 30000).
 * @returns {Promise<{success: boolean, result?: *, error?: string, executionMs: number}>}
 */
async function executeCode(code, inputData, timeoutMs) {
  var start = Date.now();

  if (!ivm) {
    return {
      success: false,
      error: 'Sandbox no disponible: isolated-vm no compilado para Electron. Ejecuta: npx @electron/rebuild',
      executionMs: Date.now() - start
    };
  }

  var validation = validateInput(code, inputData);
  if (!validation.valid) {
    return { success: false, error: validation.error, executionMs: Date.now() - start };
  }

  var effectiveTimeout = (typeof timeoutMs === 'number' && timeoutMs > 0) ? timeoutMs : DEFAULT_TIMEOUT_MS;
  var isolate = null;

  try {
    isolate = new ivm.Isolate({ memoryLimit: DEFAULT_MEMORY_LIMIT });
    var context = await isolate.createContext();
    await setupSandboxContext(context);

    var jail = context.global;
    var inputCopy = new ivm.ExternalCopy(inputData);
    await jail.set('inputData', inputCopy.copyInto());

    var wrappedCode = wrapCode(code);
    var rawResult = await context.eval(wrappedCode, { timeout: effectiveTimeout });

    var result;
    if (rawResult && typeof rawResult === 'object' && typeof rawResult.copy === 'function') {
      try { result = await rawResult.copy(); } catch (e) { result = undefined; }
    } else {
      result = rawResult;
    }

    isolate.dispose();
    isolate = null;

    return { success: true, result: result, executionMs: Date.now() - start };

  } catch (err) {
    var elapsed = Date.now() - start;
    if (isolate) { try { isolate.dispose(); } catch (e) {} }

    if (isTimeoutError(err)) {
      return { success: false, error: 'timeout — excedio el tiempo maximo', executionMs: elapsed };
    }
    var secErr = detectSecurityViolation(err);
    if (secErr) {
      return { success: false, error: secErr, executionMs: elapsed };
    }

    return {
      success: false,
      error: (err && err.message) ? String(err.message).slice(0, 500) : 'Error desconocido en el sandbox',
      executionMs: elapsed
    };
  }
}

module.exports = { executeCode };
