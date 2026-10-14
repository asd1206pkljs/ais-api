import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions import AuthorizationError, NotFoundError
from app.models.equipment import Equipment
from app.schemas.equipment import EquipmentCreate, EquipmentUpdate
from app.schemas.equipment_config import EquipmentConfig
from app.services.equipment_service import EquipmentService


def _make_equipment(owner_id=None, save_status="saved_temporarily") -> Equipment:
    eq = MagicMock(spec=Equipment)
    eq.equipment_id = uuid.uuid4()
    eq.equipment_name = "Test Equipment"
    eq.equipment_configuration_file_path = "/tmp/config.json"
    eq.owner_id = owner_id or uuid.uuid4()
    eq.save_status = save_status
    eq.created_at = datetime.now(timezone.utc)
    eq.updated_at = datetime.now(timezone.utc)
    return eq


@pytest.fixture
def repo():
    return AsyncMock()


@pytest.fixture
def storage():
    s = MagicMock()
    s.equipment_path.return_value = "equipment/xxx/config.json"
    s.write_json.return_value = "/tmp/ais/equipment/xxx/config.json"
    s.read_json.return_value = {"equipment_name": "E", "cluster_type": "single_cluster",
                                "modules": [], "timetables": {}, "flow_recipe_ids": [], "process_recipe_ids": []}
    return s


@pytest.fixture
def access():
    a = AsyncMock()
    a.is_admin.return_value = False
    a.is_owner = lambda owner, uid: owner == uid
    a.principals.return_value = ["p"]
    return a


@pytest.fixture
def sharing():
    s = AsyncMock()
    s.access_lists.return_value = {}
    return s


@pytest.fixture
def service(repo, storage, access, sharing):
    children = []
    for _ in range(3):
        r = AsyncMock()
        r.find_by_ids.return_value = []
        children.append(r)
    return EquipmentService(repo, storage, *children, access, sharing, AsyncMock())


@pytest.fixture
def session():
    return AsyncMock()


@pytest.mark.asyncio
async def test_create_equipment(service, repo, storage, session):
    owner_id = uuid.uuid4()
    repo.create.return_value = _make_equipment(owner_id=owner_id)
    result = await service.create(session, owner_id, EquipmentCreate(equipment_name="Eqp1"))
    storage.write_json.assert_called_once()
    assert repo.create.call_args[0][1]["owner_id"] == owner_id
    assert "viewers" not in repo.create.call_args[0][1]  # sharing lives in resource_shares now
    assert result.owner_id == owner_id and result.viewers == [] and result.editors == []


@pytest.mark.asyncio
async def test_read_carries_access_lists_from_shares(service, repo, sharing, access, session):
    owner = uuid.uuid4()
    eq = _make_equipment(owner_id=owner)
    repo.find_by_id.return_value = eq
    sharing.access_lists.return_value = {str(eq.equipment_id): (["v", "e"], ["e"])}
    result = await service.get(session, eq.equipment_id, owner)
    assert result.viewers == ["v", "e"] and result.editors == ["e"]
    access.can_view.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_metadata_allows_admin_but_config_does_not(service, repo, access, session):
    eq = _make_equipment()
    repo.find_by_id.return_value = eq
    access.can_view.return_value = False
    access.is_admin.return_value = True
    assert (await service.get(session, eq.equipment_id, uuid.uuid4())).equipment_id == eq.equipment_id
    with pytest.raises(AuthorizationError):
        await service.get_config(session, eq.equipment_id, uuid.uuid4())
    with pytest.raises(AuthorizationError):
        await service.copy(session, eq.equipment_id, uuid.uuid4(), "copy")


@pytest.mark.asyncio
async def test_get_unauthorized_and_missing(service, repo, access, session):
    eq = _make_equipment()
    repo.find_by_id.return_value = eq
    access.can_view.return_value = False
    with pytest.raises(AuthorizationError):
        await service.get(session, eq.equipment_id, uuid.uuid4())
    repo.find_by_id.return_value = _make_equipment(save_status="deleted")
    with pytest.raises(NotFoundError):
        await service.get(session, eq.equipment_id, uuid.uuid4())
    repo.find_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.get_config(session, eq.equipment_id, uuid.uuid4())


@pytest.mark.asyncio
async def test_update_config_requires_edit_and_links_children(service, repo, storage, access, session):
    eq = _make_equipment()
    repo.find_by_id.return_value = eq
    access.can_edit.return_value = False
    config = EquipmentConfig(equipment_name="E", cluster_type="single_cluster", modules=[],
                             flow_recipe_ids=[str(uuid.uuid4()), "junk"], process_recipe_ids=[])
    with pytest.raises(AuthorizationError):
        await service.update_config(session, eq.equipment_id, uuid.uuid4(), config)
    access.can_edit.return_value = True
    await service.update_config(session, eq.equipment_id, uuid.uuid4(), config)
    storage.write_json.assert_called_once_with(eq.equipment_configuration_file_path, config.model_dump())
    flow_args = service._flow_repo.sync_equipment_link.call_args[0]
    assert flow_args[1] == eq.equipment_id and len(flow_args[2]) == 1 and flow_args[3] == eq.owner_id
    service._module_repo.sync_equipment_link.assert_awaited_once_with(session, eq.equipment_id, [], eq.owner_id)


