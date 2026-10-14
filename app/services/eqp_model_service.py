"""
DB 연동 래퍼: ais-api DB에서 config를 읽어 EqpModelGenerator를 호출한다.
순수 생성 로직은 eqp_model_generator.py 참조.
"""

from __future__ import annotations

import uuid as _uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.enums import ResourceType
from app.enums import audit_action as act
from app.exceptions import AuthorizationError, NotFoundError
from app.repositories.equipment_repository import EquipmentRepository
from app.repositories.flow_recipe_repository import FlowRecipeRepository
from app.repositories.process_recipe_repository import ProcessRecipeRepository
from app.services.access import access_policy
from app.services.audit_service import audit
from app.services.file_storage_service import file_storage
from app.services.model_paths import model_output_dir, safe_model_name
from app.services.eqp_model_generator import EqpModelGenerator  # noqa: F401 (re-export)


async def generate_eqp_model(
    session: AsyncSession,
    equipment_id: _uuid.UUID,
    user_id: _uuid.UUID,
    output_base: str | None = None,
) -> str:
    """장비 config를 DB에서 읽어 eqp_models/{name}/ 디렉토리를 생성하고 경로를 반환."""
    eq_repo = EquipmentRepository()
    fr_repo = FlowRecipeRepository()
    pr_repo = ProcessRecipeRepository()

    equipment = await eq_repo.find_by_id(session, equipment_id)
    if equipment is None:
        raise NotFoundError("Equipment", str(equipment_id))

    # Generating reads the full content, so it follows view access (no admin bypass).
    if not await access_policy.can_view(
        session, ResourceType.EQUIPMENT.value, equipment.equipment_id, equipment.owner_id, user_id
    ):
        raise AuthorizationError()

    eq_config: dict = file_storage.read_json(equipment.equipment_configuration_file_path)

    process_recipe_configs: list[dict] = []
    for pr_id_str in eq_config.get("process_recipe_ids", []):
        try:
            pr_id = _uuid.UUID(pr_id_str)
        except ValueError:
            continue
        pr = await pr_repo.find_by_id(session, pr_id)
        if pr is None or not await access_policy.can_view_linked(
            session, ResourceType.PROCESS_RECIPE.value, pr.process_recipe_id, pr.owner_id, pr.equipment_id, user_id
        ):
            continue
        pr_data = file_storage.read_json(pr.process_recipe_path)
        pr_data["process_recipe_id"] = pr_id_str
        process_recipe_configs.append(pr_data)

    flow_recipe_configs: list[dict] = []
    for fr_id_str in eq_config.get("flow_recipe_ids", []):
        try:
            fr_id = _uuid.UUID(fr_id_str)
        except ValueError:
            continue
        fr = await fr_repo.find_by_id(session, fr_id)
        if fr is None or not await access_policy.can_view_linked(
            session, ResourceType.FLOW_RECIPE.value, fr.flow_recipe_id, fr.owner_id, fr.equipment_id, user_id
        ):
            continue
        fr_data = file_storage.read_json(fr.flow_recipe_path)
        flow_recipe_configs.append(fr_data)

    base = Path(output_base or settings.EQP_MODELS_BASE_PATH)
    eqp_name = safe_model_name(eq_config.get("equipment_name", ""), str(equipment_id))
    output_dir = model_output_dir(base, eqp_name)

    gen = EqpModelGenerator(eq_config, flow_recipe_configs, process_recipe_configs)
    gen.generate(output_dir)
    await audit.record(session, act.RESOURCE_GENERATED, resource_type=ResourceType.EQUIPMENT.value,
                       resource_id=equipment_id)
    return output_dir
