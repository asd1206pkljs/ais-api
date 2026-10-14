import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.enums import JobStatus
from app.exceptions import AuthorizationError, InsufficientCreditsError, NotFoundError
from app.models.job import Job
from app.schemas.job import JobCreate, JobUpdate
from app.services.job_service import JobService


def _make_job(user_id=None, status=JobStatus.PENDING.value) -> Job:
    job = MagicMock(spec=Job)
    job.job_id = 1
    job.user_id = user_id or uuid.uuid4()
    job.simulator_id = uuid.uuid4()
    job.job_name = "Job"
    job.job_status = status
    job.claimed_by = None
    job.result_path = "/results/1"
    job.created_at = datetime.now(timezone.utc)
    job.updated_at = datetime.now(timezone.utc)
    return job


@pytest.fixture
def repo():
    return AsyncMock()


@pytest.fixture
def user_repo():
    u = AsyncMock()
    u.try_deduct_credit.return_value = True
    return u


@pytest.fixture
def storage():
    s = MagicMock()
    s.job_result_dir.return_value = "/results/1"
    return s


@pytest.fixture
def access():
    a = AsyncMock()
    a.is_admin.return_value = False
    a.is_owner = lambda owner, uid: owner == uid
    a.principals.return_value = ["p"]
    a.can_view.return_value = True
    return a


@pytest.fixture
def sharing():
    s = AsyncMock()
    s.access_lists.return_value = {}
    return s


@pytest.fixture
def simulators():
    s = AsyncMock()
    s.find_by_id.return_value = MagicMock(simulator_id=uuid.uuid4(), owner_id=uuid.uuid4(), save_status="complete")
    return s


@pytest.fixture
def service(repo, user_repo, storage, access, sharing, simulators):
    return JobService(repo, user_repo, storage, access, sharing, AsyncMock(), simulators)


@pytest.fixture
def session():
    return AsyncMock()


@pytest.mark.asyncio
async def test_create_requires_simulator_access_and_credit(service, repo, user_repo, access, session):
    uid = uuid.uuid4()
    user_repo.find_by_id.return_value = MagicMock()
    access.can_view.return_value = False
    with pytest.raises(AuthorizationError):
        await service.create(session, uid, JobCreate(simulator_id=uuid.uuid4(), job_name="J"))
    user_repo.try_deduct_credit.assert_not_called()

    access.can_view.return_value = True
    user_repo.try_deduct_credit.return_value = False
    with pytest.raises(InsufficientCreditsError):
        await service.create(session, uid, JobCreate(simulator_id=uuid.uuid4(), job_name="J"))
    session.rollback.assert_awaited()

    user_repo.try_deduct_credit.return_value = True
    job = _make_job(uid)
    repo.create.return_value = job
    repo.update.return_value = job
    result = await service.create(session, uid, JobCreate(simulator_id=job.simulator_id, job_name="J"))
    assert result.user_id == uid and "viewers" not in repo.create.call_args[0][1]
    repo.update.assert_awaited_once_with(session, 1, {"result_path": "/results/1"})


@pytest.mark.asyncio
async def test_results_are_owner_or_viewer_only(service, repo, access, session):
    job = _make_job()
    repo.find_by_id.return_value = job
    access.can_view.return_value = False
    access.is_admin.return_value = True
    assert (await service.get(session, 1, uuid.uuid4())).job_id == 1  # metadata for the console
    with pytest.raises(AuthorizationError):
        await service.get_result_path(session, 1, uuid.uuid4())
    access.can_view.return_value = True
    assert await service.get_result_path(session, 1, uuid.uuid4()) == "/results/1"
    repo.find_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.get(session, 1, uuid.uuid4())


@pytest.mark.asyncio
async def test_owner_only_operations(service, repo, session):
    job = _make_job()
    repo.find_by_id.return_value = job
    for call in (
        service.update(session, 1, uuid.uuid4(), JobUpdate(job_name="x")),
        service.request_cancel(session, 1, uuid.uuid4()),
        service.resume(session, 1, uuid.uuid4()),
        service.delete(session, 1, uuid.uuid4()),
    ):
        with pytest.raises(AuthorizationError):
            await call


@pytest.mark.asyncio
async def test_cancel_resume_transitions(service, repo, session):
    job = _make_job()
    repo.find_by_id.return_value = job
    repo.try_transition_status.return_value = True
    assert (await service.request_cancel(session, 1, job.user_id))["paused"] is True
    repo.try_transition_status.assert_awaited_with(session, 1, JobStatus.PENDING, JobStatus.PAUSED)
    assert (await service.resume(session, 1, job.user_id))["resumed"] is True
    repo.try_transition_status.return_value = False
    job.job_status = JobStatus.TRAINING.value
    result = await service.request_cancel(session, 1, job.user_id)
    assert result == {"paused": False, "current_status": "training", "refundable_on_delete": False}
    assert (await service.resume(session, 1, job.user_id))["resumed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status,refunded", [
    (JobStatus.PENDING.value, True), (JobStatus.PAUSED.value, True), (JobStatus.TRAINING.value, False),
])
async def test_delete_refund_rules(service, repo, user_repo, sharing, session, status, refunded):
    job = _make_job(status=status)
    repo.find_by_id.return_value = job
    result = await service.delete(session, 1, job.user_id)
    assert result == {"refunded": refunded, "previous_status": status}
    assert user_repo.refund_credit.await_count == int(refunded)
    sharing.delete_for_resource.assert_awaited_once_with(session, "job", 1)


@pytest.mark.asyncio
async def test_list_for_user_and_admin(service, repo, access, session):
    uid = uuid.uuid4()
    repo.find_accessible_by_user.return_value = [_make_job(uid)]
    repo.count_accessible_by_user.return_value = 1
    jobs, meta = await service.list_for_user(session, uid)
    assert len(jobs) == 1 and meta.total == 1 and jobs[0].user_email is None
    access.is_admin.return_value = True
    repo.find_all_newest_with_user.return_value = [(_make_job(), "o@example.com")]
    repo.count.return_value = 1
    jobs, _ = await service.list_for_user(session, uid)
    assert jobs[0].user_email == "o@example.com"


@pytest.mark.asyncio
async def test_internal_claim_and_status(service, repo, session):
    job = _make_job()
    repo.find_by_id.return_value = job
    repo.try_claim.return_value = True
    assert (await service.admin_claim(session, 1, "srv-1")).job_id == 1
    repo.try_claim.return_value = False
    from app.exceptions import ConflictError
    with pytest.raises(ConflictError):
        await service.admin_claim(session, 1, "srv-2")
    repo.update.return_value = job
    from app.schemas.job import JobStatusUpdate
    await service.admin_set_status(session, 1, JobStatusUpdate(job_status=JobStatus.PENDING))
    assert repo.update.call_args[0][2] == {"job_status": "pending", "claimed_by": None}
    admin = await service.admin_get(session, 1) if not repo.find_by_id_with_user.return_value else None
    repo.find_by_id_with_user.return_value = (job, "o@example.com")
    assert (await service.admin_get(session, 1)).result_path == "/results/1"
