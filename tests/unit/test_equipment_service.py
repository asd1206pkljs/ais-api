import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import AuthorizationError, NotFoundError
from app.models.equipment import Equipment
from app.schemas.equipment import EquipmentCreate
from app.services.equipment_service import EquipmentService


def _make_equipment(owner_id=None, viewers=None, editors=None) -> Equipment:
    eq = MagicMock(spec=Equipment)
    eq.equipment_id = uuid.uuid4()
    eq.equipment_name = "Test Equipment"
    eq.equipment_configuration_file_path = "/tmp/config.json"
    eq.owner_id = owner_id or uuid.uuid4()
    eq.viewers = viewers or []
    eq.editors = editors or []
    eq.created_at = None
    eq.updated_at = None
    return eq


@pytest.fixture
def repo():
    return AsyncMock()


@pytest.fixture
def storage():
    s = MagicMock()
    s.equipment_path.return_value = "equipment/xxx/config.json"
    s.write_json.return_value = "/tmp/ais/equipment/xxx/config.json"
    return s


@pytest.fixture
def service(repo, storage):
    return EquipmentService(repo, storage)


@pytest.fixture
def session():
    return AsyncMock()


@pytest.mark.asyncio
async def test_create_equipment(service, repo, storage, session):
    owner_id = uuid.uuid4()
    eq = _make_equipment(owner_id=owner_id)
    repo.create.return_value = eq
    result = await service.create(session, owner_id, EquipmentCreate(equipment_name="Eqp1"))
    storage.write_json.assert_called_once()
    repo.create.assert_called_once()
    assert result.owner_id == owner_id


@pytest.mark.asyncio
async def test_get_equipment_owner_can_view(service, repo, session):
    owner_id = uuid.uuid4()
    eq = _make_equipment(owner_id=owner_id)
    repo.find_by_id.return_value = eq
    result = await service.get(session, eq.equipment_id, owner_id)
    assert result.equipment_id == eq.equipment_id


@pytest.mark.asyncio
async def test_get_equipment_viewer_can_view(service, repo, session):
    owner_id = uuid.uuid4()
    viewer_id = uuid.uuid4()
    eq = _make_equipment(owner_id=owner_id, viewers=[str(viewer_id)])
    repo.find_by_id.return_value = eq
    result = await service.get(session, eq.equipment_id, viewer_id)
    assert result.equipment_id == eq.equipment_id


@pytest.mark.asyncio
async def test_get_equipment_unauthorized(service, repo, session):
    eq = _make_equipment()
    repo.find_by_id.return_value = eq
    with pytest.raises(AuthorizationError):
        await service.get(session, eq.equipment_id, uuid.uuid4())


@pytest.mark.asyncio
async def test_get_equipment_not_found(service, repo, session):
    repo.find_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.get(session, uuid.uuid4(), uuid.uuid4())


@pytest.mark.asyncio
async def test_delete_only_owner(service, repo, session):
    eq = _make_equipment()
    repo.find_by_id.return_value = eq
    with pytest.raises(AuthorizationError):
        await service.delete(session, eq.equipment_id, uuid.uuid4())


@pytest.mark.asyncio
async def test_add_viewer_immutable(service, repo, storage, session):
    owner_id = uuid.uuid4()
    viewer_id = str(uuid.uuid4())
    eq = _make_equipment(owner_id=owner_id, viewers=["existing"])
    updated_eq = _make_equipment(owner_id=owner_id, viewers=["existing", viewer_id])
    repo.find_by_id.return_value = eq
    repo.update.return_value = updated_eq
    result = await service.add_viewer(session, eq.equipment_id, owner_id, viewer_id)
    call_data = repo.update.call_args[0][2]
    assert "existing" in call_data["viewers"]
    assert viewer_id in call_data["viewers"]
    assert len(call_data["viewers"]) == 2
