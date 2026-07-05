"""
DB 연동 래퍼: ais-api DB에서 config를 읽어 EqpModelGenerator를 호출한다.
순수 생성 로직은 eqp_model_generator.py 참조.
"""

from __future__ import annotations

import uuid as _uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import NotFoundError
from app.repositories.equipment_repository import EquipmentRepository
from app.repositories.flow_recipe_repository import FlowRecipeRepository
from app.repositories.process_recipe_repository import ProcessRecipeRepository
from app.services.file_storage_service import file_storage
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

    uid = str(user_id)
    if not (
        equipment.owner_id == user_id
        or uid in (equipment.viewers or [])
        or uid in (equipment.editors or [])
    ):
        from app.exceptions import AuthorizationError
        raise AuthorizationError()

    eq_config: dict = file_storage.read_json(equipment.equipment_configuration_file_path)

    process_recipe_configs: list[dict] = []
    for pr_id_str in eq_config.get("process_recipe_ids", []):
        try:
            pr_id = _uuid.UUID(pr_id_str)
        except ValueError:
            continue
        pr = await pr_repo.find_by_id(session, pr_id)
        if pr is None:
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
        if fr is None:
            continue
        fr_data = file_storage.read_json(fr.flow_recipe_path)
        flow_recipe_configs.append(fr_data)

    base = Path(output_base or settings.EQP_MODELS_BASE_PATH)
    eqp_name = eq_config.get("equipment_name", str(equipment_id))
    output_dir = str(base / eqp_name)

    gen = EqpModelGenerator(eq_config, flow_recipe_configs, process_recipe_configs)
    gen.generate(output_dir)
    return output_dir
