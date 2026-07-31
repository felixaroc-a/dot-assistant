/**
 * PM2 — cluster local/dev para FastAPI DOT (FREE-I05).
 * Ver docs/PM2-LOCAL.md para arranque en Windows/Linux.
 *
 * Workers: uvicorn multi-proceso (2–4). Ajustar con DOT_PM2_WORKERS=2|3|4.
 * No usar en producción GCP (ver scripts/deployment/ecosystem.config.cjs).
 */
const fs = require('fs');
const path = require('path');

const backendRoot = __dirname;
const isWin = process.platform === 'win32';

function resolvePython() {
  const venvBin = isWin ? 'Scripts' : 'bin';
  const venvExe = isWin ? 'python.exe' : 'python';
  const venvPython = path.join(backendRoot, 'venv', venvBin, venvExe);
  if (fs.existsSync(venvPython)) return venvPython;
  return isWin ? 'python' : 'python3';
}

function clampWorkers(raw) {
  const n = parseInt(raw, 10);
  if (Number.isNaN(n)) return 4;
  return Math.min(4, Math.max(2, n));
}

const workers = clampWorkers(process.env.DOT_PM2_WORKERS || '4');
const python = resolvePython();
const logsDir = path.join(backendRoot, 'logs');

if (!fs.existsSync(logsDir)) {
  fs.mkdirSync(logsDir, { recursive: true });
}

module.exports = {
  apps: [
    {
      name: 'dot-api-local',
      cwd: backendRoot,
      script: python,
      args: [
        '-m',
        'uvicorn',
        'app.main:app',
        '--host',
        '127.0.0.1',
        '--port',
        '8000',
        '--workers',
        String(workers),
      ],
      instances: 1,
      exec_mode: 'fork',
      env: {
        DOT_ENV: 'development',
      },
      max_memory_restart: '500M',
      max_restarts: 10,
      restart_delay: 3000,
      error_file: path.join(logsDir, 'dot-api-local-error.log'),
      out_file: path.join(logsDir, 'dot-api-local.log'),
    },
    {
      name: 'dot-worker-local',
      cwd: backendRoot,
      script: python,
      args: ['-m', 'worker.worker_main', '--interval', '3'],
      instances: 1,
      exec_mode: 'fork',
      env: {
        DOT_ENV: 'development',
      },
      max_memory_restart: '300M',
      max_restarts: 10,
      restart_delay: 3000,
      error_file: path.join(logsDir, 'dot-worker-local-error.log'),
      out_file: path.join(logsDir, 'dot-worker-local.log'),
    },
  ],
};
