/**
 * Script de setup del pendrive DOT (llave física USB).
 *
 * Funcionalidad:
 * 1. Detectar pendrive USB conectado
 * 2. Opción A (Windows Pro): BitLocker To Go via manage-bde
 * 3. Opción B (Windows Home/fallback): Archivo cifrado AES-256-GCM
 * 4. El pendrive NO debe tener archivos visibles (solo dot.vault oculto)
 *
 * Uso: requiere('child_process') para ejecutar manage-bde (Windows Pro)
 * o crear el vault cifrado directamente (todas las ediciones).
 */
const { execFile } = require('node:child_process');
const fs = require('fs');
const path = require('path');
const { promisify } = require('node:util');

const execFileAsync = promisify(execFile);

const pendriveCrypto = require('./pendrive-crypto.cjs');

/** BitLocker recovery password length (48 dígitos en 8 grupos de 6) */
const BL_RECOVERY_LENGTH = 48;

/**
 * Detecta si BitLocker To Go está disponible en el sistema (Windows Pro/Enterprise/Education).
 * @returns {Promise<boolean>}
 */
async function isBitLockerAvailable() {
  if (process.platform !== 'win32') return false;

  try {
    const { stdout } = await execFileAsync('manage-bde.exe', ['-status'], { timeout: 10000 });
    return stdout.includes('BitLocker');
  } catch {
    return false;
  }
}

/**
 * Obtiene la edición de Windows.
 * @returns {Promise<string>}
 */
async function getWindowsEdition() {
  if (process.platform !== 'win32') return 'unknown';

  try {
    const ps = [
      '-NoProfile',
      '-Command',
      "(Get-CimInstance Win32_OperatingSystem).Caption",
    ];
    const { stdout } = await execFileAsync('powershell.exe', ps, { timeout: 10000 });
    return stdout.trim();
  } catch {
    return 'unknown';
  }
}

/**
 * Detecta si el sistema tiene soporte para BitLocker.
 * @returns {Promise<{ available: boolean, edition: string, reason?: string }>}
 */
async function detectBitLockerSupport() {
  if (process.platform !== 'win32') {
    return { available: false, edition: 'no-windows', reason: 'BitLocker solo está disponible en Windows' };
  }

  const edition = await getWindowsEdition();
  const hasBitLockerCmd = await isBitLockerAvailable();

  if (!hasBitLockerCmd) {
    return { available: false, edition, reason: 'manage-bde.exe no encontrado. BitLocker requiere Windows Pro/Enterprise/Education.' };
  }

  const isProOrBetter = /Pro|Enterprise|Education|Workstation/i.test(edition);
  if (!isProOrBetter) {
    return { available: false, edition, reason: `Edición "${edition}" no soporta BitLocker. Se usará modo fallback AES-256-GCM.` };
  }

  return { available: true, edition };
}

/**
 * Valida que la letra de unidad sea una letra de unidad válida.
 * @param {string} driveLetter
 * @returns {boolean}
 */
function isValidDriveLetter(driveLetter) {
  return typeof driveLetter === 'string' && /^[A-Z]:$/i.test(driveLetter.trim());
}

/**
 * Verifica que la unidad exista y sea extraíble.
 * @param {string} driveLetter - Ej: "D:"
 * @returns {Promise<{ ok: boolean, error?: string }>}
 */
async function verifyRemovableDrive(driveLetter) {
  if (!isValidDriveLetter(driveLetter)) {
    return { ok: false, error: 'Letra de unidad inválida' };
  }

  const dl = driveLetter.trim().toUpperCase();
  const drivePath = dl + '\\';

  if (!fs.existsSync(drivePath)) {
    return { ok: false, error: `La unidad ${dl} no existe` };
  }

  try {
    const stats = fs.statSync(drivePath);
    if (!stats.isDirectory()) {
      return { ok: false, error: `La ruta ${drivePath} no es una unidad válida` };
    }
  } catch {
    return { ok: false, error: `No se puede acceder a la unidad ${dl}` };
  }

  // En Windows, verificar que sea extraíble via WMI
  if (process.platform === 'win32') {
    try {
      const ps = [
        '-NoProfile',
        '-Command',
        `Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='${dl}'" | Select-Object -ExpandProperty DriveType`,
      ];
      const { stdout } = await execFileAsync('powershell.exe', ps, { timeout: 10000 });
      const driveType = parseInt(stdout.trim(), 10);
      // DriveType 2 = Removable, 3 = Local Fixed
      if (driveType !== 2) {
        return { ok: false, error: `La unidad ${dl} no es extraíble (tipo: ${driveType}). Conecta un pendrive USB.` };
      }
    } catch {
      // Si falla la verificación, continuar de todas formas
    }
  }

  return { ok: true };
}

