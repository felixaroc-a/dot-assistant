"""Modelos SQLAlchemy alineados con infra/billing/schema.sql."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PyEnum
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, deferred, mapped_column
from sqlalchemy.types import CHAR, TypeDecorator


class GUID(TypeDecorator):
    """UUID compatible con Postgres y SQLite (CHAR(36))."""

    impl = CHAR(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PGUUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, UUID):
            return value
        return UUID(str(value))


class PlanSuscripcionORM(str, PyEnum):
    mensual = "mensual"
    trimestral = "trimestral"
    anual = "anual"


class AiProviderORM(str, PyEnum):
    """Proveedor de IA asignado al cliente (alineado con onboarding desktop)."""

    deepseek = "deepseek"
    gemini = "gemini"
    chatgpt = "chatgpt"


class Base(DeclarativeBase):
    pass


class ClienteORM(Base):
    __tablename__ = "clientes_suscripcion"

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True, default=uuid4)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    cedula: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    clave_acceso: Mapped[str] = mapped_column(String(128), nullable=False)
    correo: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    telefono: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    fecha_vencimiento: Mapped[date] = mapped_column(Date(), nullable=False, index=True)
    plan: Mapped[PlanSuscripcionORM] = mapped_column(
        Enum(PlanSuscripcionORM, name="plan_suscripcion", native_enum=False),
        nullable=False,
    )
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    recordatorio_7d_enviado_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notas: Mapped[str | None] = mapped_column(Text(), nullable=True)
    creado_por: Mapped[str | None] = deferred(mapped_column(String(64), nullable=True, index=True))
    hardware_token_hash: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True, index=True
    )
    ai_provider_id: Mapped[AiProviderORM] = mapped_column(
        Enum(AiProviderORM, name="ai_provider_id", native_enum=False),
        nullable=False,
        default=AiProviderORM.deepseek,
        server_default=AiProviderORM.deepseek.value,
    )
    ai_billing_mode: Mapped[PlanSuscripcionORM] = mapped_column(
        Enum(PlanSuscripcionORM, name="ai_billing_mode", native_enum=False),
        nullable=False,
        default=PlanSuscripcionORM.mensual,
        server_default=PlanSuscripcionORM.mensual.value,
    )
    pendrive_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
    )


class UsageTokenORM(Base):
    """Consumo de IA acumulado por cliente (chat, visión, generación de imágenes)."""

    __tablename__ = "usage_tokens"
    __table_args__ = (Index("idx_usage_cliente_mes", "cliente_id", "fecha"),)

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True, default=uuid4)
    cliente_id: Mapped[UUID] = mapped_column(
        GUID(),
        ForeignKey("clientes_suscripcion.id"),
        nullable=False,
        index=True,
    )
    fecha: Mapped[date] = mapped_column(Date(), nullable=False, server_default=func.current_date())
    modelo: Mapped[str] = mapped_column(String(50), nullable=False, default="deepseek-chat")
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tokens_prompt: Mapped[int] = mapped_column(BigInteger(), nullable=False, default=0)
    tokens_completion: Mapped[int] = mapped_column(BigInteger(), nullable=False, default=0)
    tokens_cached: Mapped[int] = mapped_column(BigInteger(), nullable=False, default=0)
    costo_total: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=0)
    operation: Mapped[str] = mapped_column(String(32), nullable=False, default="chat")
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SubscriptionReminderOutboxORM(Base):
    """DEPRECATED - Ledger usado anteriormente por Chatbot-Cobro (recordatorios Meta). Ya no se usa."""

    __tablename__ = "subscription_reminder_outbox"

    dedupe_key: Mapped[str] = mapped_column(String, primary_key=True)
    subscription_id: Mapped[str] = mapped_column(String, nullable=False)
    expiry_window_start_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expiry_window_end_utc_excl: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
