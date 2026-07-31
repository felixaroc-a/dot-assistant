#!/usr/bin/env python3
"""
Crea un usuario de prueba en la base de datos SQLite local.
Ejecutar: python scripts/seed_test_user.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

# Guarda de producción: no ejecutar fuera de desarrollo
ENVIRONMENT = os.getenv("ENVIRONMENT", os.getenv("DOT_ENV", "development"))
if ENVIRONMENT not in ("development", "testing", "dev"):
    print(f"ERROR: seed_test_user.py solo puede ejecutarse en entornos de desarrollo (ENVIRONMENT={ENVIRONMENT}). Abortando.")
    sys.exit(1)

from datetime import date
from dot_billing import hash_password
from dot_billing.models import ClienteORM, PlanSuscripcionORM
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+pysqlite:///./data/dot_dev.db")
print(f"Conectando a: {DATABASE_URL}")

engine = create_engine(DATABASE_URL)

with Session(engine) as session:
    cedula = "V-12345678"
    password = "test123"
    existing = session.query(ClienteORM).filter_by(cedula=cedula).first()
    if existing:
        print(f"Usuario {cedula} ya existe (id={existing.id})")
    else:
        user = ClienteORM(
            nombre="Usuario de Prueba DOT",
            cedula=cedula,
            clave_acceso=hash_password(password),
            correo="test@dot.local",
            plan=PlanSuscripcionORM.anual,
            fecha_vencimiento=date(2030, 12, 31),
        )
        session.add(user)
        session.commit()
        print(f"Usuario {cedula} creado con contrasena '{password}'")

    # Listar usuarios existentes
    users = session.query(ClienteORM).all()
    print(f"\nTotal usuarios: {len(users)}")
    for u in users:
        print(f"  - {u.cedula} | {u.nombre} | plan={u.plan.value} | vence={u.fecha_vencimiento}")