/**
 * Opción A: Activar BitLocker To Go en el pendrive.
 *
 * Requiere permisos de administrador. Si no es admin, muestra advertencia.
 *
 * @param {string} driveLetter - Ej: "D:"
 * @returns {Promise<{ ok: boolean, recoveryPassword?: string, error?: string }>}
 */
async function setupBitLocker(driveLetter) {
  if (process.platform !== 'win32') {
    return { ok: false, error: 'BitLocker solo está disponible en Windows' };
  }

  // Validar que el proceso corre como administrador
  try {
    const { stdout: adminCheck } = await execFileAsync(
      'powershell.exe',
      ['-NoProfile', '-Command', '([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)'],
      { timeout: 10000 },
    );
    if (adminCheck.trim().toLowerCase() !== 'true') {
      return {
        ok: false,
        error: 'Se requieren permisos de administrador para activar BitLocker. Ejecuta DOT como administrador o usa el modo AES-256-GCM (no requiere admin).',
      };
    }
  } catch {
    return { ok: false, error: 'No se pudo verificar si el proceso tiene permisos de administrador.' };
  }

  const dl = driveLetter.trim().toUpperCase();

  try {
    // 1. Verificar que no esté ya activado
    const { stdout: statusOut } = await execFileAsync('manage-bde.exe', ['-status', dl], { timeout: 15000 });
    if (statusOut.includes('Protección activada') || statusOut.includes('Protection On')) {
      return { ok: false, error: `BitLocker ya está activado en la unidad ${dl}` };
    }

    // 2. Generar recovery password aleatoria
    const recoveryPassword = generateRecoveryPassword();

    // 3. Activar BitLocker con recovery password (sin TPM, modo USB)
    //    -Used: solo cifrar espacio usado (más rápido)
    //    -rp: recovery password
    await execFileAsync('manage-bde.exe', [
      '-on', dl,
      '-Used',
      '-rp', recoveryPassword,
    ], { timeout: 300000 }); // 5 minutos máximo

    return { ok: true, recoveryPassword };
  } catch (err) {
    return { ok: false, error: `Error al activar BitLocker: ${err.message}` };
  }
}

/**
 * Genera una recovery password de BitLocker (48 dígitos en formato 8 grupos de 6).
 * @returns {string}
 */
function generateRecoveryPassword() {
  const groups = [];
  for (let g = 0; g < 8; g++) {
    let group = '';
    for (let i = 0; i < 6; i++) {
      group += Math.floor(Math.random() * 10).toString();
    }
    groups.push(group);
  }
  return groups.join('-');
}

/**
 * Obtiene información del USB: nombre del modelo y tamaño.
 * @param {string} driveLetter - Ej: "D:"
 * @returns {Promise<{ model: string, sizeGB: string, freeGB: string }>}
 */
