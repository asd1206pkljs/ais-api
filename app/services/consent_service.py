import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import ValidationError
from app.repositories.consent_repository import ConsentRepository
from app.schemas.consent import ConsentInput, ConsentStatus, LegalVersions
from app.services.audit_context import get_request_context

DOC_TERMS = "terms"
DOC_PRIVACY = "privacy"
CONSENT_REQUIRED_MESSAGE = "You must accept the current Terms of Service and Privacy Policy"


class ConsentService:
    def __init__(self, repo: ConsentRepository | None = None):
        self._repo = repo or ConsentRepository()

    @staticmethod
    def versions() -> LegalVersions:
        return LegalVersions(
            terms_version=settings.TERMS_VERSION,
            privacy_version=settings.PRIVACY_VERSION,
            consent_required=settings.CONSENT_REQUIRED,
        )

    @staticmethod
    def _matches_current(consents: ConsentInput | None) -> bool:
        return (
            consents is not None
            and consents.terms_version == settings.TERMS_VERSION
            and consents.privacy_version == settings.PRIVACY_VERSION
        )

    def validate_registration(self, consents: ConsentInput | None) -> ConsentInput | None:
        """Return the consents to store, or raise when the policy requires them."""
        if self._matches_current(consents):
            return consents
        if settings.CONSENT_REQUIRED:
            raise ValidationError(CONSENT_REQUIRED_MESSAGE)
        return None

    async def record(
        self, session: AsyncSession, user_id: uuid.UUID, consents: ConsentInput | None
    ) -> None:
        """Append one row per accepted document. Caller commits."""
        if consents is None:
            return
        ctx = get_request_context()
        base = {"user_id": user_id, "ip_address": ctx.ip_address,
                "user_agent": (ctx.user_agent or None) and ctx.user_agent[:512]}
        await self._repo.add_many(session, [
            {**base, "document": DOC_TERMS, "version": consents.terms_version},
            {**base, "document": DOC_PRIVACY, "version": consents.privacy_version},
        ])

    async def status(self, session: AsyncSession, user_id: uuid.UUID) -> ConsentStatus:
        latest = await self._repo.latest_for_user(session, user_id)
        terms = latest.get(DOC_TERMS)
        privacy = latest.get(DOC_PRIVACY)
        accepted_terms = terms.version if terms else None
        accepted_privacy = privacy.version if privacy else None
        return ConsentStatus(
            terms_version=settings.TERMS_VERSION,
            privacy_version=settings.PRIVACY_VERSION,
            accepted_terms_version=accepted_terms,
            accepted_privacy_version=accepted_privacy,
            up_to_date=(
                accepted_terms == settings.TERMS_VERSION
                and accepted_privacy == settings.PRIVACY_VERSION
            ),
        )

    async def accept_current(
        self, session: AsyncSession, user_id: uuid.UUID, consents: ConsentInput
    ) -> ConsentStatus:
        if not self._matches_current(consents):
            raise ValidationError("Accepted versions do not match the current documents")
        await self.record(session, user_id, consents)
        await session.commit()
        return await self.status(session, user_id)
