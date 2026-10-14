import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import ValidationError
from app.schemas.consent import ConsentInput
from app.services.consent_service import ConsentService

CURRENT = ConsentInput(terms_version="2026-10-01", privacy_version="2026-10-01")


@pytest.fixture
def repo():
    return AsyncMock()


@pytest.fixture
def service(repo):
    return ConsentService(repo)


def test_versions_reflect_settings():
    v = ConsentService.versions()
    assert v.terms_version == "2026-10-01" and v.privacy_version == "2026-10-01" and v.consent_required


def test_validate_registration_requires_current_versions(service):
    assert service.validate_registration(CURRENT) == CURRENT
    with pytest.raises(ValidationError):
        service.validate_registration(None)
    with pytest.raises(ValidationError):
        service.validate_registration(ConsentInput(terms_version="2020-01-01", privacy_version="2026-10-01"))


def test_validate_registration_optional_when_policy_off(service):
    with patch("app.services.consent_service.settings") as settings:
        settings.CONSENT_REQUIRED = False
        settings.TERMS_VERSION = "2026-10-01"
        settings.PRIVACY_VERSION = "2026-10-01"
        assert service.validate_registration(None) is None
        assert service.validate_registration(CURRENT) == CURRENT


@pytest.mark.asyncio
async def test_record_writes_one_row_per_document(service, repo):
    session = AsyncMock()
    uid = uuid.uuid4()
    await service.record(session, uid, CURRENT)
    rows = repo.add_many.call_args[0][1]
    assert {r["document"] for r in rows} == {"terms", "privacy"}
    assert all(r["user_id"] == uid and r["version"] == "2026-10-01" for r in rows)
    repo.add_many.reset_mock()
    await service.record(session, uid, None)
    repo.add_many.assert_not_called()


@pytest.mark.asyncio
async def test_status_and_accept_current(service, repo):
    session = AsyncMock()
    uid = uuid.uuid4()
    repo.latest_for_user.return_value = {"terms": MagicMock(version="2020-01-01")}
    status = await service.status(session, uid)
    assert status.accepted_terms_version == "2020-01-01"
    assert status.accepted_privacy_version is None
    assert status.up_to_date is False

    with pytest.raises(ValidationError):
        await service.accept_current(session, uid, ConsentInput(terms_version="x", privacy_version="y"))
    repo.latest_for_user.return_value = {
        "terms": MagicMock(version="2026-10-01"), "privacy": MagicMock(version="2026-10-01")}
    status = await service.accept_current(session, uid, CURRENT)
    assert status.up_to_date is True
    session.commit.assert_awaited()
