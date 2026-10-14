from enum import Enum


class SharePrincipalType(str, Enum):
    USER = "user"
    GROUP = "group"
    PUBLIC = "public"


class SharePermission(str, Enum):
    VIEW = "view"
    EDIT = "edit"


# principal_id stored for public shares (keeps the unique index simple).
PUBLIC_PRINCIPAL_ID = "*"
