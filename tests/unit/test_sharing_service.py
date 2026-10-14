import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.enums import SharePermission, SharePrincipalType
from app.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.schemas.share import ShareCreate
from app.services.sharing_service import ResourceInfo, SharingService, load_resource


def _share(**kw):
    s = MagicMock()
    s.share_id = kw.get("share_id", uuid.uuid4())
    s.resource_type = kw.get("resource_type", "equipment")
    s.resource_id = kw.get("resource_id", "r1")
    s.principal_type = kw.get("principal_type", "user")
    s.principal_id = kw.get("principal_id", str(uuid.uuid4()))
    s.permission = kw.get("permission", "view")
    s.granted_by = None
    s.created_at = MagicMock()
    return s


@pytest.fixture
def share_repo():
    r = AsyncMock()
    r.find_for_resources.return_value = {}
    return r


@pytest.fixture
def group_repo():
    return AsyncMock()


@pytest.fixture
def user_repo():
    u = AsyncMock()
    u.find_many_by_ids.return_value = {}
    return u


@pytest.fixture
def access():
    a = AsyncMock()
    a.is_admin.return_value = False
    a.is_owner = lambda owner, uid: owner == uid
    return a


@pytest.fixture
def audit():
    return AsyncMock()


@pytest.fixture
def service(share_repo, group_repo, user_repo, access, audit):
    return SharingService(share_repo, group_repo, user_repo, access, audit)


@pytest.fixture
def session():
    return AsyncMock()


def _active_user(uid=None):
    u = MagicMock()
    u.user_id = uid or uuid.uuid4()
    u.approved = True
    u.status = "active"
    u.user_email = "target@example.com"
    return u


@pytest.mark.asyncio
async def test_access_lists_split_view_and_edit(service, share_repo, session):
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    share_repo.find_for_resources.return_value = {
        "r1": [_share(principal_id=a, permission="view"), _share(principal_id=b, permission="edit"),
               _share(principal_id="*", principal_type="public", permission="view")],
    }
    lists = await service.access_lists(session, "equipment", ["r1", "r2"])
    assert lists["r1"] == ([a, b, "*"], [b])
    assert lists["r2"] == ([], [])


@pytest.mark.asyncio
async def test_only_owner_or_admin_manages_shares(service, access, session):
    owner, stranger = uuid.uuid4(), uuid.uuid4()
    info = ResourceInfo("equipment", "r1", owner, "E")
    with patch("app.services.sharing_service.load_resource", new=AsyncMock(return_value=info)):
        with pytest.raises(AuthorizationError):
            await service.list_shares(session, "equipment", "r1", stranger)
        access.is_admin.return_value = True
        assert await service.list_shares(session, "equipment", "r1", stranger) == []


@pytest.mark.asyncio
async def test_public_share_requires_admin(service, share_repo, session):
    owner = uuid.uuid4()
    info = ResourceInfo("equipment", "r1", owner, "E")
    with patch("app.services.sharing_service.load_resource", new=AsyncMock(return_value=info)):
        with pytest.raises(AuthorizationError, match="administrator"):
            await service.grant(session, "equipment", "r1", owner,
                                ShareCreate(principal_type=SharePrincipalType.PUBLIC))
    share_repo.grant.assert_not_called()


@pytest.mark.asyncio
async def test_admin_can_make_public(service, share_repo, user_repo, access, audit, session):
    admin = uuid.uuid4()
    access.is_admin.return_value = True
    info = ResourceInfo("equipment", "r1", uuid.uuid4(), "E")
    share_repo.grant.return_value = _share(principal_type="public", principal_id="*")
    user_repo.find_by_id.return_value = MagicMock(user_email="owner@example.com")
    with patch("app.services.sharing_service.load_resource", new=AsyncMock(return_value=info)), \
         patch("app.services.sharing_service.notifications") as n:
        read = await service.grant(session, "equipment", "r1", admin,
                                   ShareCreate(principal_type=SharePrincipalType.PUBLIC))
    n.notify_owner_resource_published.assert_called_once_with("owner@example.com", "equipment", "E")
    assert read.principal_label == "public"
    kwargs = share_repo.grant.call_args.kwargs
    assert kwargs["principal_type"] == "public" and kwargs["principal_id"] == "*"
    audit.record.assert_awaited()


