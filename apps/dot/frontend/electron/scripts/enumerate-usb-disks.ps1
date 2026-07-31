#Requires -Version 5.1
<#
.SYNOPSIS
  Enumera discos USB / removibles con letra de unidad (Windows WMI/CIM).

.DESCRIPTION
  Salida: JSON en stdout (arreglo comprimido o "[]").
  Criterios (alineado con docs/windows-usb-detection.md):
    1) Win32_DiskDrive con InterfaceType=USB o PNPDeviceID conteniendo USB
    2) Win32_LogicalDisk DriveType=2 (removible) asociado a un disco físico

  NO filtrar solo InterfaceType='USB' (Kingston y otros reportan SCSI + USBSTOR).
#>
$ErrorActionPreference = 'SilentlyContinue'

$seen = @{}
$items = [System.Collections.Generic.List[object]]::new()

# Lista de seriales genéricos de fábrica (alineada con usb-serial-policy.cjs)
$script:GenericSerials = @(
  '', 'none', 'null', '00000000', '000000000000',
  '0000000001', '0000000005', 'ffffffff', 'n/a',
  'not available', 'default string', '12345678',
  '1234567890', '0123456789'
)

function Test-IsGenericSerial([string]$Serial) {
  if (-not $Serial) { return $true }
  $lower = $Serial.ToLower().Trim([char]0)
  if ($lower -in $script:GenericSerials) { return $true }
  if ($lower -match '^0+$') { return $true }
  return $false
}

function Get-SerialFromPnp([string]$PnpDeviceId) {
  if (-not $PnpDeviceId) { return '' }
  $parts = $PnpDeviceId.Split('\')
  if ($parts.Count -lt 3) { return '' }
  $tail = ($parts[$parts.Count - 1]).Trim()
  # Eliminar sufijo de instancia del SO (&0, &1, etc.) para obtener serial base estable
  $tail = $tail -replace '&[0-9]+$', ''
  return $tail
}

function Add-DiskCandidate([object]$disk, [string]$source) {
  if ($null -eq $disk) { return }
  $idx = [string]$disk.Index
  if ($seen.ContainsKey($idx)) { return }

  $serial = ('' + $disk.SerialNumber).Trim().Trim([char]0)
  # Si el serial WMI es genérico (Kingston y otros), usar el PNPDeviceID completo
  if (Test-IsGenericSerial $serial) {
    $serial = Get-SerialFromPnp (('' + $disk.PNPDeviceID).Trim())
  }
  if (-not $serial) { return }

  $driveLetter = ''
  $parts = Get-CimAssociatedInstance -InputObject $disk -ResultClassName Win32_DiskPartition
  foreach ($part in $parts) {
    $logs = Get-CimAssociatedInstance -InputObject $part -ResultClassName Win32_LogicalDisk
    foreach ($log in $logs) {
      $id = ('' + $log.DeviceID).Trim().ToUpper()
      if ($id -match '^[A-Z]:$') {
        $driveLetter = $id
        break
      }
    }
    if ($driveLetter) { break }
  }

  $seen[$idx] = $true
  $items.Add([PSCustomObject]@{
    Serial          = $serial
    Drive           = $driveLetter
    Model           = ('' + $disk.Model).Trim()
    InterfaceType   = ('' + $disk.InterfaceType).Trim()
    PNPDeviceID     = ('' + $disk.PNPDeviceID).Trim()
    Source          = $source
    DiskIndex       = $disk.Index
  }) | Out-Null
}

Get-CimInstance Win32_DiskDrive | ForEach-Object {
  $disk = $_
  $iface = ('' + $disk.InterfaceType).Trim().ToUpper()
  $pnp = ('' + $disk.PNPDeviceID).ToUpper()
  if ($iface -eq 'USB' -or $pnp -like '*USB*') {
    Add-DiskCandidate $disk 'usb'
  }
}

Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=2' | ForEach-Object {
  $log = $_
  $parts = Get-CimAssociatedInstance -InputObject $log -ResultClassName Win32_DiskPartition
  foreach ($part in $parts) {
    $disks = Get-CimAssociatedInstance -InputObject $part -ResultClassName Win32_DiskDrive
    foreach ($disk in $disks) {
      Add-DiskCandidate $disk 'removable'
    }
  }
}

if ($items.Count -eq 0) {
  '[]'
} else {
  $items | ConvertTo-Json -Compress
}
