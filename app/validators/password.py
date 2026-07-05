import re

PASSWORD_MIN_LENGTH = 8
PASSWORD_RULE_MESSAGE = (
    "Password must be at least 8 characters and include a letter, "
    "a digit, and a special character"
)

_LETTER_RE = re.compile(r"[A-Za-z]")
_DIGIT_RE = re.compile(r"\d")
_SPECIAL_RE = re.compile(r"[^A-Za-z0-9]")


def is_strong_password(value: str) -> bool:
    if len(value) < PASSWORD_MIN_LENGTH:
        return False
    if not _LETTER_RE.search(value):
        return False
    if not _DIGIT_RE.search(value):
        return False
    if not _SPECIAL_RE.search(value):
        return False
    return True


def validate_strong_password(value: str) -> str:
    if not is_strong_password(value):
        raise ValueError(PASSWORD_RULE_MESSAGE)
    return value
