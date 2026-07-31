/**
 * Criptografía AES-256-GCM para el archivo de sello DOT (dot.vault).
 *
 * Convierte el pendrive en una "llave física" real mediante:
 * - PBKDF2-SHA256(serial + pepper) con 600.000 iteraciones (OWASP 2024) para derivar clave AES-256
 * - Compatibilidad con vaults V1 legados (HKDF-SHA256)
 * - Cifrado AES-256-GCM con autenticación (auth tag) para integridad
 * - Fingerprint hardware multi-propiedad para prevenir clonación con dd
 * - Contador de uso dentro del vault cifrado
 * - Magic header DOT_VAULT_V1 / DOT_VAULT_V2 para identificar el formato KDF
 *
 * Formato del archivo dot.vault (V2 - PBKDF2):
 *   [MAGIC_HEADER  (16 bytes)]   "DOT_VAULT_V2\0"
 *   [SALT          (16 bytes)]   salt aleatorio para PBKDF2
 *   [IV            (12 bytes)]   IV para AES-256-GCM
 *   [AUTH_TAG      (16 bytes)]   GCM authentication tag
 *   [ENCRYPTED_DATA (variable)]  Payload cifrado: JSON con { token, created_at, hw_fingerprint, usage_count, kdf }
 *
 * Formato V1 (legado - HKDF):
 *   [MAGIC_HEADER  (16 bytes)]   "DOT_VAULT_V1\0"
 *   [SALT          (16 bytes)]   salt aleatorio para HKDF
 *   [IV            (12 bytes)]   IV para AES-256-GCM
 *   [AUTH_TAG      (16 bytes)]   GCM authentication tag
 *   [ENCRYPTED_DATA (variable)]  Payload cifrado
 */
require('./load-backend-env.cjs');

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');

const execFileAsync = promisify(execFile);
const usbSerialPolicy = require('./usb-serial-policy.cjs');
const usbDetect = require('./windows-usb-detect.cjs');

const VAULT_FILENAME = 'dot.vault';
const MAGIC_HEADER_V1 = Buffer.from('DOT_VAULT_V1');
const MAGIC_HEADER_V2 = Buffer.from('DOT_VAULT_V2');
const KEY_LENGTH = 32;   // AES-256
const SALT_LENGTH = 16;
const IV_LENGTH = 12;    // GCM standard
const AUTH_TAG_LENGTH = 16;

/** Iteraciones PBKDF2 según OWASP 2024 recomendado */
const PBKDF2_ITERATIONS = 600000;
const PBKDF2_DIGEST = 'sha256';

/**
 * Obtiene el pepper desde variable de entorno.
 * NUNCA hardcodeado — debe venir de process.env.HARDWARE_TOKEN_PEPPER.
 * @returns {string}
 */
function getPepper() {
  const pepper = process.env.HARDWARE_TOKEN_PEPPER;
  if (!pepper || typeof pepper !== 'string' || pepper.trim().length === 0) {
    throw new Error(
      'HARDWARE_TOKEN_PEPPER no está definida. ' +
      'Esta variable de entorno es obligatoria para la seguridad del sistema. ' +
      'Configúrala en el .env del backend y asegúrate de que el frontend la cargue.'
    );
  }
  return pepper.trim();
}

/** @param {unknown} raw @returns {string | null} */
function sanitizeSerial(raw) {
  return usbSerialPolicy.sanitizeUsbSerial(raw);
}

/** @param {unknown} pnpDeviceId @returns {string | null} */
function serialFromPnp(pnpDeviceId) {
  return usbSerialPolicy.serialFromPnpDeviceId(pnpDeviceId);
}

const parseWindowsUsbEnumJson = usbDetect.parseWindowsUsbEnumJson;
const queryWindowsUsbDisks = usbDetect.queryWindowsUsbDisks;

/**
 * Deriva una clave AES-256 usando PBKDF2-SHA256 (V2 - recomendado).
 *
 * @param {string} serial - Serial de fábrica del pendrive
 * @param {string} pepper - Secreto compartido pepper (servidor + cliente)
 * @param {Buffer} salt  - Salt aleatorio de 16 bytes
 * @returns {Buffer} Clave AES-256 de 32 bytes
 */
