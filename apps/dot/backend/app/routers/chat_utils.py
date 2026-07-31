"""Modelos compartidos para los routers de chat."""
from __future__ import annotations

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, Field


class SendMessageRequest(BaseModel):
    conversation_id: str | None = None
    text: str
    provider: str | None = None
    preferred_model: str | None = None
    reasoning_enabled: bool | None = None
    reasoning_level: Literal["low", "medium", "high", "auto"] | None = None


class ChatMessageResponse(BaseModel):
    id: str
    role: str
    text: str
    createdAt: str
    status: str = "sent"


class SendMessageResponse(BaseModel):
    message: ChatMessageResponse
    conversation_id: str
    history_saved: bool = True
    artifacts: list[dict] = []
    memory_recall: str | None = None


class AgendaEventResponse(BaseModel):
    summary: str
    start: str | None = None
    end: str | None = None
    html_link: str | None = None


class AgendaTodayResponse(BaseModel):
    linked: bool
    events: list[AgendaEventResponse]
    message: str


class ReminderCreateRequest(BaseModel):
    text: str
    due_at: datetime


class ReminderCreateResponse(BaseModel):
    ok: bool
    id: str
    due_at: str
    message: str


class ReminderPendingItem(BaseModel):
    id: str
    text: str
    due_at: str


class ReminderPendingResponse(BaseModel):
    reminders: list[ReminderPendingItem]


class ReminderAckRequest(BaseModel):
    ids: list[str] = []


class TranslateRequest(BaseModel):
    text: str
    target_lang: str
    provider: str | None = None


class TranslateResponse(BaseModel):
    translated_text: str
    provider: str
    target_lang: str


class SummarizeRequest(BaseModel):
    content: str
    provider: str | None = None


class SummarizeResponse(BaseModel):
    summary: str
    source_type: str
    chunks: int


# ─── Multi-chat B01 ───────────────────────────────────────────────


class RenameConversationRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class CreateConversationRequest(BaseModel):
    title: str | None = None
    channel: str | None = None  # 'pc' (default) o 'whatsapp'


class ConversationResponse(BaseModel):
    id: str
    title: str
    provider: str
    channel: str = "pc"
    message_count: int
    created_at: str
    updated_at: str
    archived: bool = False


class PaginatedMessagesResponse(BaseModel):
    conversation_id: str
    messages: list
    total: int
    page: int
    page_size: int
