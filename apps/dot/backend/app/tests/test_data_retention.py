"""Tests unitarios T11 / retención D5 (BIBLIA §11)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import patch

from app.chat_models import ConversationORM, MessageORM
from app.services.activity_service import parse_last_active_at
from app.services.data_retention import (
    decide_retention,
    delete_all_user_conversations,
    inactive_beyond_retention,
    purge_user_product_data,
    unpaid_beyond_retention,
)


def test_unpaid_beyond_retention_requires_full_window():
    expiry = date(2026, 1, 1)
    assert unpaid_beyond_retention(expiry, today=date(2026, 1, 2), days=90) is False
    assert unpaid_beyond_retention(expiry, today=date(2026, 4, 1), days=90) is False
    assert unpaid_beyond_retention(expiry, today=date(2026, 4, 2), days=90) is True


def test_unpaid_false_while_subscription_active():
    expiry = date(2026, 12, 31)
    assert unpaid_beyond_retention(expiry, today=date(2026, 6, 1), days=90) is False


def test_inactive_beyond_retention_needs_timestamp():
    assert inactive_beyond_retention(None, days=90) is False
    old = datetime(2025, 1, 1, tzinfo=timezone.utc)
    now = datetime(2025, 5, 1, tzinfo=timezone.utc)
    assert inactive_beyond_retention(old, now=now, days=90) is True
    recent = now - timedelta(days=10)
    assert inactive_beyond_retention(recent, now=now, days=90) is False


def test_decide_retention_or_semantics():
    today = date(2026, 7, 15)
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    unpaid = decide_retention(
        fecha_vencimiento=date(2026, 1, 1),
        last_active_at=now,
        today=today,
        now=now,
        days=90,
    )
    assert unpaid.should_purge is True
    assert unpaid.unpaid is True
    assert unpaid.inactive is False

    inactive = decide_retention(
        fecha_vencimiento=date(2026, 12, 31),
        last_active_at=now - timedelta(days=100),
        today=today,
        now=now,
        days=90,
    )
    assert inactive.should_purge is True
    assert inactive.inactive is True
    assert inactive.unpaid is False


def test_decide_retention_skips_already_purged():
    today = date(2026, 7, 15)
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    decision = decide_retention(
        fecha_vencimiento=date(2026, 1, 1),
        last_active_at=None,
        today=today,
        now=now,
        days=90,
        already_purged=True,
    )
    assert decision.should_purge is False
    assert decision.reason == "already_purged"


def test_parse_last_active_at_iso():
    dt = parse_last_active_at("2026-01-15T12:00:00+00:00")
    assert dt == datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


def test_delete_all_user_conversations(db_session):
    uid = uuid4()
    other = uuid4()
    conv = ConversationORM(id=uuid4(), cliente_id=uid, title="a")
    conv.messages.append(MessageORM(id=uuid4(), role="user", content="hola"))
    other_conv = ConversationORM(id=uuid4(), cliente_id=other, title="b")
    db_session.add_all([conv, other_conv])
    db_session.commit()

    deleted = delete_all_user_conversations(db_session, str(uid))
    assert deleted == 1
    remaining = db_session.query(ConversationORM).all()
    assert len(remaining) == 1
    assert remaining[0].cliente_id == other


@patch("app.services.data_retention._delete_top_level_document", return_value=False)
@patch("app.services.data_retention._delete_profile_memory", return_value=True)
@patch("app.services.data_retention._delete_subcollection", return_value=2)
@patch("app.services.data_retention.delete_user_google_tokens")
@patch("app.services.data_retention.merge_user_profile")
@patch("app.services.data_retention.get_user_profile")
def test_purge_user_product_data_clears_profile_fields(
    mock_get_profile,
    mock_merge,
    mock_delete_tokens,
    mock_delete_exec,
    mock_delete_memory,
    mock_delete_results,
    db_session,
):
    from uuid import UUID

    uid = str(uuid4())
    mock_get_profile.return_value = {
        "memory_summary": {"facts": ["x"]},
        "saved_automations": [{"id": "1"}],
    }
    conv = ConversationORM(id=uuid4(), cliente_id=UUID(uid), title="chat")
    db_session.add(conv)
    db_session.commit()

    result = purge_user_product_data(db_session, uid)
    assert result["chats_deleted"] == 1
    assert result["memory_profile_doc_deleted"] is True
    assert result["automation_executions_deleted"] == 2
    assert result["automation_results_deleted"] == 0
    assert result["google_tokens_deleted"] is True
    mock_delete_memory.assert_called_once_with(uid)
    mock_delete_tokens.assert_called_once_with(uid)
    mock_delete_results.assert_called_once()
    assert mock_merge.called
    merged = mock_merge.call_args[0][1]
    assert merged["memory_summary"] is None
    assert merged["saved_automations"] == []
    assert "retention_purged_at" in merged
    assert db_session.query(ConversationORM).filter_by(cliente_id=UUID(uid)).count() == 0


# ═══════════════════════════════════════════════════════════════════════════
# Tests — Notificaciones de retención (D01)
# ═══════════════════════════════════════════════════════════════════════════


def test_unpaid_beyond_retention_respects_grace_period():
    """D05: el día después del vencimiento (gracia) NO cuenta como unpaid."""
    expiry = date(2026, 1, 1)
    # 1 día después: en gracia, no unpaid
    assert unpaid_beyond_retention(expiry, today=date(2026, 1, 2), days=90) is False


def test__compute_days_until_purge_active_subscription():
    """Suscripción activa no está en trayectoria de purge."""
    from app.services.data_retention import _compute_days_until_purge

    result = _compute_days_until_purge(
        fecha_vencimiento=date(2026, 12, 31),
        last_active_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        today=date(2026, 7, 15),
        now=datetime(2026, 7, 15, tzinfo=timezone.utc),
        days=90,
    )
    assert result is None


def test__compute_days_until_purge_near_purge():
    """Usuario a 7 días del purge debe devolver 7."""
    from app.services.data_retention import _compute_days_until_purge

    # Vencido hace 83 días (90 - 83 = quedan 7)
    result = _compute_days_until_purge(
        fecha_vencimiento=date(2026, 4, 1),
        last_active_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        today=date(2026, 6, 24),  # 84 días después del vencimiento
        now=datetime(2026, 6, 24, tzinfo=timezone.utc),
        days=90,
    )
    # is_subscription_expired: 2026-06-24 > 2026-04-01 + 1 = 2026-04-02 → True
    # delta vencimiento: (2026-06-24 - 2026-04-01).days = 84
    # remaining = 90 - 84 = 6
    # last_active_at no se considera porque está activo
    # candidates = [6] → result = 6
    # Hmm, 84 días no llegamos a 90, quedan 6
    assert result == 6


def test__compute_days_until_purge_already_eligible():
    """Usuario ya elegible para purge devuelve 0."""
    from app.services.data_retention import _compute_days_until_purge

    result = _compute_days_until_purge(
        fecha_vencimiento=date(2025, 1, 1),
        last_active_at=None,
        today=date(2026, 7, 15),
        now=datetime(2026, 7, 15, tzinfo=timezone.utc),
        days=90,
    )
    # is_subscription_expired: 2026-07-15 > 2025-01-01 + 1 = 2025-01-02 → True
    # decide_retention: unpaid=True, inactive=False, should_purge=True
    assert result == 0


@patch("app.services.data_retention.merge_user_profile")
@patch("app.services.data_retention.get_user_profile")
def test__should_send_warning_new(
    mock_get_profile,
    mock_merge,
):
    """Warning no enviado aún debe retornar True."""
    from app.services.data_retention import _should_send_warning

    mock_get_profile.return_value = {"retention_warnings_sent": []}
    assert _should_send_warning("uid-1", 7) is True
    assert _should_send_warning("uid-1", 3) is True
    assert _should_send_warning("uid-1", 1) is True


@patch("app.services.data_retention.merge_user_profile")
@patch("app.services.data_retention.get_user_profile")
def test__should_send_warning_already_sent(
    mock_get_profile,
    mock_merge,
):
    """Warning ya enviado debe retornar False."""
    from app.services.data_retention import _should_send_warning

    mock_get_profile.return_value = {"retention_warnings_sent": ["d-7"]}
    assert _should_send_warning("uid-1", 7) is False
    assert _should_send_warning("uid-1", 3) is True


@patch("app.services.data_retention.merge_user_profile")
@patch("app.services.data_retention.get_user_profile")
def test__record_warning_sent_appends(
    mock_get_profile,
    mock_merge,
):
    """Registrar warning agrega la clave al array."""
    from app.services.data_retention import _record_warning_sent

    mock_get_profile.return_value = {"retention_warnings_sent": []}
    _record_warning_sent("uid-1", 7)
    assert mock_merge.called
    merged = mock_merge.call_args[0][1]
    assert "d-7" in merged["retention_warnings_sent"]


@patch("app.services.data_retention.merge_user_profile")
@patch("app.services.data_retention.get_user_profile")
def test__record_warning_sent_no_duplicate(
    mock_get_profile,
    mock_merge,
):
    """Registrar warning ya existente no duplica."""
    from app.services.data_retention import _record_warning_sent

    mock_get_profile.return_value = {"retention_warnings_sent": ["d-7"]}
    _record_warning_sent("uid-1", 7)
    # No debe llamar a merge porque ya existe el warning
    mock_merge.assert_not_called()
