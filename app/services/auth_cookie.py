from fastapi import Response

from app.config import settings


def _cookie_kwargs() -> dict:
    return {
        "path": "/",
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE,
        "domain": settings.COOKIE_DOMAIN or None,
    }


def set_auth_cookies(response: Response, token: str) -> None:
    """Attach the session to the browser.

    The access token goes in an HttpOnly cookie so page scripts (and any XSS)
    cannot read it. A second, readable marker cookie lets the UI know a session
    exists without exposing the token; it carries no secret.
    """
    max_age = settings.JWT_EXPIRY_MINUTES * 60
    response.set_cookie(
        settings.AUTH_COOKIE_NAME, token, max_age=max_age, httponly=True, **_cookie_kwargs()
    )
    response.set_cookie(
        settings.LOGGED_IN_COOKIE_NAME, "1", max_age=max_age, httponly=False, **_cookie_kwargs()
    )


def clear_auth_cookies(response: Response) -> None:
    kwargs = _cookie_kwargs()
    response.delete_cookie(settings.AUTH_COOKIE_NAME, httponly=True, **kwargs)
    response.delete_cookie(settings.LOGGED_IN_COOKIE_NAME, httponly=False, **kwargs)
