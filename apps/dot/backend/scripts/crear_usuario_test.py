"""Crear usuario de prueba v12345678 / test123"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import bcrypt, uuid
from app.billing_db import get_engine
from sqlalchemy import text
from datetime import date

e = get_engine()
hashed = bcrypt.hashpw(b"test123", bcrypt.gensalt()).decode()
uid = str(uuid.uuid4())

with e.connect() as conn:
    conn.execute(
        text("""
            INSERT INTO clientes_suscripcion
            (id, nombre, cedula, clave_acceso, correo, telefono, fecha_vencimiento, plan, hardware_token_hash)
            VALUES (:id, :nombre, :cedula, :clave, :correo, :telefono, :vencimiento, :plan, :hardware)
        """),
        {
            "id": uid,
            "nombre": "Usuario Test",
            "cedula": "V-12345678",
            "clave": hashed,
            "correo": "test@dot.local",
            "telefono": "584121234567",
            "vencimiento": date(2030, 12, 31),
            "plan": "mensual",
            "hardware": None,
        },
    )
    conn.commit()
    print(f"[OK] Usuario v12345678/test123 creado (ID: {uid})")
    print("      Plan: mensual, Vence: 2030-12-31")
    print("      Sin pendrive -> login solo con cedula + clave")
