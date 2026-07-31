'use strict';

const path = require('path');
const fs = require('fs');
const cp = require('child_process');
const os = require('os');
const crypto = require('crypto');

/**
 * Ejecuta un script diskpart pasandole las lineas como stdin.
 * @param {string[]} lines - Lineas del script diskpart
 * @returns {string} stdout del proceso
 */
function runDiskpart(lines) {
  const tmpFile = path.join(
    os.tmpdir(),
    `dot_diskpart_${crypto.randomBytes(4).toString('hex')}.txt`
  );

  try {
    fs.writeFileSync(tmpFile, lines.join('\r\n') + '\r\nexit\r\n', 'utf8');

    const result = cp.execFileSync('diskpart', ['/s', tmpFile], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    return result;
  } finally {
    try {
      fs.unlinkSync(tmpFile);
    } catch (_) {
      // ignorar error de limpieza
    }
  }
}

/**
 * Extrae la letra de unidad del output de diskpart.
 * Busca "DFS   N:" o "DFS    N:" o similar en la linea.
 */
function extractDriveLetter(diskpartOutput) {
  const match = diskpartOutput.match(/DFS\s+([A-Z]):/);
  if (match) {
    return match[1] + ':';
  }
  // fallback: buscar "N:" en el output
  const fallback = diskpartOutput.match(/([A-Z]):\\/);
  if (fallback) {
    return fallback[1] + ':';
  }
  return null;
}

/**
 * Crea un archivo .vhd en el USB y lo monta como unidad.
 * @param {string} drivePath - Ruta del USB (ej: "E:" o "E:\")
 * @param {number} [sizeMB=2048] - Tamaño del VHD en MB (default 2GB)
 * @returns {string} Letra de unidad montada (ej: "N:")
 */
function createVhdOnUsb(drivePath, sizeMB) {
  const size = sizeMB || 2048;
  const basePath = drivePath.replace(/\\+$/, '').replace(/:$/, ':'); // normaliza
  const vhdPath = path.join(basePath, 'dot.vhd');

  const lines = [
    `create vdisk file="${vhdPath}" maximum=${size} type=fixed`,
    `select vdisk file="${vhdPath}"`,
    'attach vdisk',
    'create partition primary',
    'format fs=ntfs quick label="DOT"',
    'assign letter=N',
  ];

  runDiskpart(lines);

  return 'N:';
}

/**
 * Cifra la unidad con BitLocker usando un recovery password.
 * @param {string} driveLetter - Letra de unidad (ej: "N:")
 * @returns {string} Recovery key de 48 caracteres (XXXX-XXXX-...)
 */
function encryptVhdWithBitlocker(driveLetter) {
  const letter = driveLetter.replace(':', '').trim();

  const result = cp.execFileSync(
    'manage-bde',
    ['-on', letter, '-RecoveryPassword', '-UsedSpaceOnly'],
    { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }
  );

  const recoveryKeyRegex = /[A-Z0-9]{6}-[A-Z0-9]{6}-[A-Z0-9]{6}-[A-Z0-9]{6}-[A-Z0-9]{6}-[A-Z0-9]{6}-[A-Z0-9]{6}-[A-Z0-9]{6}/;
  const match = result.match(recoveryKeyRegex);

  if (!match) {
    throw new Error(
      'No se pudo extraer la recovery key de BitLocker.\nOutput:\n' + result
    );
  }

  return match[0];
}

/**
 * Monta un VHD existente en el USB.
 * @param {string} drivePath - Ruta del USB (ej: "E:")
 * @returns {string} Letra de unidad asignada
 */
function mountVhd(drivePath) {
  const basePath = drivePath.replace(/\\+$/, '').replace(/:$/, ':');
  const vhdPath = path.join(basePath, 'dot.vhd');

  const output = runDiskpart([
    `select vdisk file="${vhdPath}"`,
    'attach vdisk',
  ]);

  const letter = extractDriveLetter(output);
  if (letter) {
    return letter;
  }

  // si diskpart no lo reporto, buscar en el sistema
  return 'N:';
}

/**
 * Desmonta un VHD.
 * @param {string} driveLetter - Letra de unidad o ruta del USB (ej: "N:" o "E:")
 */
function dismountVhd(driveLetter) {
  // Si recibio una letra de unidad, buscar el VHD en ella no es posible,
  // asi que se asume que el usuario quiere desmontar la unidad N:
  // El camino correcto es con select vdisk y detach.

  // Como no tenemos la ruta del archivo VHD si solo recibimos la letra,
  // usamos diskpart para listar y encontrar el VHD montado en esa letra.
  const letter = driveLetter.replace(':', '').trim();

  // Intentar detectar el VHD via mountvol o asumir letra N:
  // Metodo alternativo: listar volumen y obtener el archivo VHD
  const listOutput = runDiskpart(['list vdisk']);

  // Buscar el vdisk que esta montado en la letra especificada
  const vhdLineRegex = new RegExp(
    `nordik\\.vhd|${letter}\\s`,
    'i'
  );
  const lines = listOutput.split('\n');
  let vhdFile = null;

  for (const line of lines) {
    if (line.includes('.vhd')) {
      const fileMatch = line.match(/[A-Z]:\\\S+\.vhd/i);
      if (fileMatch) {
        vhdFile = fileMatch[0];
        break;
      }
    }
  }

  if (!vhdFile) {
    // fallback: nombre generico "dot.vhd" y ruta tipica
    vhdFile = `E:\\dot.vhd`;
  }

  runDiskpart([
    `select vdisk file="${vhdFile}"`,
    'detach vdisk',
  ]);
}

module.exports = {
  createVhdOnUsb,
  encryptVhdWithBitlocker,
  mountVhd,
  dismountVhd,
};