async function getUsbDriveInfo(driveLetter) {
  let model = 'USB';
  let sizeGB = '?';
  let freeGB = '?';

  if (process.platform === 'win32') {
    try {
      const cleanLetter = driveLetter.trim().toUpperCase().replace(':', '');
      const ps = [
        '-NoProfile',
        '-Command',
        `Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='${cleanLetter}:'" | Select-Object Size, FreeSpace, VolumeName | ConvertTo-Json -Compress`,
      ];
      const { stdout } = await execFileAsync('powershell.exe', ps, { timeout: 10000 });
      const info = JSON.parse(stdout.trim());
      if (info) {
        sizeGB = info.Size ? (Number(info.Size) / (1024 ** 3)).toFixed(1) : '?';
        freeGB = info.FreeSpace ? (Number(info.FreeSpace) / (1024 ** 3)).toFixed(1) : '?';
        model = info.VolumeName || 'USB';
      }
    } catch { /* ignorar */ }

    try {
      const cleanLetter = driveLetter.trim().toUpperCase().replace(':', '');
      const ps = [
        '-NoProfile',
        '-Command',
        `Get-CimInstance Win32_DiskDrive | Where-Object { ($_.DeviceID -replace '\\\\\\\\\\\\.\\\\\\\PHYSICALDRIVE','') -eq (Get-CimInstance Win32_LogicalDiskToPartition -Filter "Dependent.DeviceID='${cleanLetter}:'" | ForEach-Object { $_.Antecedent } | Get-CimInstance Win32_DiskPartition | Select-Object -ExpandProperty DiskIndex) } | Select-Object -ExpandProperty Model`,
      ];
      const { stdout } = await execFileAsync('powershell.exe', ps, { timeout: 10000 });
      const detectedModel = stdout.trim();
      if (detectedModel) model = detectedModel;
    } catch { /* ignorar */ }
  }

  return { model, sizeGB, freeGB };
}

/**
 * Valida que haya al menos 200MB libres en el USB.
 * @param {string} driveLetter
 * @returns {Promise<boolean>}
 */
async function hasMinFreeSpace(driveLetter) {
  try {
    const cleanLetter = driveLetter.trim().toUpperCase().replace(':', '');
    const ps = [
      '-NoProfile',
      '-Command',
      `(Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='${cleanLetter}:'").FreeSpace`,
    ];
    const { stdout } = await execFileAsync('powershell.exe', ps, { timeout: 10000 });
    const freeBytes = Number(stdout.trim());
    const MIN_SPACE = 200 * 1024 * 1024; // 200MB
    return !isNaN(freeBytes) && freeBytes >= MIN_SPACE;
  } catch {
    return true; // Si no podemos verificar, asumimos que hay espacio
  }
}

/**
 * Opción B: Preparar el pendrive con vault cifrado AES-256-GCM.
 * Formatea el pendrive (opcional) y crea dot.vault.
 *
 * @param {string} driveLetter - Ej: "D:"
 * @param {string} serial      - Serial de fábrica del pendrive
 * @param {boolean} [format]   - Si true, formatea el pendrive antes (default: false)
 * @returns {Promise<{ ok: boolean, token?: string, recoveryKey?: string, error?: string }>}
 */
async function setupAesVault(driveLetter, serial, format) {
  const dl = driveLetter.trim().toUpperCase();
  const drivePath = dl + '\\';

  try {
    // Validar espacio disponible antes de formatear/copiar
    const hasSpace = await hasMinFreeSpace(dl);
    if (!hasSpace) {
      return {
        ok: false,
        error: `Espacio insuficiente en ${dl}. Se requieren al menos 200MB libres para el instalador DOT.`,
      };
    }

    // Opcional: formatear el pendrive (FAT32 rápido)
    if (format) {
      // Obtener info del USB para el mensaje de confirmación
      const info = await getUsbDriveInfo(dl);
      // Nota: La confirmación real la debe hacer la UI (frontend).
      // Este módulo solo retorna la info; la UI decide si procede.
      // Si se llama con format=true, se asume que la UI ya confirmó.

      if (process.platform === 'win32') {
        try {
          await execFileAsync('format.com', [dl, '/Q', '/FS:FAT32', '/Y', '/V:DOT'], { timeout: 120000 });
        } catch (err) {
          return { ok: false, error: `Error al formatear: ${err.message}` };
        }
      } else {
        // En Linux/Mac el formato sería diferente - omitir por ahora
        // (DOT es solo Windows)
      }
      // Esperar a que el sistema reconozca el formato
      await new Promise((r) => setTimeout(r, 3000));
    }

    // 2. Crear el vault
    const result = await pendriveCrypto.createVault(drivePath, serial);
    if (!result.ok) {
      return { ok: false, error: result.error || 'Error al crear vault cifrado' };
    }

    return { ok: true, token: result.token, recoveryKey: result.recoveryKey };
  } catch (err) {
    return { ok: false, error: err.message || 'Error en setup AES vault' };
  }
}

