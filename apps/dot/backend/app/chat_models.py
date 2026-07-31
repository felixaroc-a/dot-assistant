"""Modelos SQLAlchemy para historial de chat."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.billing_models import Base, GUID

if TYPE_CHECKING:
    pass


class ConversationORM(Base):
    __tablename__ = "chat_conversations"

    id = Column(GUID(), primary_key=True, default=uuid4)
    cliente_id = Column(
        GUID(),
        ForeignKey("clientes_suscripcion.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(String(200), default="Nueva conversación")
    provider = Column(String(50), default="deepseek")
    channel = Column(String(20), default="pc", nullable=False)  # 'pc' o 'whatsapp'
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    message_count = Column(Integer, default=0)
    archived_at = Column(DateTime(timezone=True), nullable=True)  # soft-delete

    messages = relationship(
        "MessageORM",
        back_populates="conversation",
        order_by="MessageORM.created_at",
        cascade="all, delete-orphan",
    )


class MessageORM(Base):
    __tablename__ = "chat_messages"

    id = Column(GUID(), primary_key=True, default=uuid4)
    conversation_id = Column(
        GUID(), ForeignKey("chat_conversations.id"), nullable=False
    )
    role = Column(String(20), nullable=False)  # "user" | "assistant" | "system"
    # Se persiste cifrado (enc:v1:<token>) cuando CHAT_ENCRYPTION_KEY está configurada.
    content = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    tokens = Column(Integer, default=0)

    conversation = relationship("ConversationORM", back_populates="messages")
