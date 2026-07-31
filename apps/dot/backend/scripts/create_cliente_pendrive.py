"""Crea o actualiza un cliente de prueba enlazado a un pendrive USB (hardware_token_hash).

Uso:
  # Con serial explícito (recomendado tras leer el pendrive):
  python scripts/create_cliente_pendrive.py --serial "ABC123XYZ"

  # Valores por defecto: cedula=pendrive / password=pendrive123
  python scripts/create_cliente_pendrive.py --serial "ABC123XYZ" --cedula 1000001 --password miClave
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bcrypt
from dot_billing.hardware_token import hash_hardware_token, sanitize_hardware_serial
from sqlalchemy import text

from app.billing_db import get_engine


def main() -> None:
    # ── Guarda de producción ──────────────────────────────────────────
    if os.environ.get("DOT_ENV", "development") == "production":
        print("ERROR: Este script es solo para desarrollo. DOT_ENV=production detectado. No se puede ejecutar en producción.", file=sys.stderr)
        sys.exit(1)
    # ───────────────────────────────────────────────────────────────────

    parser = argparse.ArgumentParser(description="Cliente de prueba con pendrive DOT")
    parser.add_argument("--serial", required=True, help="Serial de fábrica del pendrive USB")
    parser.add_argument("--cedula", default="pendrive", help="Cédula del cliente")
    parser.add_argument("--password", default="pendrive123", help="Contraseña en texto plano")
    parser.add_argument("--nombre", default="Cliente Pendrive Test", help="Nombre visible")
    parser.add_argument("--correo", default="pendrive@dot.app", help="Correo")
    args = parser.parse_args()

    clean = sanitize_hardware_serial(args.serial)
    if not clean:
        print(f"ERROR: serial inválido: {args.serial!r}", file=sys.stderr)
        sys.exit(1)

    token_hash = hash_hardware_token(clean)
    hashed = bcrypt.hashpw(args.password.encode(), bcrypt.gensalt()).decode()

    e = get_engine()
    with e.connect() as conn:
        existing = conn.execute(
            text("SELECT id FROM clientes_suscripcion WHERE cedula = :cedula"),
            {"cedula": args.cedula},
        ).fetchone()

        if existing:
            conn.execute(
                text(
                    """
                    UPDATE clientes_suscripcion
                    SET clave_acceso = :clave,
                        hardware_token_hash = :hash,
                        nombre = :nombre,
                        correo = :correo,
                        fecha_vencimiento = :vencimiento,
                        plan = :plan
                    WHERE cedula = :cedula
                    """
                ),
                {
                    "cedula": args.cedula,
                    "clave": hashed,
                    "hash": token_hash,
                    "nombre": args.nombre,
                    "correo": args.correo,
                    "vencimiento": "2027-12-31",
                    "plan": "anual",
                },
            )
            print(f"Cliente {args.cedula!r} actualizado con pendrive {clean!r}")
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO clientes_suscripcion
                    (id, nombre, cedula, clave_acceso, correo, fecha_vencimiento, plan, hardware_token_hash)
                    VALUES (:id, :nombre, :cedula, :clave, :correo, :vencimiento, :plan, :hash)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "nombre": args.nombre,
                    "cedula": args.cedula,
                    "clave": hashed,
                    "correo": args.correo,
                    "vencimiento": "2027-12-31",
                    "plan": "anual",
                    "hash": token_hash,
                },
            )
            print(f"Cliente {args.cedula!r} creado con pendrive {clean!r}")

        conn.commit()

    print(f"  Cédula:    {args.cedula}")
    print(f"  Contraseña: {args.password}")
    print(f"  Serial USB: {clean}")
    print("OK")


if __name__ == "__main__":
    main()
