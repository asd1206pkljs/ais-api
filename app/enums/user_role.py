from enum import Enum


class UserRole(str, Enum):
    """Platform-wide role. Group-level roles live in GroupRole."""

    ADMIN = "admin"
    USER = "user"
