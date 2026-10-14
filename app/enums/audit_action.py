"""Audit-log action names. Keep them stable: operators filter on these strings."""

# auth
LOGIN_SUCCESS = "auth.login.success"
LOGIN_FAILURE = "auth.login.failure"
LOGOUT = "auth.logout"
REGISTER = "auth.register"
EMAIL_VERIFIED = "auth.email_verified"
PASSWORD_RESET_REQUESTED = "auth.password_reset.requested"
PASSWORD_RESET = "auth.password_reset.completed"
PASSWORD_CHANGED = "auth.password.changed"
CONSENT_ACCEPTED = "auth.consent.accepted"

# account
ACCOUNT_UPDATED = "account.updated"
ACCOUNT_DELETED = "account.deleted"
ACCOUNT_ACTIVATED = "account.activated"
ACCOUNT_DISABLED = "account.disabled"
ACCOUNT_ROLE_CHANGED = "account.role_changed"
CREDITS_PURCHASED = "account.credits.purchased"
CREDITS_ADJUSTED = "account.credits.adjusted"

# resources
RESOURCE_CREATED = "resource.created"
RESOURCE_READ = "resource.read"
RESOURCE_UPDATED = "resource.updated"
RESOURCE_DELETED = "resource.deleted"
RESOURCE_COPIED = "resource.copied"
RESOURCE_GENERATED = "resource.generated"
SHARE_GRANTED = "share.granted"
SHARE_REVOKED = "share.revoked"

# groups
GROUP_CREATED = "group.created"
GROUP_UPDATED = "group.updated"
GROUP_DELETED = "group.deleted"
GROUP_MEMBER_ADDED = "group.member.added"
GROUP_MEMBER_UPDATED = "group.member.updated"
GROUP_MEMBER_REMOVED = "group.member.removed"

# requests
REQUEST_SUBMITTED = "request.submitted"
REQUEST_AUTO_APPROVED = "request.auto_approved"
REQUEST_APPROVED = "request.approved"
REQUEST_REJECTED = "request.rejected"

# jobs
JOB_CREATED = "job.created"
JOB_CANCEL_REQUESTED = "job.cancel_requested"
JOB_RESUMED = "job.resumed"
JOB_DELETED = "job.deleted"
JOB_STATUS_CHANGED = "job.status_changed"