@pytest.mark.asyncio
async def test_update_config_rejects_strangers_rows(service, repo, access, session):
    """An editor must not be able to pull someone else's module into their
    equipment and inherit access to it."""
    from app.exceptions import ValidationError

    eq = _make_equipment()
    repo.find_by_id.return_value = eq
    access.can_edit.return_value = True
    stranger_module = MagicMock(module_id=7, owner_id=uuid.uuid4(), equipment_id=None)
    service._module_repo.find_by_ids.return_value = [stranger_module]
    config = EquipmentConfig(equipment_name="E", cluster_type="single_cluster",
                             modules=[{"module_id": 7, "cluster": ["efem"]}])
    access.can_edit_linked.return_value = False
    with pytest.raises(ValidationError):
        await service.update_config(session, eq.equipment_id, uuid.uuid4(), config)
    service._module_repo.sync_equipment_link.assert_not_called()
    # ...unless the stranger actually shared it for editing.
    access.can_edit_linked.return_value = True
    await service.update_config(session, eq.equipment_id, uuid.uuid4(), config)
    service._module_repo.sync_equipment_link.assert_awaited_once()
    # Unowned legacy rows and the equipment owner's rows pass without a lookup.
    access.can_edit_linked.reset_mock()
    service._module_repo.find_by_ids.return_value = [
        MagicMock(module_id=7, owner_id=None, equipment_id=None),
        MagicMock(module_id=8, owner_id=eq.owner_id, equipment_id=None),
    ]
    await service.update_config(session, eq.equipment_id, uuid.uuid4(), config)
    access.can_edit_linked.assert_not_called()


@pytest.mark.asyncio
async def test_update_and_delete_rules(service, repo, storage, access, sharing, session):
    owner = uuid.uuid4()
    eq = _make_equipment(owner_id=owner)
    repo.find_by_id.return_value = eq
    repo.update.return_value = eq
    access.can_edit.return_value = True
    await service.update(session, eq.equipment_id, uuid.uuid4(), EquipmentUpdate(equipment_name="N"))
    repo.update.assert_awaited_once_with(session, eq.equipment_id, {"equipment_name": "N"})
    with pytest.raises(AuthorizationError):  # editor but not owner
        await service.delete(session, eq.equipment_id, uuid.uuid4())
    await service.delete(session, eq.equipment_id, owner)
    storage.delete.assert_called_once_with(eq.equipment_configuration_file_path)
    sharing.delete_for_resource.assert_awaited_once_with(session, "equipment", eq.equipment_id)
    repo.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_admin_sees_all_users_see_accessible(service, repo, access, session):
    uid = uuid.uuid4()
    repo.find_accessible_by_user.return_value = [_make_equipment()]
    repo.find_all.return_value = [_make_equipment(), _make_equipment()]
    assert len(await service.list_by_owner(session, uid)) == 1
    repo.find_accessible_by_user.assert_awaited_once_with(session, uid, ["p"], 0, 100)
    access.is_admin.return_value = True
    assert len(await service.list_by_owner(session, uid)) == 2


@pytest.mark.asyncio
async def test_legacy_viewer_editor_endpoints_delegate_to_sharing(service, repo, sharing, session):
    owner = uuid.uuid4()
    eq = _make_equipment(owner_id=owner)
    repo.find_by_id.return_value = eq
    target = str(uuid.uuid4())
    await service.add_viewer(session, eq.equipment_id, owner, target)
    await service.add_editor(session, eq.equipment_id, owner, target)
    await service.remove_viewer(session, eq.equipment_id, owner, target)
    await service.remove_editor(session, eq.equipment_id, owner, target)
    assert sharing.grant_legacy.await_count == 2 and sharing.revoke_legacy.await_count == 2


@pytest.mark.asyncio
async def test_copy_creates_owned_children(service, repo, storage, access, session):
    owner, copier = uuid.uuid4(), uuid.uuid4()
    src = _make_equipment(owner_id=owner)
    repo.find_by_id.return_value = src
    access.can_view.return_value = True
    pr_id, fr_id = uuid.uuid4(), uuid.uuid4()
    storage.read_json.side_effect = [
        {"equipment_name": "E", "cluster_type": "single_cluster",
         "modules": [{"module_id": 1, "cluster": ["a"]}], "timetables": {},
         "process_recipe_ids": [str(pr_id), "junk"], "flow_recipe_ids": [str(fr_id)]},
        {"user_added_process_modules": [1, 99]},
        {"process_recipe_steps": [{"process_recipe_id": str(pr_id)}], "module_sequence": [["1", "x"]]},
    ]
    module = MagicMock(module_name="m", module_type="robot", module_subtype=[], save_status="complete")
    service._module_repo.find_by_id.return_value = module
    service._module_repo.create.return_value = MagicMock(module_id=42)
    service._process_repo.find_by_id.return_value = MagicMock(process_recipe_name="p", process_recipe_path="/p", save_status="complete")
    service._flow_repo.find_by_id.return_value = MagicMock(flow_recipe_name="f", flow_recipe_path="/f", save_status="complete")
    repo.create.return_value = _make_equipment(owner_id=copier)

    await service.copy(session, src.equipment_id, copier, "Copy")

    assert service._module_repo.create.call_args[0][1]["owner_id"] == copier
    assert service._process_repo.create.call_args[0][1]["owner_id"] == copier
    assert service._flow_repo.create.call_args[0][1]["owner_id"] == copier
    new_cfg = storage.write_json.call_args_list[-1][0][1]
    assert new_cfg["modules"][0]["module_id"] == 42 and new_cfg["equipment_name"] == "Copy"
    assert len(new_cfg["process_recipe_ids"]) == 1 and len(new_cfg["flow_recipe_ids"]) == 1
    assert repo.create.call_args[0][1]["owner_id"] == copier
