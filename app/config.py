from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_MINUTES: int = 60
    RATE_LIMIT_PER_MINUTE: int = 60
    FILE_STORAGE_BASE_PATH: str = "/var/ais/files"
    EQP_MODELS_BASE_PATH: str = "/home/ais/ais-api/simulators"
    TRAIN_RESULTS_BASE_PATH: str = "/home/ais/ais-api/train_results"
    CORS_ALLOWED_ORIGINS: str = "http://localhost:3000"
    DISABLE_RATE_LIMIT: bool = False
    INTERNAL_API_KEY: str = ""
    # Bootstrap admins: comma-separated emails treated as platform admins even
    # before their users.role is set (the migration promotes them). Prefer
    # managing roles through PATCH /admin/users/{id} afterwards.
    ADMIN_EMAILS: str = ""
    # Where admin notifications (new sign-ups, credit requests) go; falls back
    # to CONTACT_INBOX_EMAIL, then EMAIL_FROM.
    ADMIN_NOTIFY_EMAIL: str = ""

    # --- sign-up approval policy ---
    # When true a verified sign-up waits for an administrator unless its email
    # domain is listed in SIGNUP_AUTO_APPROVE_DOMAINS (comma-separated).
    SIGNUP_REQUIRE_APPROVAL: bool = True
    SIGNUP_AUTO_APPROVE_DOMAINS: str = ""

    # --- credit request policy ---
    # Requests for at most this many credits are granted without an admin,
    # provided the user had no auto-approved request within the window.
    # 0 disables automatic approval.
    CREDIT_REQUEST_AUTO_APPROVE_MAX: int = 0
    CREDIT_REQUEST_AUTO_APPROVE_WINDOW_DAYS: int = 30
    # The purchase endpoint has no payment provider behind it: it credits the
    # account immediately. Off by default; set true only for the mock checkout demo.
    CREDIT_PURCHASE_ENABLED: bool = False

    # --- legal consent ---
    TERMS_VERSION: str = "2026-10-01"
    PRIVACY_VERSION: str = "2026-10-01"
    # Registration must carry acceptance of the current versions above.
    CONSENT_REQUIRED: bool = True

    # --- data at rest ---
    # base64 of 32 random bytes (python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())").
    # Every stored config file is encrypted (AES-256-GCM, envelope) under it.
    DATA_ENCRYPTION_KEY: str = ""
    # Comma-separated previous keys still accepted for decryption after a rotation.
    DATA_ENCRYPTION_KEYS_PREVIOUS: str = ""
    ENCRYPT_DATA_AT_REST: bool = True
    # Allow reading legacy plaintext config files (until app.tasks.encrypt_files ran).
    ALLOW_PLAINTEXT_FILES: bool = True

    PASSWORD_RESET_TTL_MINUTES: int = 30
    PASSWORD_RESET_URL_BASE: str = "http://localhost:3000"
    EMAIL_VERIFY_TTL_HOURS: int = 24
    # Frontend base for the verification link; falls back to PASSWORD_RESET_URL_BASE.
    EMAIL_VERIFY_URL_BASE: str = ""

    # Access token is delivered as an HttpOnly cookie; a second, readable
    # marker cookie only tells the UI that a session exists (carries no secret).
    AUTH_COOKIE_NAME: str = "access_token"
    LOGGED_IN_COOKIE_NAME: str = "logged_in"
    COOKIE_SECURE: bool = True  # set false only for plain-http development hosts
    COOKIE_SAMESITE: str = "lax"
    COOKIE_DOMAIN: str = ""  # empty = host-only cookie

    # Per-account lockout after repeated failed logins (in addition to per-IP rate limits).
    LOGIN_MAX_FAILURES: int = 5
    LOGIN_FAILURE_WINDOW_MINUTES: int = 15
    LOGIN_LOCKOUT_MINUTES: int = 15

    # Housekeeping: unverified sign-ups older than this are deleted.
    PENDING_SIGNUP_TTL_HOURS: int = 72
    CLEANUP_INTERVAL_MINUTES: int = 60
    ENABLE_BACKGROUND_CLEANUP: bool = True
    EMAIL_BACKEND: str = "console"  # console | smtp
    EMAIL_FROM: str = "admin@chronoboost.io"
    CONTACT_INBOX_EMAIL: str = ""  # destination for contact-form submissions
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ALLOWED_ORIGINS.split(",")]

    @property
    def admin_emails(self) -> set[str]:
        return {e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()}

    @property
    def email_verify_url_base(self) -> str:
        return self.EMAIL_VERIFY_URL_BASE or self.PASSWORD_RESET_URL_BASE

    @property
    def signup_auto_approve_domains(self) -> set[str]:
        return {
            d.strip().lower().lstrip("@")
            for d in self.SIGNUP_AUTO_APPROVE_DOMAINS.split(",")
            if d.strip()
        }

    @property
    def admin_notify_email(self) -> str:
        return self.ADMIN_NOTIFY_EMAIL or self.CONTACT_INBOX_EMAIL or self.EMAIL_FROM

    @property
    def data_encryption_keys_previous(self) -> list[str]:
        return [k.strip() for k in self.DATA_ENCRYPTION_KEYS_PREVIOUS.split(",") if k.strip()]


settings = Settings()