/**
 * Flujo completo de setup del pendrive.
 * Detecta automáticamente si usar BitLocker o AES vault.
 *
 * @param {string} driveLetter - Letra de unidad (ej: "D:")
 * @param {string} serial      - Serial del pendrive
 * @param {object} [opts]
 * @param {boolean} [opts.format] - Formatear el pendrive (default: true)
 * @returns {Promise<{ ok: boolean, method?: string, token?: string, recoveryPassword?: string, recoveryKeyPath?: string, error?: string }>}
 */
async function setupPendrive(driveLetter, serial, opts) {
  const format = opts?.format !== false; // default true
  const dl = driveLetter.trim().toUpperCase();

  // 1. Verificar que la unidad sea válida y extraíble
  const verifyResult = await verifyRemovableDrive(dl);
  if (!verifyResult.ok) {
    return { ok: false, error: verifyResult.error };
  }

  // 2. Detectar soporte de BitLocker
  const blSupport = await detectBitLockerSupport();

  if (blSupport.available) {
    // Opción A: BitLocker To Go
    try {
      const blResult = await setupBitLocker(dl);
      if (!blResult.ok) {
        // Si BitLocker falla, hacer fallback a AES vault
        return await setupAesVault(dl, serial, format);
      }

      // Después de BitLocker, crear el vault dentro de la unidad protegida
      // (BitLocker cifra todo, pero igual creamos dot.vault para verificación en capa de app)
      // Nota: con BitLocker, el sistema monta automáticamente y permite escritura
      const vaultResult = await pendriveCrypto.createVault(dl + '\\', serial);
      if (!vaultResult.ok) {
        return {
          ok: true,
          method: 'bitlocker',
          recoveryPassword: blResult.recoveryPassword,
          warning: 'BitLocker activado pero no se pudo crear dot.vault secundario',
        };
      }

      return {
        ok: true,
        method: 'bitlocker',
        token: vaultResult.token,
        recoveryPassword: blResult.recoveryPassword,
      };
    } catch (err) {
      // Fallback a AES
      return await setupAesVault(dl, serial, format);
    }
  } else {
    // Opción B: AES-256-GCM vault (funciona en todas las ediciones)
    return await setupAesVault(dl, serial, format);
  }
}

/**
 * Limpia un pendrive: elimina dot.vault y desactiva BitLocker si está activo.
 *
 * @param {string} driveLetter - Ej: "D:"
 * @returns {Promise<{ ok: boolean, error?: string }>}
 */
async function clearPendrive(driveLetter) {
  const dl = driveLetter.trim().toUpperCase();
  const drivePath = dl + '\\';

  try {
    // 1. Eliminar vault si existe
    const vaultPath = path.join(drivePath, pendriveCrypto.VAULT_FILENAME);
    if (fs.existsSync(vaultPath)) {
      fs.unlinkSync(vaultPath);
    }

    // 2. Desactivar BitLocker (si aplica)
    if (process.platform === 'win32') {
      try {
        const { stdout } = await execFileAsync('manage-bde.exe', ['-status', dl], { timeout: 10000 });
        if (stdout.includes('Protección activada') || stdout.includes('Protection On')) {
          await execFileAsync('manage-bde.exe', ['-off', dl], { timeout: 120000 });
          // Esperar a que termine descifrado
          await new Promise((r) => setTimeout(r, 3000));
        }
      } catch {
        // No crítico
      }
    }

    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message || 'Error al limpiar pendrive' };
  }
}

module.exports = {
  setupPendrive,
  clearPendrive,
  setupBitLocker,
  setupAesVault,
  detectBitLockerSupport,
  isBitLockerAvailable,
  verifyRemovableDrive,
  isValidDriveLetter,
  getWindowsEdition,
  getUsbDriveInfo,
  hasMinFreeSpace,
};
