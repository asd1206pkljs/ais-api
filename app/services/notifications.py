"""E-mail notifications for the request workflow and account lifecycle.

Every function swallows delivery errors (after logging) because a failed
notification must never undo the state change it announces.
"""
import logging

from app.config import settings
from app.enums import RequestStatus, RequestType
from app.services.email_service import send_plain_email

logger = logging.getLogger(__name__)

_TYPE_LABEL = {
    RequestType.SIGNUP_APPROVAL.value: "sign-up approval",
    RequestType.CREDIT.value: "credit",
}


def _safe_send(to_email: str, subject: str, body: str) -> None:
    try:
        send_plain_email(to_email, subject, body)
    except Exception:  # noqa: BLE001 - notification failures are logged, not raised
        logger.exception("notification to %s failed (%s)", to_email, subject)


def _request_summary(request) -> str:
    payload = request.payload or {}
    label = _TYPE_LABEL.get(request.request_type, request.request_type)
    lines = [f"Request type: {label}", f"Request id:   {request.request_id}"]
    if request.request_type == RequestType.CREDIT.value:
        lines.append(f"Requested:    {payload.get('requested_amount')} credit(s)")
        if payload.get("reason"):
            lines.append(f"Reason:       {payload['reason']}")
    return "\n".join(lines)


def notify_admins_new_request(request, user_email: str, user_name: str) -> None:
    label = _TYPE_LABEL.get(request.request_type, request.request_type)
    _safe_send(
        settings.admin_notify_email,
        f"[ChronoBoost] New {label} request from {user_email}",
        f"{user_name} <{user_email}> submitted a request that needs a decision.\n\n"
        f"{_request_summary(request)}\n\n"
        "Open the admin console to approve or reject it.",
    )


def notify_user_request_received(to_email: str, request) -> None:
    _safe_send(
        to_email,
        "[ChronoBoost] We received your request",
        "Your request has been received and is waiting for review. "
        "You will get another e-mail once it is decided.\n\n"
        f"{_request_summary(request)}",
    )


def notify_user_request_decided(to_email: str, request) -> None:
    approved = request.status in (RequestStatus.APPROVED.value, RequestStatus.AUTO_APPROVED.value)
    verdict = "approved" if approved else "rejected"
    note = f"\n\nNote from the reviewer:\n{request.decision_note}" if request.decision_note else ""
    granted = ""
    if approved and request.request_type == RequestType.CREDIT.value:
        granted = f"\n\nGranted: {(request.payload or {}).get('granted_amount')} credit(s)"
    _safe_send(
        to_email,
        f"[ChronoBoost] Your request was {verdict}",
        f"Your request has been {verdict}.\n\n{_request_summary(request)}{granted}{note}",
    )


def notify_user_account_pending(to_email: str) -> None:
    _safe_send(
        to_email,
        "[ChronoBoost] Your account is awaiting approval",
        "Thanks for verifying your e-mail address. An administrator will review your "
        "sign-up; you will be notified by e-mail as soon as the account is activated.",
    )


def notify_user_account_activated(to_email: str) -> None:
    _safe_send(
        to_email,
        "[ChronoBoost] Your account is active",
        "Your ChronoBoost account has been activated. You can now sign in.\n\n"
        f"{settings.PASSWORD_RESET_URL_BASE.rstrip('/')}/login",
    )


def notify_owner_resource_published(to_email: str, resource_type: str, name: str | None) -> None:
    _safe_send(
        to_email,
        "[ChronoBoost] An administrator made your resource public",
        f"Your {resource_type} '{name or ''}' is now visible to every user of the platform. "
        "Contact support if you did not expect this.",
    )


def notify_user_account_disabled(to_email: str) -> None:
    _safe_send(
        to_email,
        "[ChronoBoost] Your account has been disabled",
        "Your ChronoBoost account has been disabled by an administrator. "
        "Contact support if you believe this is a mistake.",
    )
