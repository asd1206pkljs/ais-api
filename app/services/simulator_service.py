import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import _INTERNAL_USER_ID
from app.exceptions import AuthorizationError, NotFoundError
from app.repositories.equipment_repository import EquipmentRepository
from app.repositories.flow_recipe_repository import FlowRecipeRepository
from app.repositories.process_recipe_repository import ProcessRecipeRepository
from app.repositories.simulator_repository import SimulatorRepository
from app.schemas.simulator import SimulatorCreate, SimulatorRead, SimulatorUpdate
from app.schemas.simulator_config import SimulatorConfig
from app.services.access import is_admin
from app.services.eqp_model_generator import EqpModelGenerator
from app.services.file_storage_service import FileStorageService, file_storage


class SimulatorService:
    def __init__(self, repo: SimulatorRepository, storage: FileStorageService = file_storage):
        self._repo = repo
        self._storage = storage

    def _can_view(self, simulator, user_id: uuid.UUID) -> bool:
        uid = str(user_id)
        viewers = simulator.viewers or []
        editors = simulator.editors or []
        return (
            simulator.owner_id == user_id
            or "*" in viewers
            or "*" in editors
            or uid in viewers
            or uid in editors
        )

    def _can_edit(self, simulator, user_id: uuid.UUID) -> bool:
        editors = simulator.editors or []
        return simulator.owner_id == user_id or "*" in editors or str(user_id) in editors

    async def list_by_owner(
        self, session: AsyncSession, owner_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[SimulatorRead]:
        if owner_id == _INTERNAL_USER_ID or await is_admin(session, owner_id):
            simulators = await self._repo.find_all(session, skip, limit)
        else:
            simulators = await self._repo.find_accessible_by_user(session, owner_id, skip, limit)
        return [SimulatorRead.model_validate(s) for s in simulators]

    async def create(
        self, session: AsyncSession, owner_id: uuid.UUID, data: SimulatorCreate
    ) -> SimulatorRead:
        simulator_id = uuid.uuid4()
        rel_path = self._storage.simulator_path(simulator_id)
        abs_path = self._storage.write_json(rel_path, {
            "selected_flow_recipe_ids": [],
            "module_time_configs": {},
        })
        owner_str = str(owner_id)
        simulator = await self._repo.create(session, {
            "simulator_id": simulator_id,
            "simulator_name": data.simulator_name,
            "equipment_id": None,
            "simulator_path": abs_path,
            "owner_id": owner_id,
            "viewers": [owner_str],
            "editors": [owner_str],
            "save_status": "saved_temporarily",
        })
        return SimulatorRead.model_validate(simulator)

    async def get(
        self, session: AsyncSession, simulator_id: uuid.UUID, user_id: uuid.UUID
    ) -> SimulatorRead:
        simulator = await self._repo.find_by_id(session, simulator_id)
        if simulator is None:
            raise NotFoundError("Simulator", str(simulator_id))
        if not self._can_view(simulator, user_id) and not await is_admin(session, user_id):
            raise AuthorizationError()
        return SimulatorRead.model_validate(simulator)

    async def get_config(
        self, session: AsyncSession, simulator_id: uuid.UUID, user_id: uuid.UUID
    ) -> SimulatorConfig:
        simulator = await self._repo.find_by_id(session, simulator_id)
        if simulator is None:
            raise NotFoundError("Simulator", str(simulator_id))
        if not self._can_view(simulator, user_id) and not await is_admin(session, user_id):
            raise AuthorizationError()
        data = self._storage.read_json(simulator.simulator_path)
        return SimulatorConfig.model_validate(data)

    async def update_config(
        self,
        session: AsyncSession,
        simulator_id: uuid.UUID,
        user_id: uuid.UUID,
        config: SimulatorConfig,
    ) -> SimulatorConfig:
        simulator = await self._repo.find_by_id(session, simulator_id)
        if simulator is None:
            raise NotFoundError("Simulator", str(simulator_id))
        if not self._can_edit(simulator, user_id):
            raise AuthorizationError()
        self._storage.write_json(simulator.simulator_path, config.model_dump())
        return config

    async def update(
        self,
        session: AsyncSession,
        simulator_id: uuid.UUID,
        user_id: uuid.UUID,
        data: SimulatorUpdate,
    ) -> SimulatorRead:
        simulator = await self._repo.find_by_id(session, simulator_id)
        if simulator is None:
            raise NotFoundError("Simulator", str(simulator_id))
        if not self._can_edit(simulator, user_id):
            raise AuthorizationError()
        updated = await self._repo.update(
            session, simulator_id, data.model_dump(exclude_none=True)
        )
        return SimulatorRead.model_validate(updated)

    async def generate(
        self,
        session: AsyncSession,
        simulator_id: uuid.UUID,
        user_id: uuid.UUID,
        output_base: str | None = None,
    ) -> str:
        """simulator config + equipment config를 머지해 eqp_model 디렉토리 생성, 경로 반환."""
        simulator = await self._repo.find_by_id(session, simulator_id)
        if simulator is None:
            raise NotFoundError("Simulator", str(simulator_id))
        if user_id != _INTERNAL_USER_ID and simulator.owner_id != user_id:
            raise AuthorizationError()

        sim_config = self._storage.read_json(simulator.simulator_path)
        selected_fr_ids: set[str] = set(sim_config.get("selected_flow_recipe_ids", []))
        sim_timetables: dict = sim_config.get("module_time_configs", {})

        eq_repo = EquipmentRepository()
        fr_repo = FlowRecipeRepository()
        pr_repo = ProcessRecipeRepository()

        equipment = await eq_repo.find_by_id(session, simulator.equipment_id)
        if equipment is None:
            raise NotFoundError("Equipment", str(simulator.equipment_id))

        eq_config: dict = self._storage.read_json(equipment.equipment_configuration_file_path)

        # equipment base timetables + simulator override 머지
        merged_timetables: dict = {**eq_config.get("timetables", {}), **sim_timetables}
        eq_config = {**eq_config, "timetables": merged_timetables}

        # 선택된 flow recipe만 로드
        flow_recipe_configs: list[dict] = []
        for fr_id_str in eq_config.get("flow_recipe_ids", []):
            if selected_fr_ids and fr_id_str not in selected_fr_ids:
                continue
            try:
                fr_id = uuid.UUID(fr_id_str)
            except ValueError:
                continue
            fr = await fr_repo.find_by_id(session, fr_id)
            if fr is None:
                continue
            fr_data = self._storage.read_json(fr.flow_recipe_path)
            flow_recipe_configs.append(fr_data)

        # 선택된 flow recipe가 참조하는 process recipe 로드
        needed_pr_ids: set[str] = set()
        for fr_data in flow_recipe_configs:
            for step in fr_data.get("process_recipe_steps", []):
                pr_id = step.get("process_recipe_id")
                if pr_id:
                    needed_pr_ids.add(pr_id)

        process_recipe_configs: list[dict] = []
        for pr_id_str in eq_config.get("process_recipe_ids", []):
            if pr_id_str not in needed_pr_ids:
                continue
            try:
                pr_id = uuid.UUID(pr_id_str)
            except ValueError:
                continue
            pr = await pr_repo.find_by_id(session, pr_id)
            if pr is None:
                continue
            pr_data = self._storage.read_json(pr.process_recipe_path)
            pr_data["process_recipe_id"] = pr_id_str
            process_recipe_configs.append(pr_data)

        base = Path(output_base or settings.EQP_MODELS_BASE_PATH)
        eqp_name = eq_config.get("equipment_name", str(simulator.equipment_id))
        output_dir = str(base / f"{eqp_name}--{simulator_id}")

        gen = EqpModelGenerator(eq_config, flow_recipe_configs, process_recipe_configs)
        gen.generate(output_dir)
        return output_dir

    async def delete(
        self, session: AsyncSession, simulator_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        simulator = await self._repo.find_by_id(session, simulator_id)
        if simulator is None:
            raise NotFoundError("Simulator", str(simulator_id))
        if simulator.owner_id != user_id:
            raise AuthorizationError()
        self._storage.delete(simulator.simulator_path)
        await self._repo.delete(session, simulator_id)

    async def add_viewer(
        self, session: AsyncSession, simulator_id: uuid.UUID, owner_id: uuid.UUID, viewer_id: str
    ) -> SimulatorRead:
        simulator = await self._repo.find_by_id(session, simulator_id)
        if simulator is None:
            raise NotFoundError("Simulator", str(simulator_id))
        if simulator.owner_id != owner_id:
            raise AuthorizationError("Only the owner can manage viewers")
        current = list(simulator.viewers or [])
        new_viewers = current if viewer_id in current else [*current, viewer_id]
        updated = await self._repo.update(session, simulator_id, {"viewers": new_viewers})
        return SimulatorRead.model_validate(updated)

    async def remove_viewer(
        self, session: AsyncSession, simulator_id: uuid.UUID, owner_id: uuid.UUID, viewer_id: str
    ) -> SimulatorRead:
        simulator = await self._repo.find_by_id(session, simulator_id)
        if simulator is None:
            raise NotFoundError("Simulator", str(simulator_id))
        if simulator.owner_id != owner_id:
            raise AuthorizationError("Only the owner can manage viewers")
        new_viewers = [v for v in (simulator.viewers or []) if v != viewer_id]
        updated = await self._repo.update(session, simulator_id, {"viewers": new_viewers})
        return SimulatorRead.model_validate(updated)

    async def add_editor(
        self, session: AsyncSession, simulator_id: uuid.UUID, owner_id: uuid.UUID, editor_id: str
    ) -> SimulatorRead:
        simulator = await self._repo.find_by_id(session, simulator_id)
        if simulator is None:
            raise NotFoundError("Simulator", str(simulator_id))
        if simulator.owner_id != owner_id:
            raise AuthorizationError("Only the owner can manage editors")
        current = list(simulator.editors or [])
        new_editors = current if editor_id in current else [*current, editor_id]
        updated = await self._repo.update(session, simulator_id, {"editors": new_editors})
        return SimulatorRead.model_validate(updated)

    async def remove_editor(
        self, session: AsyncSession, simulator_id: uuid.UUID, owner_id: uuid.UUID, editor_id: str
    ) -> SimulatorRead:
        simulator = await self._repo.find_by_id(session, simulator_id)
        if simulator is None:
            raise NotFoundError("Simulator", str(simulator_id))
        if simulator.owner_id != owner_id:
            raise AuthorizationError("Only the owner can manage editors")
        new_editors = [e for e in (simulator.editors or []) if e != editor_id]
        updated = await self._repo.update(session, simulator_id, {"editors": new_editors})
        return SimulatorRead.model_validate(updated)
