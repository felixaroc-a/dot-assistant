import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { access, copyFile, cp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const frontendRoot = path.resolve(__dirname, '..')
const repoRoot = path.resolve(frontendRoot, '..', '..', '..')
const releaseDir = path.join(frontendRoot, 'release')
const backendDir = path.join(frontendRoot, '..', '..', 'backend')
const installerAssetsDir = path.join(frontendRoot, 'scripts', 'installer')
const stagingDir = path.join(frontendRoot, '.installer-staging')
const outputDir = path.join(releaseDir, 'installer')
const installerScriptPath = path.join(repoRoot, 'scripts', 'installer.iss')
const rootEnvExamplePath = path.join(repoRoot, '.env.example')
const dryRun = process.argv.includes('--dry-run')
const keepStaging = process.argv.includes('--keep-staging')

function normalizeForInno(value) {
  return value.replaceAll('\\', '\\\\')
}

async function ensurePathExists(pathValue, label) {
  try {
    await access(pathValue)
  } catch {
    throw new Error(`No se encontró ${label}: ${pathValue}`)
  }
}

async function readAppVersion() {
  const packageJsonPath = path.join(frontendRoot, 'package.json')
  await ensurePathExists(packageJsonPath, 'frontend/package.json')
  const packageJson = JSON.parse(await readFile(packageJsonPath, 'utf8'))
  return String(packageJson.version || '0.0.0').trim() || '0.0.0'
}

async function findPortableExecutable(options = {}) {
  const { allowMissingRelease = false } = options
  try {
    await access(releaseDir)
  } catch {
    if (allowMissingRelease) return null
    throw new Error(`No se encontró frontend/release: ${releaseDir}`)
  }
  const entries = await readdir(releaseDir, { withFileTypes: true })
  const portableCandidates = entries
    .filter((entry) => entry.isFile() && entry.name.toLowerCase().endsWith('.exe'))
    .filter((entry) => entry.name.toLowerCase().includes('portable'))
    .map((entry) => path.join(releaseDir, entry.name))
    .sort()

  if (portableCandidates.length === 0) return null
  return portableCandidates[0]
}

function resolveIsccPath() {
  const envPath = (process.env.ISCC_PATH || '').trim()
  const candidates = [
    envPath,
    'C:\\Program Files (x86)\\Inno Setup 6\\ISCC.exe',
    'C:\\Program Files\\Inno Setup 6\\ISCC.exe',
  ].filter(Boolean)
  return candidates.find((candidate) => existsSync(candidate)) || null
}

async function prepareStaging(portableExecutablePath) {
  await ensurePathExists(backendDir, 'frontend/backend')
  await ensurePathExists(installerAssetsDir, 'frontend/scripts/installer')
  await ensurePathExists(installerScriptPath, 'scripts/installer.iss')
  await ensurePathExists(rootEnvExamplePath, '.env.example')

  await rm(stagingDir, { recursive: true, force: true })
  await mkdir(stagingDir, { recursive: true })

  await cp(backendDir, path.join(stagingDir, 'backend'), { recursive: true })
  await cp(installerAssetsDir, stagingDir, { recursive: true })
  await copyFile(rootEnvExamplePath, path.join(stagingDir, '.env.example'))

  if (!portableExecutablePath) {
    await writeFile(
      path.join(stagingDir, 'NordikDesktop.exe.placeholder.txt'),
      'Portable executable no encontrado. Ejecuta npm run desktop:dist antes de compilar setup.exe.',
      'utf8',
    )
    return
  }

  await copyFile(portableExecutablePath, path.join(stagingDir, 'NordikDesktop.exe'))
}

function compileInstaller(appVersion) {
  const isccPath = resolveIsccPath()
  if (!isccPath) {
    throw new Error(
      'No se encontró ISCC.exe (Inno Setup). Instálalo o define ISCC_PATH para compilar setup.exe.',
    )
  }

  const args = [
    installerScriptPath,
    `/DMyAppVersion=${appVersion}`,
    `/DSourceStaging=${normalizeForInno(stagingDir)}`,
    `/DOutputDir=${normalizeForInno(outputDir)}`,
  ]

  const result = spawnSync(isccPath, args, {
    cwd: repoRoot,
    stdio: 'inherit',
    windowsHide: true,
  })

  if (result.status !== 0) {
    throw new Error(`ISCC finalizó con código ${String(result.status ?? 'desconocido')}.`)
  }
}

async function run() {
  const appVersion = await readAppVersion()
  const portableExecutablePath = await findPortableExecutable({ allowMissingRelease: dryRun })
  await prepareStaging(portableExecutablePath)

  if (dryRun) {
    console.log('[installer] Dry run completado.')
    if (!portableExecutablePath) {
      console.log('[installer] Falta ejecutable portable en release. Genera artefactos con npm run desktop:dist.')
    } else {
      console.log(`[installer] Portable detectado: ${portableExecutablePath}`)
    }
    console.log(`[installer] Staging preparado: ${stagingDir}`)
    console.log(`[installer] Script Inno listo: ${installerScriptPath}`)
    if (!keepStaging) {
      await rm(stagingDir, { recursive: true, force: true })
      console.log('[installer] Staging temporal eliminado (usa --keep-staging para conservarlo).')
    }
    return
  }

  if (!portableExecutablePath) {
    throw new Error('No se encontró ejecutable portable en release. Ejecuta npm run desktop:dist primero.')
  }

  await mkdir(outputDir, { recursive: true })
  compileInstaller(appVersion)
  console.log(`[installer] setup.exe generado en: ${outputDir}`)
}

run().catch((error) => {
  console.error('[installer] Error:', error instanceof Error ? error.message : String(error))
  process.exit(1)
})