function deriveKeyPBKDF2(serial, pepper, salt) {
  const normalized = serial.trim().toUpperCase();
  const pass = Buffer.from(normalized + '\x00' + pepper, 'utf-8');
  return crypto.pbkdf2Sync(pass, salt, PBKDF2_ITERATIONS, KEY_LENGTH, PBKDF2_DIGEST);
}

/**
 * Deriva una clave AES-256 usando HKDF-SHA256 (V1 - legado, para compatibilidad).
 *
 * @param {string} serial - Serial de fábrica del pendrive
 * @param {string} pepper - Secreto compartido pepper
 * @param {Buffer} salt  - Salt aleatorio de 16 bytes
 * @returns {Buffer} Clave AES-256 de 32 bytes
 */
function deriveKeyHKDF(serial, pepper, salt) {
  const normalized = serial.trim().toUpperCase();
  const ikm = Buffer.from(normalized + '\x00' + pepper, 'utf-8');
  return crypto.hkdfSync('sha256', ikm, salt, 'dot-pendrive-v1', KEY_LENGTH);
}

/**
 * Deriva una clave intentando PBKDF2 primero; si el payload se descifra,
 * es V2. Si falla, reintenta con HKDF (legado V1).
 *
 * @param {Buffer} magicHeader - Magic header leído del vault
 * @param {string} serial
 * @param {string} pepper
 * @param {Buffer} salt
 * @returns {{ key: Buffer, kdf: string }}
 */
function deriveKeyWithFallback(magicHeader, serial, pepper, salt) {
  if (magicHeader.equals(MAGIC_HEADER_V2)) {
    return { key: deriveKeyPBKDF2(serial, pepper, salt), kdf: 'pbkdf2' };
  }
  // V1 o desconocido → HKDF
  return { key: deriveKeyHKDF(serial, pepper, salt), kdf: 'hkdf' };
}

/**
 * Genera un token UUID v4 aleatorio.
 * @returns {string}
 */
function generateToken() {
  return crypto.randomUUID();
}

/**
 * Genera una recovery key de 48 caracteres alfanuméricos.
 * @returns {string}
 */
function generateRecoveryKey() {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  let key = '';
  for (let i = 0; i < 48; i++) {
    key += chars[crypto.randomInt(chars.length)];
  }
  // Formato: 4 grupos de 12 caracteres separados por guión
  return key.slice(0, 12) + '-' + key.slice(12, 24) + '-' +
         key.slice(24, 36) + '-' + key.slice(36, 48);
}

/**
 * Obtiene fingerprint hardware multi-propiedad para prevención de clonación.
 *
 * Lee VID, PID, tamaño, modelo, firmware, interface vía WMI.
 * Si WMI falla, usa solo el serial como fallback.
 *
 * @param {string} serial - Serial del pendrive
 * @returns {Promise<{ fingerprint: string, driveLetter: string | null, firmwareRevision: string, interfaceType: string }>}
 */
