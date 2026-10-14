import io
import tarfile
import tempfile
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import _INTERNAL_USER_ID
from app.enums import ResourceType, SharePermission
from app.enums import audit_action as act
from app.exceptions import AuthorizationError, NotFoundError
from app.models.simulator import Simulator
from app.repositories.equipment_repository import EquipmentRepository
from app.repositories.flow_recipe_repository import FlowRecipeRepository
from app.repositories.process_recipe_repository import ProcessRecipeRepository
from app.repositories.simulator_repository import SimulatorRepository
from app.schemas.simulator import SimulatorCreate, SimulatorRead, SimulatorUpdate
from app.schemas.simulator_config import SimulatorConfig
from app.services.access import AccessPolicy, access_policy
from app.services.audit_service import AuditService, audit
from app.services.eqp_model_generator import EqpModelGenerator
from app.services.file_storage_service import FileStorageService, file_storage
from app.services.model_paths import model_output_dir, safe_model_name
from app.services.sharing_service import SharingService

RTYPE = ResourceType.SIMULATOR.value


class SimulatorService:
    def __init__(
        self,
        repo: SimulatorRepository,
        storage: FileStorageService = file_storage,
        access: AccessPolicy = access_policy,
        sharing: SharingService | None = None,
        audit_svc: AuditService = audit,
    ):
        self._repo = repo
        self._storage = storage
        self._access = access
        self._sharing = sharing or SharingService(access=access, audit_svc=audit_svc)
        self._audit = audit_svc

    # --- helpers ---------------------------------------------------------------

    async def _load(self, session: AsyncSession, simulator_id: uuid.UUID) -> Simulator:
        simulator = await self._repo.find_by_id(session, simulator_id)
        if simulator is None or simulator.save_status == "deleted":
            raise NotFoundError("Simulator", str(simulator_id))
        return simulator

    async def _can_view(self, session, simulator, user_id) -> bool:
        return await self._access.can_view(session, RTYPE, simulator.simulator_id, simulator.owner_id, user_id)

    async def _can_edit(self, session, simulator, user_id) -> bool:
        return await self._access.can_edit(session, RTYPE, simulator.simulator_id, simulator.owner_id, user_id)

    async def _reads(
        self, session: AsyncSession, rows: list[Simulator], viewer_id: uuid.UUID | None = None
    ) -> list[SimulatorRead]:
        lists = await self._sharing.access_lists(
            session, RTYPE, [str(s.simulator_id) for s in rows],
            viewer_id=viewer_id, owners={str(s.simulator_id): s.owner_id for s in rows},
        )
        out = []
        for s in rows:
            viewers, editors = lists.get(str(s.simulator_id), ([], []))
            read = SimulatorRead.model_validate(s)
            out.append(read.model_copy(update={"viewers": viewers, "editors": editors}))
        return out

    async def _read(
        self, session: AsyncSession, row: Simulator, viewer_id: uuid.UUID | None = None
    ) -> SimulatorRead:
        (read,) = await self._reads(session, [row], viewer_id)
        return read

    async def _require_equipment_view(self, session: AsyncSession, equipment_id: uuid.UUID, user_id: uuid.UUID):
        """A simulator may only point at equipment its user is allowed to see."""
        equipment = await EquipmentRepository().find_by_id(session, equipment_id)
        if equipment is None or equipment.save_status == "deleted":
            raise NotFoundError("Equipment", str(equipment_id))
        if user_id != _INTERNAL_USER_ID and not await self._access.can_view(
            session, ResourceType.EQUIPMENT.value, equipment.equipment_id, equipment.owner_id, user_id
        ):
            raise AuthorizationError("No access to the selected equipment")
        return equipment

    # --- CRUD ------------------------------------------------------------------

    async def list_by_owner(
        self, session: AsyncSession, owner_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[SimulatorRead]:
        """Internal callers and admins see every simulator's metadata; users see
        what they own or were granted."""
        if owner_id == _INTERNAL_USER_ID or await self._access.is_admin(session, owner_id):
            simulators = await self._repo.find_all(session, skip, limit)
        else:
            principals = await self._access.principals(session, owner_id)
            simulators = await self._repo.find_accessible_by_user(session, owner_id, principals, skip, limit)
        return await self._reads(session, simulators, owner_id)

    async def create(
        self, session: AsyncSession, owner_id: uuid.UUID, data: SimulatorCreate
    ) -> SimulatorRead:
        simulator_id = uuid.uuid4()
        rel_path = self._storage.simulator_path(simulator_id)
        abs_path = self._storage.write_json(rel_path, {
            "selected_flow_recipe_ids": [],
            "module_time_configs": {},
        })
        simulator = await self._repo.create(session, {
            "simulator_id": simulator_id,
            "simulator_name": data.simulator_name,
            "equipment_id": None,
            "simulator_path": abs_path,
            "owner_id": owner_id,
            "save_status": "saved_temporarily",
        })
        await self._audit.record(session, act.RESOURCE_CREATED, resource_type=RTYPE, resource_id=simulator_id,
                                 details={"name": data.simulator_name})
        return await self._read(session, simulator, owner_id)

    async def copy(
        self, session: AsyncSession, simulator_id: uuid.UUID, user_id: uuid.UUID, new_name: str
    ) -> SimulatorRead:
        """Copy a simulator (same equipment reference + verbatim config) for ``user_id``.
        Requires view access; copying is reading the content, so admins get no bypass."""
        source = await self._load(session, simulator_id)
        if not await self._can_view(session, source, user_id):
            raise AuthorizationError()
        if source.equipment_id is not None:
            await self._require_equipment_view(session, source.equipment_id, user_id)

        src_cfg = self._storage.read_json(source.simulator_path)
        new_id = uuid.uuid4()
        abs_path = self._storage.write_json(self._storage.simulator_path(new_id), src_cfg)
        simulator = await self._repo.create(session, {
            "simulator_id": new_id,
            "simulator_name": new_name,
            "equipment_id": source.equipment_id,
            "simulator_path": abs_path,
            "owner_id": user_id,
            "save_status": source.save_status,
        })
        await self._audit.record(session, act.RESOURCE_COPIED, resource_type=RTYPE, resource_id=new_id,
                                 details={"source": str(simulator_id)})
        return await self._read(session, simulator, user_id)

    async def get(self, session: AsyncSession, simulator_id: uuid.UUID, user_id: uuid.UUID) -> SimulatorRead:
        simulator = await self._load(session, simulator_id)
        if not await self._can_view(session, simulator, user_id) and not await self._access.is_admin(session, user_id):
            raise AuthorizationError()
        return await self._read(session, simulator, user_id)

    async def get_config(self, session: AsyncSession, simulator_id: uuid.UUID, user_id: uuid.UUID) -> SimulatorConfig:
        simulator = await self._load(session, simulator_id)
        if not await self._can_view(session, simulator, user_id):
            raise AuthorizationError()
        data = self._storage.read_json(simulator.simulator_path)
        await self._audit.record(session, act.RESOURCE_READ, resource_type=RTYPE, resource_id=simulator_id,
                                 details={"part": "config"})
        return SimulatorConfig.model_validate(data)

    async def update_config(
        self, session: AsyncSession, simulator_id: uuid.UUID, user_id: uuid.UUID, config: SimulatorConfig
    ) -> SimulatorConfig:
        simulator = await self._load(session, simulator_id)
        if not await self._can_edit(session, simulator, user_id):
            raise AuthorizationError()
        self._storage.write_json(simulator.simulator_path, config.model_dump())
        await self._audit.record(session, act.RESOURCE_UPDATED, resource_type=RTYPE, resource_id=simulator_id,
                                 details={"part": "config"})
        return config

    async def update(
        self, session: AsyncSession, simulator_id: uuid.UUID, user_id: uuid.UUID, data: SimulatorUpdate
    ) -> SimulatorRead:
        simulator = await self._load(session, simulator_id)
        if not await self._can_edit(session, simulator, user_id):
            raise AuthorizationError()
        changes = data.model_dump(exclude_none=True)
        if "equipment_id" in changes and changes["equipment_id"] != simulator.equipment_id:
            await self._require_equipment_view(session, changes["equipment_id"], user_id)
        updated = await self._repo.update(session, simulator_id, changes)
        await self._audit.record(session, act.RESOURCE_UPDATED, resource_type=RTYPE, resource_id=simulator_id,
                                 details=changes)
        return await self._read(session, updated, user_id)

    async def _may_read(self, session: AsyncSession, rtype: str, rid, row, user_id: uuid.UUID) -> bool:
        """Recipes referenced by the equipment config still get their own check,
        so a planted id never leaks a stranger's recipe into a model."""
        if user_id == _INTERNAL_USER_ID:
            return True
        return await self._access.can_view_linked(session, rtype, rid, row.owner_id, row.equipment_id, user_id)

    async def _require_generate_access(self, session: AsyncSession, simulator: Simulator, user_id: uuid.UUID) -> None:
        if user_id == _INTERNAL_USER_ID:
            return  # training servers act for the job owner (authenticated by API key)
        if not await self._can_edit(session, simulator, user_id):
            raise AuthorizationError()

    async def generate(
        self,
        session: AsyncSession,
        simulator_id: uuid.UUID,
        user_id: uuid.UUID,
        output_base: str | None = None,
    ) -> str:
        """simulator config + equipment config를 머지해 eqp_model 디렉토리 생성, 경로 반환."""
        simulator = await self._load(session, simulator_id)
        await self._require_generate_access(session, simulator, user_id)
        if simulator.equipment_id is None:
            raise NotFoundError("Equipment", "none")
        equipment = await self._require_equipment_view(session, simulator.equipment_id, user_id)

        sim_config = self._storage.read_json(simulator.simulator_path)
        selected_fr_ids: set[str] = set(sim_config.get("selected_flow_recipe_ids", []))
        sim_timetables: dict = sim_config.get("module_time_configs", {})

        fr_repo = FlowRecipeRepository()
        pr_repo = ProcessRecipeRepository()

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
            if fr is None or not await self._may_read(session, ResourceType.FLOW_RECIPE.value, fr.flow_recipe_id, fr, user_id):
                continue
            flow_recipe_configs.append(self._storage.read_json(fr.flow_recipe_path))

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
            if pr is None or not await self._may_read(session, ResourceType.PROCESS_RECIPE.value, pr.process_recipe_id, pr, user_id):
                continue
            pr_data = self._storage.read_json(pr.process_recipe_path)
            pr_data["process_recipe_id"] = pr_id_str
            process_recipe_configs.append(pr_data)

        base = Path(output_base or settings.EQP_MODELS_BASE_PATH)
        eqp_name = safe_model_name(eq_config.get("equipment_name", ""), str(simulator.equipment_id))
        output_dir = model_output_dir(base, f"{eqp_name}--{simulator_id}")

        gen = EqpModelGenerator(eq_config, flow_recipe_configs, process_recipe_configs)
        gen.generate(output_dir)
        await self._audit.record(session, act.RESOURCE_GENERATED, resource_type=RTYPE, resource_id=simulator_id)
        return output_dir

    async def generate_bundle(
        self, session: AsyncSession, simulator_id: uuid.UUID, user_id: uuid.UUID
    ) -> tuple[str, bytes]:
        """eqp_model을 생성한 뒤 tar.gz 번들로 묶어 (파일명, bytes) 반환.

        The model is built in a temporary directory so no plaintext copy of the
        user's data is left on the API server's disk.
        """
        with tempfile.TemporaryDirectory(prefix="eqp_bundle_") as tmp:
            output_dir = await self.generate(session, simulator_id, user_id, output_base=tmp)
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                # arcname을 고정해 클라이언트가 항상 `eqp_model/`로 풀 수 있게 함
                tar.add(output_dir, arcname="eqp_model")
            filename = f"{Path(output_dir).name}.tar.gz"
        return filename, buf.getvalue()

    async def delete(self, session: AsyncSession, simulator_id: uuid.UUID, user_id: uuid.UUID) -> None:
        simulator = await self._load(session, simulator_id)
        if not self._access.is_owner(simulator.owner_id, user_id):
            raise AuthorizationError("Only the owner can delete a simulator")
        self._storage.delete(simulator.simulator_path)
        await self._sharing.delete_for_resource(session, RTYPE, simulator_id)
        await self._repo.delete(session, simulator_id)
        await self._audit.record(session, act.RESOURCE_DELETED, resource_type=RTYPE, resource_id=simulator_id)

    # --- legacy sharing endpoints (POST/DELETE .../viewers|editors) ------------------

    async def add_viewer(self, session, simulator_id, owner_id, viewer_id: str) -> SimulatorRead:
        await self._sharing.grant_legacy(session, RTYPE, str(simulator_id), owner_id, viewer_id, SharePermission.VIEW)
        return await self._read(session, await self._load(session, simulator_id), owner_id)

    async def remove_viewer(self, session, simulator_id, owner_id, viewer_id: str) -> SimulatorRead:
        await self._sharing.revoke_legacy(session, RTYPE, str(simulator_id), owner_id, viewer_id, SharePermission.VIEW)
        return await self._read(session, await self._load(session, simulator_id), owner_id)

    async def add_editor(self, session, simulator_id, owner_id, editor_id: str) -> SimulatorRead:
        await self._sharing.grant_legacy(session, RTYPE, str(simulator_id), owner_id, editor_id, SharePermission.EDIT)
        return await self._read(session, await self._load(session, simulator_id), owner_id)

    async def remove_editor(self, session, simulator_id, owner_id, editor_id: str) -> SimulatorRead:
        await self._sharing.revoke_legacy(session, RTYPE, str(simulator_id), owner_id, editor_id, SharePermission.EDIT)
        return await self._read(session, await self._load(session, simulator_id), owner_id)
