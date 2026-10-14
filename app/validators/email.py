from typing import Annotated

from pydantic import BeforeValidator, EmailStr


def normalize_email(value: str) -> str:
    """Normalize an email for case-insensitive storage and lookup.

    Trims surrounding whitespace and lowercases the whole address so that
    ``User@X.com`` and ``user@x.com`` resolve to the same account. Runs before
    ``EmailStr`` format validation, so a cleaned value is what gets validated
    and stored.
    """
    if isinstance(value, str):
        return value.strip().lower()
    return value


# EmailStr field that is trimmed and lowercased on the way in.
NormalizedEmail = Annotated[EmailStr, BeforeValidator(normalize_email)]