async function getHardwareFingerprint(serial) {
  if (process.platform !== 'win32') {
    const fingerprint = crypto.createHash('sha256').update(serial || 'unknown').digest('hex');
    return { fingerprint, driveLetter: null, firmwareRevision: '', interfaceType: '' };
  }

  try {
    const cleanSerial = sanitizeSerial(serial) || String(serial || '').trim();
    const ps = [
      '-NoProfile',
      '-Command',
      `Get-CimInstance Win32_DiskDrive | Where-Object { $_.SerialNumber -eq '${cleanSerial}' } | Select-Object -First 1 Model, Size, FirmwareRevision, InterfaceType, PNPDeviceID | ConvertTo-Json -Compress`,
    ];
    const { stdout } = await execFileAsync('powershell.exe', ps, { timeout: 10000 });
    const trimmed = (stdout || '').trim();
    if (!trimmed) throw new Error('WMI returned empty result');

    const info = JSON.parse(trimmed);

    const pnpId = String(info.PNPDeviceID || '');
    const vidPidMatch = pnpId.match(/VID_([0-9A-Fa-f]+)&PID_([0-9A-Fa-f]+)/i) || [];

    const fingerprintData = [
      serial || '',
      String(info.Size || '0'),
      String(info.Model || ''),
      String(info.FirmwareRevision || ''),
      String(info.InterfaceType || ''),
      vidPidMatch[1] || '',
      vidPidMatch[2] || '',
    ].join('|');

    const fingerprint = crypto.createHash('sha256').update(fingerprintData).digest('hex');
    return {
      fingerprint,
      driveLetter: null,
      firmwareRevision: String(info.FirmwareRevision || ''),
      interfaceType: String(info.InterfaceType || ''),
    };
  } catch (err) {
    // Fallback: usar solo serial como fingerprint
    const fingerprint = crypto.createHash('sha256').update(serial || 'unknown').digest('hex');
    return { fingerprint, driveLetter: null, firmwareRevision: '', interfaceType: '' };
  }
}

/**
 * Encuentra la letra de unidad asociada a un serial de USB en Windows.
 * @param {string} serial
 * @returns {Promise<string | null>}
 */
async function findDriveLetterForSerial(serial) {
  if (process.platform !== 'win32') return null;

  const target = sanitizeSerial(serial) || String(serial || '').trim();
  if (!target) return null;

  const disks = await queryWindowsUsbDisks();
  const match = disks.find((d) => d.serial.toLowerCase() === target.toLowerCase());
  return match?.driveLetter || null;
}

/**
 * Busca recursivamente la letra de unidad de un pendrive por serial.
 * @param {string} serial
 * @returns {Promise<string | null>}
 */
async function getDrivePathForSerial(serial) {
  const driveLetter = await findDriveLetterForSerial(serial);
  if (driveLetter) return driveLetter + '\\';
  return null;
}

/**
 * Verifica si un archivo dot.vault existe en la raíz de la unidad dada.
 * @param {string} drivePath - Ej: "D:\\" o "D:"
 * @returns {boolean}
 */
function vaultExists(drivePath) {
  const vaultPath = path.join(drivePath, VAULT_FILENAME);
  return fs.existsSync(vaultPath);
}

/**
 * Lee el vault de un archivo sin descifrarlo (solo valida formato).
 * @param {string} drivePath
 * @returns {{ ok: boolean, magic: Buffer|null, data: Buffer|null, error?: string }}
 */
function readVaultRaw(drivePath) {
  const vaultPath = path.join(drivePath, VAULT_FILENAME);
  if (!fs.existsSync(vaultPath)) {
    return { ok: false, magic: null, data: null, error: 'VAULT_NOT_FOUND' };
  }
  let data;
  try {
    data = fs.readFileSync(vaultPath);
  } catch {
    return { ok: false, magic: null, data: null, error: 'VAULT_READ_ERROR' };
  }

  const minLen = MAGIC_HEADER_V1.length + SALT_LENGTH + IV_LENGTH + AUTH_TAG_LENGTH + 1;
  if (data.length < minLen) {
    return { ok: false, magic: null, data: null, error: 'VAULT_TOO_SHORT' };
  }

  const magic = data.slice(0, MAGIC_HEADER_V1.length);
  if (!magic.equals(MAGIC_HEADER_V1) && !magic.equals(MAGIC_HEADER_V2)) {
    return { ok: false, magic, data: null, error: 'INVALID_MAGIC' };
  }

  return { ok: true, magic, data };
}

/**
 * Crea el archivo dot.vault en el pendrive con cifrado AES-256-GCM (V2 - PBKDF2).
 *
 * @param {string}  drivePath      - Ruta del pendrive (ej: "D:\\")
 * @param {string}  serial         - Serial de fábrica del pendrive
 * @param {string}  [pepper]       - Pepper (default: env HARDWARE_TOKEN_PEPPER)
 * @param {string}  [token]        - Token UUID v4 (se genera automático si no se provee)
 * @param {string}  [recoveryKey]  - Recovery key de 48 caracteres (se genera automático si no se provee)
 * @returns {{ ok: boolean, token?: string, recoveryKey?: string, error?: string }}
 */
