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
    # Comma-separated emails granted admin access (view all equipment/simulators).
    ADMIN_EMAILS: str = ""

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


settings = Settings()