@pytest.mark.asyncio
async def test_admin_cannot_grant_user_or_group_shares_on_others_resources(service, share_repo, access, session):
    admin = uuid.uuid4()
    access.is_admin.return_value = True
    info = ResourceInfo("equipment", "r1", uuid.uuid4(), "E")
    with patch("app.services.sharing_service.load_resource", new=AsyncMock(return_value=info)):
        with pytest.raises(AuthorizationError, match="owner"):
            await service.grant(session, "equipment", "r1", admin,
                                ShareCreate(principal_type=SharePrincipalType.USER, user_id=admin))
        with pytest.raises(AuthorizationError, match="owner"):
            await service.grant(session, "equipment", "r1", admin,
                                ShareCreate(principal_type=SharePrincipalType.GROUP, group_id=uuid.uuid4()))
    share_repo.grant.assert_not_called()


@pytest.mark.asyncio
async def test_user_share_by_email_requires_active_account_and_not_owner(
    service, share_repo, user_repo, session
):
    owner = uuid.uuid4()
    info = ResourceInfo("simulator", "s1", owner, "S")
    with patch("app.services.sharing_service.load_resource", new=AsyncMock(return_value=info)):
        user_repo.find_by_email.return_value = None
        with pytest.raises(ValidationError):
            await service.grant(session, "simulator", "s1", owner,
                                ShareCreate(principal_type=SharePrincipalType.USER, email="x@example.com"))
        pending = _active_user()
        pending.status = "pending_approval"
        user_repo.find_by_email.return_value = pending
        with pytest.raises(ValidationError):
            await service.grant(session, "simulator", "s1", owner,
                                ShareCreate(principal_type=SharePrincipalType.USER, email="x@example.com"))
        user_repo.find_by_email.return_value = _active_user(owner)
        with pytest.raises(ValidationError, match="owner"):
            await service.grant(session, "simulator", "s1", owner,
                                ShareCreate(principal_type=SharePrincipalType.USER, email="x@example.com"))
        target = _active_user()
        user_repo.find_by_email.return_value = target
        share_repo.grant.return_value = _share(principal_id=str(target.user_id), permission="edit")
        user_repo.find_many_by_ids.return_value = {target.user_id: target}
        read = await service.grant(session, "simulator", "s1", owner, ShareCreate(
            principal_type=SharePrincipalType.USER, email="x@example.com", permission=SharePermission.EDIT))
    assert read.principal_label == "target@example.com" and read.permission == SharePermission.EDIT


@pytest.mark.asyncio
async def test_group_share_requires_membership(service, share_repo, group_repo, session):
    owner, gid = uuid.uuid4(), uuid.uuid4()
    info = ResourceInfo("equipment", "r1", owner, "E")
    group = MagicMock(group_id=gid, group_name="Acme")
    with patch("app.services.sharing_service.load_resource", new=AsyncMock(return_value=info)):
        group_repo.find_by_id.return_value = None
        with pytest.raises(NotFoundError):
            await service.grant(session, "equipment", "r1", owner,
                                ShareCreate(principal_type=SharePrincipalType.GROUP, group_id=gid))
        group_repo.find_by_id.return_value = group
        group_repo.find_member.return_value = None
        with pytest.raises(AuthorizationError):
            await service.grant(session, "equipment", "r1", owner,
                                ShareCreate(principal_type=SharePrincipalType.GROUP, group_id=gid))
        group_repo.find_member.return_value = MagicMock()
        share_repo.grant.return_value = _share(principal_type="group", principal_id=str(gid))
        read = await service.grant(session, "equipment", "r1", owner,
                                   ShareCreate(principal_type=SharePrincipalType.GROUP, group_id=gid))
    assert read.principal_label == "Acme"


@pytest.mark.asyncio
async def test_jobs_are_view_only(service, session):
    owner = uuid.uuid4()
    info = ResourceInfo("job", "7", owner, "J")
    with patch("app.services.sharing_service.load_resource", new=AsyncMock(return_value=info)):
        with pytest.raises(ValidationError, match="viewing"):
            await service.grant(session, "job", "7", owner, ShareCreate(
                principal_type=SharePrincipalType.USER, user_id=uuid.uuid4(), permission=SharePermission.EDIT))