async function createVault(drivePath, serial, pepper, token, recoveryKey) {
  try {
    pepper = pepper || getPepper();
    token = token || generateToken();
    const rk = recoveryKey || generateRecoveryKey();

    // Obtener fingerprint hardware anti-clonación
    const hw = await getHardwareFingerprint(serial);
    const salt = crypto.randomBytes(SALT_LENGTH);
    const iv = crypto.randomBytes(IV_LENGTH);
    const key = deriveKeyPBKDF2(serial, pepper, salt);

    const payload = JSON.stringify({
      token: token,
      kdf: 'pbkdf2',
      created_at: new Date().toISOString(),
      hw_fingerprint: hw.fingerprint,
      firmware_revision: hw.firmwareRevision,
      interface_type: hw.interfaceType,
      usage_count: 0,
    });

    const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
    const encrypted = Buffer.concat([cipher.update(payload, 'utf-8'), cipher.final()]);
    const authTag = cipher.getAuthTag();

    // Formato V2: MAGIC_V2 (16) + SALT (16) + IV (12) + AUTH_TAG (16) + ENCRYPTED_DATA
    const vault = Buffer.concat([
      MAGIC_HEADER_V2,
      salt,
      iv,
      authTag,
      encrypted,
    ]);

    const vaultPath = path.join(drivePath, VAULT_FILENAME);
    const tempPath = vaultPath + '.tmp';
    try {
      fs.writeFileSync(tempPath, vault);
      fs.renameSync(tempPath, vaultPath);
    } catch (writeErr) {
      // Limpiar archivo temporal si algo falló
      try { fs.unlinkSync(tempPath); } catch { /* ignorar */ }
      throw writeErr;
    }

    // Marcar como oculto en Windows
    if (process.platform === 'win32') {
      try {
        await execFileAsync('attrib', ['+H', vaultPath], { timeout: 5000 });
      } catch {
        // No crítico si falla
      }
    }

    return { ok: true, token, recoveryKey: rk };
  } catch (err) {
    // Si quedó un .tmp huérfano por error fuera del bloque anterior, limpiarlo
    try {
      const vaultPath = path.join(drivePath, VAULT_FILENAME);
      const tempPath = vaultPath + '.tmp';
      if (fs.existsSync(tempPath)) fs.unlinkSync(tempPath);
    } catch { /* ignorar */ }
    return { ok: false, error: err.message || 'Error al crear vault' };
  }
}

/**
 * Verifica y descifra el vault dot.vault en el pendrive.
 * Soporta tanto V1 (HKDF legado) como V2 (PBKDF2).
 *
 * @param {string} drivePath  - Ruta del pendrive (ej: "D:\\")
 * @param {string} serial     - Serial de fábrica del pendrive
 * @param {string} [pepper]   - Pepper (default: env HARDWARE_TOKEN_PEPPER)
 * @returns {{ ok: boolean, token?: string, created_at?: string, hw_fingerprint?: string, kdf?: string, usage_count?: number, error?: string }}
 */
