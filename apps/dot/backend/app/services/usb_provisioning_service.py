"""Provisión comercial USB vía script Node (Windows, equipo local)."""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = BACKEND_ROOT.parent
PROVISION_SCRIPT = FRONTEND_DIR / "scripts" / "provision-pendrive-delivery.cjs"
PROVISION_MODULE = FRONTEND_DIR / "electron" / "usb-provision-delivery.cjs"


@dataclass(slots=True)
class UsbProvisioningError(Exception):
    message: str
    code: str = "USB_PROVISIONING_ERROR"
    status_code: int = 400
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


def provisioning_runtime_status() -> dict[str, Any]:
    return {
        "script_exists": PROVISION_SCRIPT.is_file(),
        "script_path": str(PROVISION_SCRIPT),
        "module_exists": PROVISION_MODULE.is_file(),
        "module_path": str(PROVISION_MODULE),
        "node_path": shutil.which("node"),
    }


def _ensure_runtime_available() -> None:
    status = provisioning_runtime_status()
    if not status["script_exists"] or not status["module_exists"]:
        raise UsbProvisioningError(
            message=(
                "No se encontró el runtime de provisión USB. "
                "Verifica frontend/scripts/provision-pendrive-delivery.cjs y "
                "frontend/electron/usb-provision-delivery.cjs."
            ),
            code="SCRIPT_NOT_FOUND",
            status_code=500,
            details=status,
        )
    if not status["node_path"]:
        raise UsbProvisioningError(
            message=(
                "Node.js no está instalado o no está en PATH del servidor. "
                "Instala Node 20+ para habilitar la provisión USB."
            ),
            code="NODE_NOT_FOUND",
            status_code=500,
            details=status,
        )


def _parse_json_payload(raw_stdout: str) -> dict[str, Any] | None:
    body = (raw_stdout or "").strip()
    if not body:
        return None
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    for line in reversed(body.splitlines()):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _run_script_json(args: list[str], timeout_seconds: int) -> dict[str, Any]:
    _ensure_runtime_available()
    cmd = ["node", str(PROVISION_SCRIPT), *args]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(FRONTEND_DIR),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise UsbProvisioningError(
            message=(
                "La provisión tardó demasiado. Revisa el USB (espacio, permisos o velocidad) "
                "y vuelve a intentarlo."
            ),
            code="TIMEOUT",
            status_code=504,
            details={"timeout_seconds": timeout_seconds},
        ) from exc
    except OSError as exc:
        raise UsbProvisioningError(
            message=f"No se pudo ejecutar Node.js para provisión USB: {exc}",
            code="PROCESS_EXEC_ERROR",
            status_code=500,
        ) from exc

    payload = _parse_json_payload(proc.stdout)
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        if payload:
            raise UsbProvisioningError(
                message=str(
                    payload.get("message")
                    or payload.get("error")
                    or "Error de provisión USB."
                ),
                code=str(payload.get("code") or "PROVISION_FAILED"),
                status_code=422,
                details={"stderr": stderr, "payload": payload},
            )
        raise UsbProvisioningError(
            message=stderr or "El script de provisión terminó con error no estructurado.",
            code="PROVISION_FAILED",
            status_code=422,
            details={"stderr": stderr},
        )

    if payload is None:
        raise UsbProvisioningError(
            message="El script de provisión no devolvió JSON válido.",
            code="INVALID_JSON_OUTPUT",
            status_code=500,
            details={"stderr": stderr},
        )
    return payload


def list_usb_devices() -> list[dict[str, str | None]]:
    payload = _run_script_json(["--list-json"], timeout_seconds=20)
    devices = payload.get("devices", [])
    if not isinstance(devices, list):
        return []
    normalized: list[dict[str, str | None]] = []
    for item in devices:
        if not isinstance(item, dict):
            continue
        serial = str(item.get("serial") or "").strip()
        drive_letter = str(item.get("driveLetter") or "").strip().upper()
        if not serial or not drive_letter:
            continue
        normalized.append(
            {
                "serial": serial,
                "driveLetter": drive_letter,
                "model": str(item.get("model") or "").strip() or None,
                "interfaceType": str(item.get("interfaceType") or "").strip() or None,
                "source": str(item.get("source") or "").strip() or None,
            }
        )
    return normalized


def run_usb_provisioning(
    *,
    serial: str,
    drive_letter: str | None,
    api_base: str,
    require_registered: bool = True,
    force: bool = False,
    copy_installer: bool = True,
) -> dict[str, Any]:
    args = ["--json", "--serial", serial, "--api-base", api_base]
    if drive_letter:
        args.extend(["--drive", drive_letter])
    if require_registered:
        args.append("--require-registered")
    if force:
        args.append("--force")
    if not copy_installer:
        args.append("--no-installer")

    result = _run_script_json(args, timeout_seconds=180)
    if not result.get("ok"):
        raise UsbProvisioningError(
            message=str(
                result.get("message")
                or result.get("error")
                or "La provisión USB no se completó."
            ),
            code=str(result.get("code") or "PROVISION_FAILED"),
            status_code=422,
            details={"payload": result},
        )
    if not result.get("result") and result.get("serial"):
        result = {
            **result,
            "result": {
                "driveLetter": result.get("drive"),
                "serial": result.get("serial"),
                "installerPath": result.get("installerPath"),
                "recoveryKey": result.get("recoveryKey"),
                "installerCopied": bool(result.get("installerPath")),
            },
        }
    return result
