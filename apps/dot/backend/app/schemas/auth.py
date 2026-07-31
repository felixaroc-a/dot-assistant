"""DTOs de autenticacion."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class SuscripcionClienteDto(BaseModel):
    cliente_id: str = Field(description="UUID en clientes_suscripcion.id")
    cedula: str
    plan: str
    fecha_vencimiento: date
    correo: str | None = None


class LoginRequest(BaseModel):
    cedula: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, description="Mapeado a clave_acceso en la BD.")
    hardware_serial: str | None = Field(
        default=None,
        max_length=128,
        description="Serial de fábrica del pendrive; lo lee la app de escritorio en esta PC.",
    )


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    cliente: SuscripcionClienteDto


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(
        default=None,
        description="Opcional: revocar también la familia de refresh.",
    )


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"


class MeResponse(BaseModel):
    uid: str
    cedula: str | None = None
    email: str | None = None
    plan: str | None = None
    fecha_vencimiento: date | None = None
    email_verified: bool | None = None
