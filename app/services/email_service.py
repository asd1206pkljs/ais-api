import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)


def _build_reset_message(to_email: str, reset_url: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "[ChronoBoost] Reset your password"
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = to_email
    msg.set_content(
        "We received a request to reset your ChronoBoost password.\n\n"
        f"To choose a new password, follow this link (expires in "
        f"{settings.PASSWORD_RESET_TTL_MINUTES} minutes):\n\n"
        f"{reset_url}\n\n"
        "If you didn't request this, ignore this email."
    )
    return msg


def send_password_reset_email(to_email: str, reset_url: str) -> None:
    backend = settings.EMAIL_BACKEND.lower()
    if backend == "console":
        logger.info(
            "Password reset email (console backend)\n"
            "  to: %s\n  link: %s",
            to_email,
            reset_url,
        )
        return
    if backend == "smtp":
        if not settings.SMTP_HOST:
            logger.error("EMAIL_BACKEND=smtp but SMTP_HOST is not configured")
            return
        msg = _build_reset_message(to_email, reset_url)
        _send_via_smtp(msg)
        return
    logger.warning("Unknown EMAIL_BACKEND: %s — email not sent", backend)


def send_plain_email(to_email: str, subject: str, body: str) -> None:
    """Deliver a plain-text message through the configured backend.

    Raises RuntimeError when no working backend is configured.
    """
    backend = settings.EMAIL_BACKEND.lower()
    if backend == "console":
        logger.info("Email (console backend)\n  to: %s\n  subject: %s\n%s", to_email, subject, body)
        return
    if backend == "smtp":
        if not settings.SMTP_HOST:
            logger.error("EMAIL_BACKEND=smtp but SMTP_HOST is not configured")
            raise RuntimeError("Email backend is not configured")
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.EMAIL_FROM
        msg["To"] = to_email
        msg.set_content(body)
        _send_via_smtp(msg)
        return
    logger.warning("Unknown EMAIL_BACKEND: %s — email not sent", backend)
    raise RuntimeError("Email backend is not configured")


def _send_via_smtp(msg: EmailMessage) -> None:
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls()
        if settings.SMTP_USER:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.send_message(msg)


def _build_verification_message(to_email: str, verify_url: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "[ChronoBoost] Verify your email address"
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = to_email
    msg.set_content(
        "Thanks for signing up for ChronoBoost.\n\n"
        "To activate your account, confirm your email address by following this "
        f"link (expires in {settings.EMAIL_VERIFY_TTL_HOURS} hours):\n\n"
        f"{verify_url}\n\n"
        "If you didn't create an account, you can ignore this email."
    )
    return msg


def send_verification_email(to_email: str, verify_url: str) -> None:
    """Send the sign-up verification link.

    Raises RuntimeError when no working backend is configured, so that
    registration fails loudly instead of leaving an account nobody can verify.
    """
    backend = settings.EMAIL_BACKEND.lower()
    if backend == "console":
        logger.info(
            "Verification email (console backend)\n  to: %s\n  link: %s",
            to_email,
            verify_url,
        )
        return
    if backend == "smtp":
        if not settings.SMTP_HOST:
            logger.error("EMAIL_BACKEND=smtp but SMTP_HOST is not configured")
            raise RuntimeError("Email backend is not configured")
        _send_via_smtp(_build_verification_message(to_email, verify_url))
        return
    logger.warning("Unknown EMAIL_BACKEND: %s — verification email not sent", backend)
    raise RuntimeError("Email backend is not configured")


def _build_contact_message(
    *,
    to_email: str,
    first_name: str,
    last_name: str,
    email: str,
    company: str,
    job_title: str | None,
    phone: str | None,
    country: str | None,
    inquiry_type: str,
    message: str,
) -> EmailMessage:
    full_name = f"{first_name} {last_name}".strip()
    subject = f"[ChronoBoost Contact] {inquiry_type} — {full_name}"
    if company:
        subject += f" ({company})"

    lines = [
        f"Name:        {full_name}",
        f"Company:     {company}",
    ]
    if job_title:
        lines.append(f"Job title:   {job_title}")
    lines.append(f"Email:       {email}")
    if phone:
        lines.append(f"Phone:       {phone}")
    if country:
        lines.append(f"Country:     {country}")
    lines.extend([
        f"Inquiry:     {inquiry_type}",
        "",
        "Message:",
        message,
    ])

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = to_email
    msg["Reply-To"] = email
    msg.set_content("\n".join(lines))
    return msg


def send_contact_email(
    *,
    first_name: str,
    last_name: str,
    email: str,
    company: str,
    job_title: str | None,
    phone: str | None,
    country: str | None,
    inquiry_type: str,
    message: str,
) -> None:
    to_email = settings.CONTACT_INBOX_EMAIL or settings.EMAIL_FROM
    msg = _build_contact_message(
        to_email=to_email,
        first_name=first_name,
        last_name=last_name,
        email=email,
        company=company,
        job_title=job_title,
        phone=phone,
        country=country,
        inquiry_type=inquiry_type,
        message=message,
    )

    backend = settings.EMAIL_BACKEND.lower()
    if backend == "console":
        logger.info(
            "Contact email (console backend)\n  to: %s\n  subject: %s\n  body:\n%s",
            to_email,
            msg["Subject"],
            msg.get_content(),
        )
        return
    if backend == "smtp":
        if not settings.SMTP_HOST:
            logger.error("EMAIL_BACKEND=smtp but SMTP_HOST is not configured")
            raise RuntimeError("Email backend is not configured")
        _send_via_smtp(msg)
        return
    logger.warning("Unknown EMAIL_BACKEND: %s — contact email not sent", backend)
    raise RuntimeError("Email backend is not configured")
