/** Textos visibles al usuario durante la vinculación QR (sin términos internos). */
export const WHATSAPP_LINK_UI = {
  title: 'Vincular WhatsApp',
  desktopOnly: 'La vinculación de WhatsApp solo está disponible en la aplicación de escritorio.',
  preparing: 'Preparando vinculación…',
  generatingQr: 'Generando código QR…',
  generatingSlow: 'Sigue generando el código… Mantén la app abierta.',
  scanHint: 'Escanea el código QR con WhatsApp',
  scanPath: 'WhatsApp → Dispositivos vinculados → Vincular un dispositivo',
  groupSetupHint:
    'Para hablar con DOT desde el celular: crea un grupo de WhatsApp llamado «DOT» (añádete a ti mismo) y escribe @DOT en cada mensaje. No responde en chats privados 1:1.',
  connected: 'WhatsApp conectado correctamente.',
  connectedSetupHint:
    'Siguiente paso: crea el grupo «DOT» (solo tú) y menciona @DOT cuando quieras que responda.',
  qrTimeout: 'No se generó el código QR a tiempo.',
  linkFailed: 'No se pudo completar la vinculación. Intenta de nuevo.',
  retry: 'Reintentar',
  retryConnection: 'Reintentar conexión',
  alreadyScannedCheck: 'Ya escaneé, comprobar',
  checking: 'Comprobando…',
  checkingStatus: 'Comprobando el estado de WhatsApp…',
  scanThenCheck: 'Si ya escaneaste el código, pulsa comprobar para confirmar la conexión.',
  pendingVerification:
    'WhatsApp parece conectado; estamos validando la sesión. Puedes continuar y verificar más tarde.',
  manualCheckTimeout:
    'No se detectó la conexión en 45 segundos. Puedes continuar y verificar luego o reintentar.',
  serverSyncError: 'No se pudo comprobar el estado de WhatsApp en el servidor.',
  serverSaveError: 'No se pudo guardar el progreso de la vinculación.',
  restartError: 'No se pudo reiniciar la vinculación de WhatsApp.',
  qrGenerateFailed: 'No se pudo generar el código QR. Intenta de nuevo.',
  sessionDisconnected: 'La sesión de WhatsApp se desconectó. Reintenta la vinculación.',
  reconnecting: 'Reconectando WhatsApp…',
  rescanQr: 'Vuelve a escanear el código.',
  rescanHint: 'Abre Sesiones y escanea un código QR nuevo.',
} as const

export type WhatsAppQrUiPhase = 'idle' | 'generating' | 'scan' | 'connected' | 'error'

export function resolveWhatsAppQrUiPhase(input: {
  isDesktop: boolean
  linkedOk: boolean
  hasQrImage: boolean
  runState: 'idle' | 'running' | 'ended'
  qrTimeout: boolean
  startError: string | null
  showEndedError: boolean
}): WhatsAppQrUiPhase {
  if (!input.isDesktop) return 'idle'
  if (input.linkedOk) return 'connected'
  if (input.startError || input.qrTimeout || input.showEndedError) return 'error'
  if (input.hasQrImage && input.runState === 'running') return 'scan'
  if (input.runState === 'running' || input.runState === 'idle') return 'generating'
  if (input.runState === 'ended') return 'error'
  return 'idle'
}
