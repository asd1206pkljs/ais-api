import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions import NotFoundError, ValidationError
from app.models.flow_recipe import FlowRecipe
from app.models.process_recipe import ProcessRecipe
from app.schemas.flow_recipe import FlowRecipeCreate
from app.schemas.flow_recipe_config import FlowRecipeConfig, ProcessRecipeStep
from app.services.flow_recipe_service import FlowRecipeService


def _make_flow_recipe() -> FlowRecipe:
    r = MagicMock(spec=FlowRecipe)
    r.flow_recipe_id = uuid.uuid4()
    r.flow_recipe_name = "FR1"
    r.flow_recipe_path = "/tmp/fr.json"
    r.save_status = "temporary"
    r.created_at = None
    r.updated_at = None
    return r


def _make_process_recipe() -> ProcessRecipe:
    r = MagicMock(spec=ProcessRecipe)
    r.process_recipe_id = uuid.uuid4()
    r.process_recipe_name = "PR1"
    r.process_recipe_path = "/tmp/pr.json"
    r.save_status = "temporary"
    r.created_at = None
    r.updated_at = None
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
    s.flow_recipe_path.return_value = "flow_recipes/xxx/config.json"
    s.write_json.return_value = "/tmp/ais/flow_recipes/xxx/config.json"
    return s


@pytest.fixture
def service(repo, process_repo, storage):
    return FlowRecipeService(repo, process_repo, storage)


@pytest.fixture
def session():
    return AsyncMock()


@pytest.mark.asyncio
async def test_create_flow_recipe(service, repo, storage, session):
    fr = _make_flow_recipe()
    repo.create.return_value = fr
    result = await service.create(session, FlowRecipeCreate(flow_recipe_name="FR1"))
    storage.write_json.assert_called_once()
    assert result.flow_recipe_name == "FR1"


@pytest.mark.asyncio
async def test_get_not_found(service, repo, session):
    repo.find_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.get(session, uuid.uuid4())


@pytest.mark.asyncio
async def test_update_config_validates_process_recipe_ids(service, repo, process_repo, storage, session):
    fr = _make_flow_recipe()
    repo.find_by_id.return_value = fr
    process_repo.find_by_id.return_value = None
    config = FlowRecipeConfig(
        flow_recipe_name="FR1",
        num_process_steps=1,
        process_recipe_steps=[ProcessRecipeStep(step=1, process_recipe_id=str(uuid.uuid4()))],
    )
    with pytest.raises(ValidationError):
        await service.update_config(session, fr.flow_recipe_id, config)


@pytest.mark.asyncio
async def test_update_config_valid(service, repo, process_repo, storage, session):
    fr = _make_flow_recipe()
    pr = _make_process_recipe()
    repo.find_by_id.return_value = fr
    process_repo.find_by_id.return_value = pr
    config = FlowRecipeConfig(
        flow_recipe_name="FR1",
        num_process_steps=1,
        process_recipe_steps=[ProcessRecipeStep(step=1, process_recipe_id=str(pr.process_recipe_id))],
    )
    result = await service.update_config(session, fr.flow_recipe_id, config)
    storage.write_json.assert_called_once()
    assert result.num_process_steps == 1
