import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import settings
from app.exceptions import AuthenticationError


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# Compared against when no account matches the submitted email, so a wrong
# email costs the same bcrypt work as a wrong password and response time does
# not reveal which emails are registered. Random per process; never matches.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


def create_access_token(user_id: uuid.UUID, email: str, token_version: int) -> str:
    """Issue a JWT carrying a unique `jti` (for revocation) and the user's
    current `ver` (so a password change invalidates every earlier token)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRY_MINUTES)
    payload = {
        "sub": str(user_id),
        "email": email,
        "ver": token_version,
        "jti": uuid.uuid4().hex,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as e:
        raise AuthenticationError(f"Token validation failed: {e}") from e
    # Tokens issued before revocation support lack jti/ver and are rejected.
    if any(payload.get(k) is None for k in ("sub", "jti", "ver", "exp")):
        raise AuthenticationError("Invalid token payload")
    return payload