@pytest.mark.asyncio
async def test_legacy_grant_and_revoke(service, share_repo, user_repo, session):
    owner, target = uuid.uuid4(), _active_user()
    info = ResourceInfo("equipment", "r1", owner, "E")
    user_repo.find_by_id.return_value = target
    share_repo.grant.return_value = _share(principal_id=str(target.user_id))
    with patch("app.services.sharing_service.load_resource", new=AsyncMock(return_value=info)):
        await service.grant_legacy(session, "equipment", "r1", owner, str(target.user_id), SharePermission.VIEW)
        with pytest.raises(ValidationError):
            await service.grant_legacy(session, "equipment", "r1", owner, "not-a-uuid", SharePermission.VIEW)
        with pytest.raises(AuthorizationError):  # "*" goes through the public rule
            await service.grant_legacy(session, "equipment", "r1", owner, "*", SharePermission.VIEW)
        await service.revoke_legacy(session, "equipment", "r1", owner, str(target.user_id), SharePermission.VIEW)
        share_repo.revoke_principal.assert_awaited_once()
        await service.revoke_legacy(session, "equipment", "r1", owner, str(target.user_id), SharePermission.EDIT)
    # removing an editor downgrades the existing share to view instead of deleting it
    share_repo.set_permission.assert_awaited_once_with(
        session, "equipment", "r1", "user", str(target.user_id), "view")


@pytest.mark.asyncio
async def test_revoke_checks_share_belongs_to_resource(service, share_repo, session):
    owner = uuid.uuid4()
    info = ResourceInfo("equipment", "r1", owner, "E")
    share_repo.find_by_id.return_value = _share(resource_id="other")
    with patch("app.services.sharing_service.load_resource", new=AsyncMock(return_value=info)):
        with pytest.raises(NotFoundError):
            await service.revoke(session, "equipment", "r1", owner, uuid.uuid4())
        share_repo.find_by_id.return_value = _share(resource_id="r1")
        await service.revoke(session, "equipment", "r1", owner, uuid.uuid4())
    share_repo.revoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_overview_and_revoke(service, share_repo, session):
    share_repo.list_all.return_value = [_share(resource_id="r1"), _share(resource_id="gone")]
    share_repo.count_all.return_value = 2
    infos = {"r1": ResourceInfo("equipment", "r1", uuid.uuid4(), "E1")}

    async def fake_load(session, rtype, rid):
        if rid in infos:
            return infos[rid]
        raise NotFoundError(rtype, rid)

    with patch("app.services.sharing_service.load_resource", new=fake_load):
        items, meta = await service.list_all(session, public_only=True, resource_type=None, skip=0, limit=10)
    assert [i.resource_name for i in items] == ["E1", None] and meta.total == 2

    share_repo.find_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.admin_revoke(session, uuid.uuid4())
    share_repo.find_by_id.return_value = _share()
    await service.admin_revoke(session, uuid.uuid4())
    share_repo.revoke.assert_awaited()


@pytest.mark.asyncio
async def test_load_resource_validates_type_and_id(session):
    with pytest.raises(ValidationError):
        await load_resource(session, "bogus", "1")
    with pytest.raises(NotFoundError):
        await load_resource(session, "job", "not-int")
    with pytest.raises(NotFoundError):
        await load_resource(session, "equipment", "not-uuid")
    row = MagicMock(owner_id=uuid.uuid4(), equipment_name="E", save_status="complete")
    with patch("app.repositories.equipment_repository.EquipmentRepository.find_by_id",
               new=AsyncMock(return_value=row)):
        info = await load_resource(session, "equipment", str(uuid.uuid4()))
    assert info.name == "E" and info.owner_id == row.owner_id
    row.save_status = "deleted"
    with patch("app.repositories.equipment_repository.EquipmentRepository.find_by_id",
               new=AsyncMock(return_value=row)):
        with pytest.raises(NotFoundError):
            await load_resource(session, "equipment", str(uuid.uuid4()))
