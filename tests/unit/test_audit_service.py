import uuid
from datetime import datetime, timezone
from enum import Enum
from unittest.mock import AsyncMock

import pytest

from app.services.audit_context import Actor, RequestContext, get_actor, reset, set_actor, set_request_context
from app.services.audit_service import AuditService, jsonable


class Color(str, Enum):
    RED = "red"


def test_jsonable_flattens_uuid_datetime_enum_and_models():
    uid = uuid.uuid4()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = jsonable({"id": uid, "when": now, "c": Color.RED, "nested": [uid, {"x": (1, 2)}]})
    assert out == {"id": str(uid), "when": now.isoformat(), "c": "red", "nested": [str(uid), {"x": [1, 2]}]}


@pytest.mark.asyncio
async def test_record_uses_context_actor_and_request():
    reset()
    repo = AsyncMock()
    svc = AuditService(repo)
    session = AsyncMock()
    uid = uuid.uuid4()
    set_request_context(RequestContext(request_id="req-1", ip_address="10.0.0.1", user_agent="ua" * 400))
    set_actor(Actor(user_id=uid, email="a@example.com", actor_type="admin"))
    try:
        await svc.record(session, "share.granted", resource_type="equipment", resource_id=uuid.UUID(int=5),
                         target_user_id=uid, details={"permission": "view"})
    finally:
        reset()
    data = repo.add.call_args[0][1]
    assert data["actor_id"] == uid and data["actor_email"] == "a@example.com" and data["actor_type"] == "admin"
    assert data["resource_id"] == str(uuid.UUID(int=5)) and data["request_id"] == "req-1"
    assert data["ip_address"] == "10.0.0.1" and len(data["user_agent"]) == 512
    assert data["details"] == {"permission": "view"} and data["outcome"] == "success"


@pytest.mark.asyncio
async def test_record_defaults_to_anonymous_and_never_raises():
    reset()
    repo = AsyncMock()
    repo.add.side_effect = RuntimeError("db down")
    session = AsyncMock()
    await AuditService(repo).record(session, "auth.login.failure", outcome="failure")
    data = repo.add.call_args[0][1]
    assert data["actor_type"] == "anonymous" and data["actor_id"] is None
    session.rollback.assert_awaited()
    assert get_actor().actor_type == "anonymous"


@pytest.mark.asyncio
async def test_explicit_actor_overrides_context():
    reset()
    repo = AsyncMock()
    session = AsyncMock()
    explicit = Actor(user_id=uuid.uuid4(), email="x@example.com", actor_type="user")
    await AuditService(repo).record(session, "auth.register", actor=explicit)
    assert repo.add.call_args[0][1]["actor_email"] == "x@example.com"
