import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.enums import JobStatus
from app.exceptions import AuthorizationError, InsufficientCreditsError, NotFoundError
from app.models.job import Job
from app.models.user import User
from app.schemas.job import JobCreate
from app.services.job_service import JobService


def _make_job(user_id=None, job_id: int = 1) -> Job:
    job = MagicMock(spec=Job)
    job.job_id = job_id
    job.user_id = user_id or uuid.uuid4()
    job.simulator_id = uuid.uuid4()
    job.job_name = "Test Job"
    job.job_status = JobStatus.PENDING
    job.viewers = [str(job.user_id)]
    job.result_path = None
    job.created_at = None
    job.updated_at = None
    return job


def _make_user(user_id=None, credits: int = 5) -> User:
    user = MagicMock(spec=User)
    user.user_id = user_id or uuid.uuid4()
    user.user_credits = credits
    return user


@pytest.fixture
def repo():
    return AsyncMock()


@pytest.fixture
def user_repo():
    return AsyncMock()


@pytest.fixture
def service(repo, user_repo):
    return JobService(repo, user_repo)


@pytest.fixture
def session():
    return AsyncMock()


@pytest.mark.asyncio
async def test_create_job(service, repo, user_repo, session, tmp_path):
    user_id = uuid.uuid4()
    job = _make_job(user_id=user_id)
    user_repo.find_by_id.return_value = _make_user(user_id=user_id, credits=3)
    user_repo.try_deduct_credit.return_value = True
    repo.create.return_value = job

    persisted = _make_job(user_id=user_id, job_id=job.job_id)
    persisted.result_path = str(tmp_path / str(job.job_id))
    repo.update.return_value = persisted

    storage = MagicMock()
    storage.job_result_dir.return_value = persisted.result_path
    service._storage = storage

    result = await service.create(
        session,
        user_id,
        JobCreate(simulator_id=job.simulator_id, job_name="Test"),
    )
    assert result.user_id == user_id
    assert result.simulator_id == job.simulator_id
    assert result.result_path == persisted.result_path
    user_repo.try_deduct_credit.assert_awaited_once_with(session, user_id, 1)
    storage.job_result_dir.assert_called_once_with(job.job_id)
    repo.update.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_job_insufficient_credits(service, repo, user_repo, session):
    user_id = uuid.uuid4()
    user_repo.find_by_id.return_value = _make_user(user_id=user_id, credits=0)
    user_repo.try_deduct_credit.return_value = False
    with pytest.raises(InsufficientCreditsError):
        await service.create(
            session,
            user_id,
            JobCreate(simulator_id=uuid.uuid4(), job_name="Test"),
        )
    repo.create.assert_not_called()


@pytest.mark.asyncio
async def test_create_job_user_not_found(service, repo, user_repo, session):
    user_repo.find_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.create(
            session,
            uuid.uuid4(),
            JobCreate(simulator_id=uuid.uuid4(), job_name="Test"),
        )
    user_repo.try_deduct_credit.assert_not_called()
    repo.create.assert_not_called()


@pytest.mark.asyncio
async def test_get_job_owner(service, repo, session):
    user_id = uuid.uuid4()
    job = _make_job(user_id=user_id, job_id=42)
    repo.find_by_id.return_value = job
    result = await service.get(session, job.job_id, user_id)
    assert result.job_id == job.job_id


@pytest.mark.asyncio
async def test_get_job_unauthorized(service, repo, session):
    job = _make_job(job_id=7)
    repo.find_by_id.return_value = job
    with pytest.raises(AuthorizationError):
        await service.get(session, job.job_id, uuid.uuid4())


@pytest.mark.asyncio
async def test_get_job_not_found(service, repo, session):
    repo.find_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.get(session, 999, uuid.uuid4())


@pytest.mark.asyncio
async def test_delete_job_unauthorized(service, repo, session):
    job = _make_job(job_id=3)
    repo.find_by_id.return_value = job
    with pytest.raises(AuthorizationError):
        await service.delete(session, job.job_id, uuid.uuid4())


@pytest.mark.asyncio
async def test_delete_pending_job_refunds_credit(service, repo, user_repo, session):
    user_id = uuid.uuid4()
    job = _make_job(user_id=user_id, job_id=10)
    job.job_status = JobStatus.PENDING
    repo.find_by_id.return_value = job
    result = await service.delete(session, job.job_id, user_id)
    assert result["refunded"] is True
    assert result["previous_status"] == JobStatus.PENDING.value
    user_repo.refund_credit.assert_awaited_once_with(session, user_id, 1)
    repo.delete.assert_awaited_once_with(session, job.job_id)


@pytest.mark.asyncio
async def test_delete_paused_job_refunds_credit(service, repo, user_repo, session):
    user_id = uuid.uuid4()
    job = _make_job(user_id=user_id, job_id=12)
    job.job_status = JobStatus.PAUSED
    repo.find_by_id.return_value = job
    result = await service.delete(session, job.job_id, user_id)
    assert result["refunded"] is True
    assert result["previous_status"] == JobStatus.PAUSED.value
    user_repo.refund_credit.assert_awaited_once_with(session, user_id, 1)


@pytest.mark.asyncio
async def test_delete_non_pending_job_no_refund(service, repo, user_repo, session):
    user_id = uuid.uuid4()
    job = _make_job(user_id=user_id, job_id=11)
    job.job_status = JobStatus.TRAINING
    repo.find_by_id.return_value = job
    result = await service.delete(session, job.job_id, user_id)
    assert result["refunded"] is False
    assert result["previous_status"] == JobStatus.TRAINING.value
    user_repo.refund_credit.assert_not_called()
    repo.delete.assert_awaited_once_with(session, job.job_id)


@pytest.mark.asyncio
async def test_request_cancel_pending_locks_to_paused(service, repo, user_repo, session):
    user_id = uuid.uuid4()
    job = _make_job(user_id=user_id, job_id=20)
    job.job_status = JobStatus.PENDING
    repo.find_by_id.return_value = job
    repo.try_transition_status.return_value = True
    result = await service.request_cancel(session, job.job_id, user_id)
    assert result == {
        "paused": True,
        "current_status": JobStatus.PAUSED.value,
        "refundable_on_delete": True,
    }
    repo.try_transition_status.assert_awaited_once_with(
        session, job.job_id, JobStatus.PENDING, JobStatus.PAUSED
    )


@pytest.mark.asyncio
async def test_request_cancel_already_training_returns_not_refundable(
    service, repo, user_repo, session
):
    user_id = uuid.uuid4()
    job = _make_job(user_id=user_id, job_id=21)
    job.job_status = JobStatus.TRAINING
    repo.find_by_id.return_value = job
    repo.try_transition_status.return_value = False
    result = await service.request_cancel(session, job.job_id, user_id)
    assert result["paused"] is False
    assert result["refundable_on_delete"] is False


@pytest.mark.asyncio
async def test_resume_paused_job(service, repo, user_repo, session):
    user_id = uuid.uuid4()
    job = _make_job(user_id=user_id, job_id=22)
    job.job_status = JobStatus.PAUSED
    repo.find_by_id.return_value = job
    repo.try_transition_status.return_value = True
    result = await service.resume(session, job.job_id, user_id)
    assert result["resumed"] is True
    assert result["current_status"] == JobStatus.PENDING.value
    repo.try_transition_status.assert_awaited_once_with(
        session, job.job_id, JobStatus.PAUSED, JobStatus.PENDING
    )
