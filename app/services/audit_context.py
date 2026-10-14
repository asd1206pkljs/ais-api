"""Per-request context (request id, client address, actor) for audit records.

Set by middleware / the auth dependency; read by AuditService so that services
never have to thread request objects through their signatures.
"""
import uuid
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestContext:
    request_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True)
class Actor:
    user_id: uuid.UUID | None
    email: str | None
    actor_type: str  # user | admin | system | anonymous


ANONYMOUS = Actor(user_id=None, email=None, actor_type="anonymous")
SYSTEM = Actor(user_id=None, email=None, actor_type="system")

_request_ctx: ContextVar[RequestContext | None] = ContextVar("audit_request_ctx", default=None)
_actor: ContextVar[Actor | None] = ContextVar("audit_actor", default=None)


def set_request_context(ctx: RequestContext) -> None:
    _request_ctx.set(ctx)


def get_request_context() -> RequestContext:
    return _request_ctx.get() or RequestContext()


def set_actor(actor: Actor | None) -> None:
    _actor.set(actor)


def get_actor() -> Actor:
    return _actor.get() or ANONYMOUS


def reset() -> None:
    _request_ctx.set(None)
    _actor.set(None)
