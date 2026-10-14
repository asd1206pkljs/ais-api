from unittest.mock import MagicMock, patch

import pytest

from app.services import email_service as es


@pytest.fixture
def smtp():
    with patch("app.services.email_service.smtplib.SMTP") as cls:
        inst = MagicMock()
        cls.return_value.__enter__.return_value = inst
        yield cls, inst


def _settings(**over):
    base = dict(EMAIL_BACKEND="smtp", EMAIL_FROM="from@example.com", SMTP_HOST="smtp.example.com",
                SMTP_PORT=587, SMTP_USER="u", SMTP_PASSWORD="p", SMTP_USE_TLS=True,
                PASSWORD_RESET_TTL_MINUTES=30, EMAIL_VERIFY_TTL_HOURS=24, CONTACT_INBOX_EMAIL="")
    base.update(over)
    s = MagicMock()
    for k, v in base.items():
        setattr(s, k, v)
    return s


def test_console_backend_logs_only(caplog, smtp):
    with patch("app.services.email_service.settings", _settings(EMAIL_BACKEND="console")):
        es.send_plain_email("to@example.com", "Subj", "Body")
        es.send_password_reset_email("to@example.com", "https://x/reset")
        es.send_verification_email("to@example.com", "https://x/verify")
        es.send_contact_email(first_name="A", last_name="B", email="a@b.c", company="Co", job_title=None,
                              phone=None, country=None, inquiry_type="demo", message="hi")
    smtp[0].assert_not_called()


def test_smtp_backend_sends_with_tls_and_login(smtp):
    cls, inst = smtp
    with patch("app.services.email_service.settings", _settings()):
        es.send_plain_email("to@example.com", "Subj", "Body")
        es.send_password_reset_email("to@example.com", "https://x/reset?token=t")
        es.send_verification_email("to@example.com", "https://x/verify?token=t")
        es.send_contact_email(first_name="A", last_name="B", email="a@b.c", company="Co", job_title="CTO",
                              phone="123", country="KR", inquiry_type="demo", message="hi")
    cls.assert_called_with("smtp.example.com", 587)
    assert inst.starttls.call_count == 4 and inst.login.call_count == 4
    sent = [c.args[0] for c in inst.send_message.call_args_list]
    assert sent[0]["Subject"] == "Subj" and sent[0]["To"] == "to@example.com"
    assert "Reset your password" in sent[1]["Subject"] and "https://x/reset?token=t" in sent[1].get_content()
    assert "Verify" in sent[2]["Subject"]
    assert sent[3]["Reply-To"] == "a@b.c" and "(Co)" in sent[3]["Subject"] and sent[3]["To"] == "from@example.com"


def test_smtp_without_tls_or_login(smtp):
    _, inst = smtp
    with patch("app.services.email_service.settings", _settings(SMTP_USE_TLS=False, SMTP_USER="")):
        es.send_plain_email("to@example.com", "S", "B")
    inst.starttls.assert_not_called()
    inst.login.assert_not_called()


def test_missing_smtp_host_and_unknown_backend(smtp):
    with patch("app.services.email_service.settings", _settings(SMTP_HOST="")):
        es.send_password_reset_email("to@example.com", "u")  # logs, does not raise
        with pytest.raises(RuntimeError):
            es.send_plain_email("to@example.com", "S", "B")
        with pytest.raises(RuntimeError):
            es.send_verification_email("to@example.com", "u")
        with pytest.raises(RuntimeError):
            es.send_contact_email(first_name="A", last_name="B", email="a@b.c", company="Co", job_title=None,
                                  phone=None, country=None, inquiry_type="x", message="m")
    with patch("app.services.email_service.settings", _settings(EMAIL_BACKEND="carrier-pigeon")):
        es.send_password_reset_email("to@example.com", "u")
        with pytest.raises(RuntimeError):
            es.send_plain_email("to@example.com", "S", "B")
        with pytest.raises(RuntimeError):
            es.send_verification_email("to@example.com", "u")
        with pytest.raises(RuntimeError):
            es.send_contact_email(first_name="A", last_name="B", email="a@b.c", company="Co", job_title=None,
                                  phone=None, country=None, inquiry_type="x", message="m")
    smtp[0].assert_not_called()


def test_notifications_swallow_delivery_errors():
    from app.services import notifications

    req = MagicMock(request_type="credit", request_id="r", payload={"requested_amount": 3, "reason": "r"},
                    status="approved", decision_note="ok")
    with patch("app.services.notifications.send_plain_email", side_effect=RuntimeError("down")) as send:
        notifications.notify_admins_new_request(req, "u@example.com", "U")
        notifications.notify_user_request_received("u@example.com", req)
        notifications.notify_user_request_decided("u@example.com", req)
        notifications.notify_user_account_pending("u@example.com")
        notifications.notify_user_account_activated("u@example.com")
        notifications.notify_user_account_disabled("u@example.com")
    assert send.call_count == 6
    with patch("app.services.notifications.send_plain_email") as send:
        req.status = "rejected"
        notifications.notify_user_request_decided("u@example.com", req)
        assert "rejected" in send.call_args[0][1]
        req.request_type = "signup_approval"
        req.status = "approved"
        notifications.notify_user_request_decided("u@example.com", req)
        assert "Granted" not in send.call_args[0][2]
