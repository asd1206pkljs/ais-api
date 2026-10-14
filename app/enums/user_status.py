from enum import Enum


class UserStatus(str, Enum):
    """Account lifecycle after email verification.

    pending_approval: verified, waiting for an administrator (or policy) to activate
    active:           may sign in and use the platform
    disabled:         blocked by an administrator; sessions are rejected
    """

    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    DISABLED = "disabled"
