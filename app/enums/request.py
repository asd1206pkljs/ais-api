from enum import Enum


class RequestType(str, Enum):
    SIGNUP_APPROVAL = "signup_approval"
    CREDIT = "credit"


class RequestStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"
