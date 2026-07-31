/**
 * OpenClaw Remote Execution.
 * Permite ejecutar comandos remotos en la PC del usuario via WhatsApp/Nordik.
 *
 * SEGURIDAD:
 * - Solo comandos en ALLOWED_COMMANDS pueden ejecutarse.
 * - Cada comando requiere autorizacion explicita del usuario (pendiente).
 * - Timeout por defecto para evitar uso excesivo de recursos.
 * - El usuario siempre puede cancelar desde la UI de Electron.
 */
const { execFile } = require('child_process');
const { promisify } = require('util');
const path = require('path');
const os = require('os');

const execAsync = promisify(execFile);

/**
 * Lista de comandos permitidos (allowlist de seguridad).
 * Solo estos comandos pueden ejecutarse remotamente via OpenClaw.
 */
const ALLOWED_COMMANDS = {
  'download-file': {
    label: 'Descargar archivo',
    description: 'Descarga un archivo desde una URL publica a la carpeta Descargas',
    pattern: /^download\s+(https?:\/\/[^\s]+\.[^\s]+(?:\?[^\s]*)?)\s+(.+)$/i,
    async execute(match) {
      const [, url, filename] = match;
      const downloadsDir = path.join(os.homedir(), 'Downloads');
      const dest = path.join(downloadsDir, filename.replace(/[^a-zA-Z0-9._-]/g, '_'));
      const platform = process.platform;

      if (platform === 'win32') {
        // Windows: usar PowerShell
        const { stdout } = await execAsync(
          'powershell.exe',
          [
            '-NoProfile',
            '-Command',
            `Invoke-WebRequest -Uri "${url.replace(/"/g, '\\"')}" -OutFile "${dest.replace(/"/g, '\\"')}" -UseBasicParsing`,
          ],
          { timeout: 300000, maxBuffer: 500 * 1024 * 1024 },
        );
        return { success: true, file: dest, stdout };
      }

      // macOS/Linux (no soportado oficialmente, pero funcional si alguien lo prueba)
      const { stdout } = await execAsync(
        'curl',
        ['-L', '-o', dest, url],
        { timeout: 300000, maxBuffer: 500 * 1024 * 1024 },
      );
      return { success: true, file: dest, stdout };
    },
  },

  'run-script': {
    label: 'Ejecutar script',
    description: 'Ejecuta un script Python o Node.js permitido desde la carpeta de scripts de Nordik',
    pattern: /^run\s+(python|python3|node)\s+(.+)$/i,
    async execute(match) {
      const [, runtime, scriptPath] = match;
      const allowedRuntimes = ['python', 'python3', 'node'];
      if (!allowedRuntimes.includes(runtime.toLowerCase())) {
        throw new Error(`Runtime no permitido: ${runtime}. Permitidos: ${allowedRuntimes.join(', ')}`);
      }

      // Solo permitir scripts en la carpeta nordik-scripts del usuario
      const scriptsDir = path.join(os.homedir(), 'Nordik', 'scripts');
      const resolvedPath = path.resolve(scriptsDir, scriptPath);

      if (!resolvedPath.startsWith(scriptsDir)) {
        throw new Error(`Acceso denegado: el script debe estar dentro de ${scriptsDir}`);
      }

      const { stdout } = await execAsync(runtime, [resolvedPath], {
        timeout: 60000,
        maxBuffer: 10 * 1024 * 1024,
      });
      return { success: true, output: stdout };
    },
  },

  'system-info': {
    label: 'Informacion del sistema',
    description: 'Obtiene informacion basica del sistema (OS, RAM, disco)',
    pattern: /^system-info$/i,
    async execute() {
      const cpus = os.cpus();
      const totalMem = os.totalmem();
      const freeMem = os.freemem();
      const usedMem = totalMem - freeMem;
      return {
        success: true,
        data: {
          platform: os.platform(),
          release: os.release(),
          hostname: os.hostname(),
          arch: os.arch(),
          cpus: cpus.length,
          cpuModel: cpus[0]?.model || 'unknown',
          memory: {
            total: `${(totalMem / 1024 ** 3).toFixed(1)} GB`,
            used: `${(usedMem / 1024 ** 3).toFixed(1)} GB`,
            free: `${(freeMem / 1024 ** 3).toFixed(1)} GB`,
            usagePercent: ((usedMem / totalMem) * 100).toFixed(0),
          },
          uptime: `${Math.floor(os.uptime() / 3600)}h`,
        },
        message: `Sistema: ${os.platform()} ${os.release()} | CPU: ${cpus.length}x ${cpus[0]?.model} | RAM: ${((usedMem / 1024 ** 3)).toFixed(1)}/${((totalMem / 1024 ** 3)).toFixed(1)} GB`,
      };
    },
  },
};

/**
 * Procesa un comando remoto recibido via WhatsApp/OpenClaw.
 *
 * @param {string} text - Texto completo del comando (ej: "download https://... archivo.zip")
 * @returns {Promise<{success: boolean, error?: string, file?: string, output?: string, data?: object}>}
 */
async function processRemoteCommand(text) {
  if (!text || typeof text !== 'string') {
    return { success: false, error: 'Comando vacio.' };
  }

  const trimmed = text.trim();

  for (const [name, cmd] of Object.entries(ALLOWED_COMMANDS)) {
    const match = trimmed.match(cmd.pattern);
    if (match) {
      try {
        const result = await cmd.execute(match);
        return { ...result, success: true };
      } catch (err) {
        return {
          success: false,
          error: `Error ejecutando '${cmd.label}': ${err.message}`,
        };
      }
    }
  }

  // No hubo match con ningun comando conocido
  const available = Object.values(ALLOWED_COMMANDS)
    .map((c) => `  - ${c.label}: ${c.description}`)
    .join('\n');

  return {
    success: false,
    error: `Comando no reconocido.\nComandos disponibles:\n${available}`,
  };
}

module.exports = { processRemoteCommand, ALLOWED_COMMANDS };