function verifyVault(drivePath, serial, pepper) {
  pepper = pepper || getPepper();

  const raw = readVaultRaw(drivePath);
  if (!raw.ok) {
    return { ok: false, error: raw.error };
  }

  let offset = MAGIC_HEADER_V1.length; // same length as V2

  const salt = raw.data.slice(offset, offset + SALT_LENGTH);
  offset += SALT_LENGTH;
  const iv = raw.data.slice(offset, offset + IV_LENGTH);
  offset += IV_LENGTH;
  const authTag = raw.data.slice(offset, offset + AUTH_TAG_LENGTH);
  offset += AUTH_TAG_LENGTH;
  const encrypted = raw.data.slice(offset);

  // Intentar descifrar con el KDF correcto según magic header
  const { key, kdf } = deriveKeyWithFallback(raw.magic, serial, pepper, salt);

  try {
    const decipher = crypto.createDecipheriv('aes-256-gcm', key, iv);
    decipher.setAuthTag(authTag);
    const decrypted = Buffer.concat([decipher.update(encrypted), decipher.final()]);
    const payload = JSON.parse(decrypted.toString('utf-8'));

    // Si el magic era V1 pero el payload dice algo distinto, respetar
    const actualKdf = payload.kdf || kdf;

    return {
      ok: true,
      token: payload.token,
      created_at: payload.created_at,
      hw_fingerprint: payload.hw_fingerprint,
      kdf: actualKdf,
      usage_count: payload.usage_count || 0,
    };
  } catch (e) {
    // Si falló con V2 (PBKDF2), intentar con V1 (HKDF) como fallback
    if (raw.magic.equals(MAGIC_HEADER_V2)) {
      try {
        const fallbackKey = deriveKeyHKDF(serial, pepper, salt);
        const decipher2 = crypto.createDecipheriv('aes-256-gcm', fallbackKey, iv);
        decipher2.setAuthTag(authTag);
        const decrypted2 = Buffer.concat([decipher2.update(encrypted), decipher2.final()]);
        const payload2 = JSON.parse(decrypted2.toString('utf-8'));
        return {
          ok: true,
          token: payload2.token,
          created_at: payload2.created_at,
          hw_fingerprint: payload2.hw_fingerprint,
          kdf: 'hkdf',
          usage_count: payload2.usage_count || 0,
        };
      } catch {
        return { ok: false, error: 'DECRYPT_FAILED' };
      }
    }
    return { ok: false, error: 'DECRYPT_FAILED' };
  }
}

/**
 * Incrementa el contador de uso dentro del vault.
 * Vuelve a cifrar el vault con el mismo KDF original.
 *
 * @param {string} drivePath
 * @param {string} serial
 * @param {string} [pepper]
 * @returns {{ ok: boolean, usage_count?: number, error?: string }}
 */
function incrementVaultUsage(drivePath, serial, pepper) {
  pepper = pepper || getPepper();

  const raw = readVaultRaw(drivePath);
  if (!raw.ok) {
    return { ok: false, error: raw.error || 'VAULT_NOT_FOUND' };
  }

  let offset = MAGIC_HEADER_V1.length;
  const salt = raw.data.slice(offset, offset + SALT_LENGTH);
  offset += SALT_LENGTH;
  const iv = raw.data.slice(offset, offset + IV_LENGTH);
  offset += IV_LENGTH;
  const authTag = raw.data.slice(offset, offset + AUTH_TAG_LENGTH);
  offset += AUTH_TAG_LENGTH;
  const encrypted = raw.data.slice(offset);

  const { key, kdf } = deriveKeyWithFallback(raw.magic, serial, pepper, salt);

  try {
    const decipher = crypto.createDecipheriv('aes-256-gcm', key, iv);
    decipher.setAuthTag(authTag);
    const decrypted = Buffer.concat([decipher.update(encrypted), decipher.final()]);
    const payload = JSON.parse(decrypted.toString('utf-8'));

    // Incrementar contador
    payload.usage_count = (payload.usage_count || 0) + 1;

    // Re-cifrar con los mismos parámetros (nuevo IV para fresh ciphertext)
    const newIv = crypto.randomBytes(IV_LENGTH);
    const newPayload = JSON.stringify(payload);
    const cipher = crypto.createCipheriv('aes-256-gcm', key, newIv);
    const newEncrypted = Buffer.concat([cipher.update(newPayload, 'utf-8'), cipher.final()]);
    const newAuthTag = cipher.getAuthTag();

    const newVault = Buffer.concat([
      raw.magic,
      salt,
      newIv,
      newAuthTag,
      newEncrypted,
    ]);

    const vaultPath = path.join(drivePath, VAULT_FILENAME);
    const tempPath = vaultPath + '.tmp';
    try {
      fs.writeFileSync(tempPath, newVault);
      fs.renameSync(tempPath, vaultPath);
    } catch (writeErr) {
      // Limpiar archivo temporal si algo falló
      try { fs.unlinkSync(tempPath); } catch { /* ignorar */ }
      throw writeErr;
    }

    return { ok: true, usage_count: payload.usage_count };
  } catch {
    // Si quedó un .tmp huérfano, limpiarlo
    try {
      const vaultPath = path.join(drivePath, VAULT_FILENAME);
      const tempPath = vaultPath + '.tmp';
      if (fs.existsSync(tempPath)) fs.unlinkSync(tempPath);
    } catch { /* ignorar */ }
    return { ok: false, error: 'DECRYPT_FAILED' };
  }
}

