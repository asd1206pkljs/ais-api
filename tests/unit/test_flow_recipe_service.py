import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.schemas.flow_recipe import FlowRecipeCreate, FlowRecipeUpdate
from app.schemas.flow_recipe_config import FlowRecipeConfig
from app.services.flow_recipe_service import FlowRecipeService


def _recipe(owner=None, equipment_id=None):
    r = MagicMock()
    r.flow_recipe_id = uuid.uuid4()
    r.flow_recipe_name = "F"
    r.flow_recipe_path = "/f.json"
    r.save_status = "temporary"
    r.owner_id = owner
    r.equipment_id = equipment_id
    r.created_at = datetime.now(timezone.utc)
    r.updated_at = datetime.now(timezone.utc)
    return r


@pytest.fixture
def repo():
    return AsyncMock()


@pytest.fixture
def process_repo():
    return AsyncMock()


@pytest.fixture
def storage():
    s = MagicMock()
    s.flow_recipe_path.return_value = "flow_recipes/x/config.json"
    s.write_json.return_value = "/f.json"
    s.read_json.return_value = {"flow_recipe_name": "F", "num_process_steps": 0,
                                "process_recipe_steps": [], "module_sequence": []}
    return s


@pytest.fixture
def access():
    a = AsyncMock()
    a.is_admin.return_value = False
    a.is_owner = lambda owner, uid: owner == uid
    a.principals.return_value = ["p"]
    a.can_view_linked.return_value = True
    a.can_edit_linked.return_value = True
    return a


@pytest.fixture
def service(repo, process_repo, storage, access):
    return FlowRecipeService(repo, process_repo, storage, access, AsyncMock(), AsyncMock())


@pytest.fixture
def session():
    return AsyncMock()


@pytest.mark.asyncio
async def test_create_sets_owner(service, repo, session):
    uid = uuid.uuid4()
    repo.create.return_value = _recipe(owner=uid)
    result = await service.create(session, uid, FlowRecipeCreate(flow_recipe_name="F"))
    assert repo.create.call_args[0][1]["owner_id"] == uid and result.owner_id == uid


@pytest.mark.asyncio
async def test_view_and_edit_guards(service, repo, access, session):
    recipe = _recipe()
    repo.find_by_id.return_value = recipe
    access.can_view_linked.return_value = False
    with pytest.raises(AuthorizationError):
        await service.get(session, recipe.flow_recipe_id, uuid.uuid4())
    with pytest.raises(AuthorizationError):
        await service.get_config(session, recipe.flow_recipe_id, uuid.uuid4())
    access.can_edit_linked.return_value = False
    with pytest.raises(AuthorizationError):
        await service.update(session, recipe.flow_recipe_id, uuid.uuid4(), FlowRecipeUpdate(flow_recipe_name="x"))
    with pytest.raises(AuthorizationError):  # not owner, not editor
        await service.delete(session, recipe.flow_recipe_id, uuid.uuid4())
    repo.find_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.get(session, recipe.flow_recipe_id, uuid.uuid4())


@pytest.mark.asyncio
async def test_update_config_validates_process_recipes_visible_to_user(service, repo, process_repo, access, session):
    recipe = _recipe()
    repo.find_by_id.return_value = recipe
    pr_id = uuid.uuid4()
    config = FlowRecipeConfig(flow_recipe_name="F", num_process_steps=1,
                              process_recipe_steps=[{"process_recipe_id": str(pr_id), "step": 1}],
                              module_sequence=[])
    process_repo.find_by_id.return_value = None
    with pytest.raises(ValidationError):
        await service.update_config(session, recipe.flow_recipe_id, uuid.uuid4(), config)
    pr = MagicMock(process_recipe_id=pr_id, owner_id=uuid.uuid4(), equipment_id=None)
    process_repo.find_by_id.return_value = pr
    access.can_view_linked.side_effect = [False]  # the process recipe belongs to someone else
    with pytest.raises(ValidationError):
        await service.update_config(session, recipe.flow_recipe_id, uuid.uuid4(), config)
    access.can_view_linked.side_effect = None
    await service.update_config(session, recipe.flow_recipe_id, uuid.uuid4(), config)
    service._storage.write_json.assert_called_once()


@pytest.mark.asyncio
async def test_owner_deletes(service, repo, storage, session):
    uid = uuid.uuid4()
    recipe = _recipe(owner=uid)
    repo.find_by_id.return_value = recipe
    await service.delete(session, recipe.flow_recipe_id, uid)
    storage.delete.assert_called_once_with("/f.json")
    repo.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_list(service, repo, access, session):
    uid = uuid.uuid4()
    repo.find_accessible.return_value = [_recipe(owner=uid)]
    repo.count_accessible.return_value = 1
    items, meta = await service.list_for_user(session, uid)
    assert len(items) == 1 and meta.total == 1
    access.is_admin.return_value = True
    repo.find_all.return_value = [_recipe(), _recipe()]
    repo.count.return_value = 2
    items, meta = await service.list_for_user(session, uid)
    assert len(items) == 2
