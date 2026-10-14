import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.enums import GroupRole
from app.exceptions import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.schemas.group import GroupCreate, GroupMemberAdd, GroupUpdate
from app.services.group_service import GroupService


def _group(gid=None, name="Acme"):
    g = MagicMock()
    g.group_id = gid or uuid.uuid4()
    g.group_name = name
    g.description = None
    g.created_at = MagicMock()
    return g


def _member(role="member", uid=None):
    m = MagicMock()
    m.role = role
    m.user_id = uid or uuid.uuid4()
    m.added_at = MagicMock()
    return m


def _user(uid=None, status="active"):
    u = MagicMock()
    u.user_id = uid or uuid.uuid4()
    u.user_email = "m@example.com"
    u.user_name = "M"
    u.status = status
    return u


@pytest.fixture
def repo():
    r = AsyncMock()
    r.member_counts.return_value = {}
    r.list_members.return_value = []
    return r


@pytest.fixture
def users():
    return AsyncMock()


@pytest.fixture
def shares():
    return AsyncMock()


@pytest.fixture
def access():
    a = AsyncMock()
    a.is_admin.return_value = False
    return a


@pytest.fixture
def service(repo, users, shares, access):
    return GroupService(repo, users, shares, access, AsyncMock())


@pytest.fixture
def session():
    return AsyncMock()


@pytest.mark.asyncio
async def test_create_makes_creator_group_admin(service, repo, session):
    uid = uuid.uuid4()
    repo.create.return_value = _group()
    read = await service.create(session, uid, GroupCreate(group_name="Acme"))
    repo.add_member.assert_awaited_once_with(session, repo.create.return_value.group_id, uid, "admin", uid)
    assert read.my_role == GroupRole.ADMIN


@pytest.mark.asyncio
async def test_get_requires_membership_unless_admin(service, repo, access, session):
    gid, uid = uuid.uuid4(), uuid.uuid4()
    repo.find_by_id.return_value = _group(gid)
    repo.find_member.return_value = None
    with pytest.raises(AuthorizationError):
        await service.get(session, gid, uid)
    access.is_admin.return_value = True
    detail = await service.get(session, gid, uid)
    assert detail.members == [] and detail.my_role is None
    repo.find_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.get(session, gid, uid)


@pytest.mark.asyncio
async def test_update_and_delete_need_group_admin(service, repo, shares, session):
    gid, uid = uuid.uuid4(), uuid.uuid4()
    repo.find_by_id.return_value = _group(gid)
    repo.find_member.return_value = _member("member")
    with pytest.raises(AuthorizationError):
        await service.update(session, gid, uid, GroupUpdate(group_name="New"))
    repo.find_member.return_value = _member("admin")
    repo.update.return_value = _group(gid, "New")
    assert (await service.update(session, gid, uid, GroupUpdate(group_name="New"))).group_name == "New"
    await service.delete(session, gid, uid)
    shares.delete_for_principal.assert_awaited_once_with(session, "group", str(gid))
    repo.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_member_rules(service, repo, users, session):
    gid, admin = uuid.uuid4(), uuid.uuid4()
    repo.find_by_id.return_value = _group(gid)
    repo.find_member.side_effect = [_member("admin")]  # caller lookup
    users.find_by_email.return_value = None
    with pytest.raises(ValidationError):
        await service.add_member(session, gid, admin, GroupMemberAdd(email="x@example.com"))

    repo.find_member.side_effect = [_member("admin")]
    users.find_by_email.return_value = _user(status="pending_approval")
    with pytest.raises(ValidationError):
        await service.add_member(session, gid, admin, GroupMemberAdd(email="x@example.com"))

    target = _user()
    users.find_by_email.return_value = target
    repo.find_member.side_effect = [_member("admin"), _member("member", target.user_id)]
    with pytest.raises(ConflictError):
        await service.add_member(session, gid, admin, GroupMemberAdd(email="x@example.com"))

    repo.find_member.side_effect = [_member("admin"), None, _member("admin")]
    repo.list_members.return_value = [(_member("member", target.user_id), target)]
    detail = await service.add_member(session, gid, admin, GroupMemberAdd(email="x@example.com"))
    repo.add_member.assert_awaited_once_with(session, gid, target.user_id, "member", admin)
    assert detail.members[0].user_email == "m@example.com"


@pytest.mark.asyncio
async def test_last_admin_cannot_be_demoted_or_removed(service, repo, session):
    gid, admin = uuid.uuid4(), uuid.uuid4()
    repo.find_by_id.return_value = _group(gid)
    repo.find_member.return_value = _member("admin", admin)
    repo.count_admins.return_value = 1
    with pytest.raises(ConflictError):
        await service.update_member(session, gid, admin, admin, GroupRole.MEMBER)
    with pytest.raises(ConflictError):
        await service.remove_member(session, gid, admin, admin)
    repo.count_admins.return_value = 2
    await service.remove_member(session, gid, admin, admin)
    repo.remove_member.assert_awaited_once_with(session, gid, admin)


@pytest.mark.asyncio
async def test_member_can_leave_but_not_remove_others(service, repo, session):
    gid, me, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    repo.find_by_id.return_value = _group(gid)
    repo.find_member.return_value = _member("member", me)
    with pytest.raises(AuthorizationError):
        await service.remove_member(session, gid, me, other)
    await service.remove_member(session, gid, me, me)
    repo.remove_member.assert_awaited_once_with(session, gid, me)
    repo.find_member.return_value = None
    with pytest.raises(NotFoundError):
        await service.remove_member(session, gid, me, me)


@pytest.mark.asyncio
async def test_update_member_role(service, repo, session):
    gid, admin, target = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    repo.find_by_id.return_value = _group(gid)
    repo.find_member.side_effect = [_member("admin", admin), _member("member", target), _member("admin", admin)]
    await service.update_member(session, gid, admin, target, GroupRole.ADMIN)
    repo.update_member_role.assert_awaited_once_with(session, gid, target, "admin")
    repo.find_member.side_effect = [_member("admin", admin), None]
    with pytest.raises(NotFoundError):
        await service.update_member(session, gid, admin, target, GroupRole.ADMIN)


@pytest.mark.asyncio
async def test_listings(service, repo, session):
    uid = uuid.uuid4()
    g = _group()
    repo.find_for_user.return_value = [(g, _member("admin", uid))]
    repo.member_counts.return_value = {g.group_id: 3}
    mine = await service.list_mine(session, uid)
    assert mine[0].member_count == 3 and mine[0].my_role == GroupRole.ADMIN
    assert (await service.memberships(session, uid))[0].group_name == "Acme"
    repo.find_all.return_value = [g]
    repo.count.return_value = 1
    items, meta = await service.list_all(session, 0, 10)
    assert len(items) == 1 and meta.total == 1