/**
 * Verifica el vault completo: descifra, valida fingerprint hardware y retorna token.
 *
 * @param {string} drivePath  - Ruta del pendrive (ej: "D:\\")
 * @param {string} serial     - Serial de fábrica del pendrive
 * @param {string} [pepper]   - Pepper (default: env HARDWARE_TOKEN_PEPPER)
 * @returns {Promise<{ ok: boolean, token?: string, error?: string }>}
 */
async function verifyVaultFull(drivePath, serial, pepper) {
  if (!pepper) {
    try { pepper = getPepper(); } catch { return { ok: false, error: 'PEPPER_MISSING' }; }
  }

  const vault = verifyVault(drivePath, serial, pepper);
  if (!vault.ok) return { ok: false, error: vault.error || 'VAULT_INVALID' };

  // Verificar fingerprint hardware anti-clonación
  const hw = await getHardwareFingerprint(serial);
  if (vault.hw_fingerprint && vault.hw_fingerprint !== hw.fingerprint) {
    return { ok: false, error: 'HARDWARE_FINGERPRINT_MISMATCH' };
  }

  return { ok: true, token: vault.token };
}

/**
 * Escanea todas las unidades removibles buscando la primera con vault válido.
 *
 * @param {string} [pepper] - Pepper (default: env HARDWARE_TOKEN_PEPPER)
 * @returns {Promise<{ ok: boolean, serial?: string, drivePath?: string, token?: string, error?: string }>}
 */
async function findValidVault(pepper) {
  if (!pepper) {
    try { pepper = getPepper(); } catch { return { ok: false, error: 'PEPPER_MISSING' }; }
  }

  let devices = [];
  try {
    devices = await listAllUsbDrives();
  } catch {
    return { ok: false, error: 'USB_ENUM_FAILED' };
  }

  for (const device of devices) {
    if (!device.driveLetter || !device.serial) continue;
    const drivePath = device.driveLetter.endsWith('\\')
      ? device.driveLetter
      : device.driveLetter + '\\';

    const result = await verifyVaultFull(drivePath, device.serial, pepper);
    if (result.ok) {
      return {
        ok: true,
        serial: device.serial,
        drivePath,
        token: result.token,
      };
    }
  }

  return { ok: false, error: 'NO_VALID_VAULT' };
}

/**
 * Lista todos los USB conectados con su serial y letra de unidad (si existe).
 * Incluye USB clásico, PNP USB y unidades removibles con disco físico asociado.
 * @returns {Promise<Array<{ serial: string, driveLetter: string, model?: string, interfaceType?: string, source?: string }>>}
 */
const listAllUsbDrives = usbDetect.listAllUsbDrives;

module.exports = {
  VAULT_FILENAME,
  MAGIC_HEADER_V1,
  MAGIC_HEADER_V2,
  deriveKeyPBKDF2,
  deriveKeyHKDF,
  generateToken,
  generateRecoveryKey,
  createVault,
  verifyVault,
  verifyVaultFull,
  findValidVault,
  vaultExists,
  readVaultRaw,
  getDrivePathForSerial,
  findDriveLetterForSerial,
  listAllUsbDrives,
  queryWindowsUsbDisks,
  getHardwareFingerprint,
  incrementVaultUsage,
  getPepper,
  sanitizeSerial,
  serialFromPnp,
  parseWindowsUsbEnumJson,
};
