from enum import Enum


class GroupRole(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"
