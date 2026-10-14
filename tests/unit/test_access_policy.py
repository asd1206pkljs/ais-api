import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.enums import SharePermission
from app.services.access import AccessPolicy, is_admin, is_admin_user


def _user(role="user", email="u@example.com"):
    u = MagicMock()
    u.role = role
    u.user_email = email
    return u


@pytest.fixture
def shares():
    return AsyncMock()


@pytest.fixture
def groups():
    g = AsyncMock()
    g.member_group_ids.return_value = []
    return g


@pytest.fixture
def users():
    return AsyncMock()


@pytest.fixture
def policy(shares, groups, users):
    return AccessPolicy(shares, groups, users)


@pytest.fixture
def session():
    return AsyncMock()


def test_is_admin_user_role_or_bootstrap_list():
    assert is_admin_user(_user(role="admin"))
    assert not is_admin_user(_user(role="user"))
    assert not is_admin_user(None)
    with patch("app.services.access.settings") as settings:
        settings.admin_emails = {"boot@example.com"}
        assert is_admin_user(_user(role="user", email="Boot@Example.com"))


@pytest.mark.asyncio
async def test_module_level_is_admin_looks_up_role(session):
    with patch("app.services.access._user_repo") as repo:
        repo.find_by_id = AsyncMock(return_value=_user(role="admin"))
        assert await is_admin(session, uuid.uuid4())
        repo.find_by_id = AsyncMock(return_value=None)
        assert not await is_admin(session, uuid.uuid4())


@pytest.mark.asyncio
async def test_principals_include_self_groups_and_public(policy, groups, session):
    uid, gid = uuid.uuid4(), uuid.uuid4()
    groups.member_group_ids.return_value = [gid]
    assert await policy.principals(session, uid) == [str(uid), str(gid), "*"]


@pytest.mark.asyncio
async def test_owner_always_allowed_without_share_lookup(policy, shares, session):
    uid = uuid.uuid4()
    assert await policy.can_view(session, "equipment", uuid.uuid4(), uid, uid)
    assert await policy.can_edit(session, "equipment", uuid.uuid4(), uid, uid)
    shares.has_permission.assert_not_called()


@pytest.mark.asyncio
async def test_share_lookup_uses_principals_and_permission(policy, shares, groups, session):
    uid, gid, rid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    groups.member_group_ids.return_value = [gid]
    shares.has_permission.return_value = True
    assert await policy.can_edit(session, "simulator", rid, uuid.uuid4(), uid)
    shares.has_permission.assert_awaited_once_with(
        session, "simulator", str(rid), [str(uid), str(gid), "*"], SharePermission.EDIT.value
    )
    shares.has_permission.return_value = False
    assert not await policy.can_view(session, "simulator", rid, uuid.uuid4(), uid)


@pytest.mark.asyncio
async def test_admin_role_has_no_implicit_content_access(policy, shares, users, session):
    users.find_by_id.return_value = _user(role="admin")
    shares.has_permission.return_value = False
    assert await policy.is_admin(session, uuid.uuid4())
    assert not await policy.can_view(session, "equipment", uuid.uuid4(), uuid.uuid4(), uuid.uuid4())


@pytest.mark.asyncio
async def test_linked_resource_inherits_equipment_access(policy, shares, session):
    uid, owner, eq_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    equipment = MagicMock(equipment_id=eq_id, owner_id=owner, save_status="complete")
    # No direct share on the recipe, but the equipment is shared for view only.
    shares.has_permission.side_effect = lambda s, rtype, rid, principals, perm: (
        rtype == "equipment" and perm == SharePermission.VIEW.value
    )
    with patch("app.repositories.equipment_repository.EquipmentRepository.find_by_id",
               new=AsyncMock(return_value=equipment)):
        assert await policy.can_view_linked(session, "flow_recipe", uuid.uuid4(), None, eq_id, uid)
        assert not await policy.can_edit_linked(session, "flow_recipe", uuid.uuid4(), None, eq_id, uid)
    # Not linked to any equipment → only direct grants count.
    assert not await policy.can_view_linked(session, "module", 1, None, None, uid)
    # Deleted equipment grants nothing.
    equipment.save_status = "deleted"
    with patch("app.repositories.equipment_repository.EquipmentRepository.find_by_id",
               new=AsyncMock(return_value=equipment)):
        assert not await policy.can_view_linked(session, "module", 1, None, eq_id, uid)
    # Owner of the recipe itself wins regardless.
    assert await policy.can_edit_linked(session, "module", 1, uid, None, uid)
