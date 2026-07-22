import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AuthorizationError, NotFoundError
from app.repositories.equipment_repository import EquipmentRepository
from app.repositories.flow_recipe_repository import FlowRecipeRepository
from app.repositories.module_repository import ModuleRepository
from app.repositories.process_recipe_repository import ProcessRecipeRepository
from app.schemas.equipment import EquipmentCreate, EquipmentRead, EquipmentUpdate
from app.schemas.equipment_config import EquipmentConfig
from app.services.access import is_admin
from app.services.file_storage_service import FileStorageService, file_storage


class EquipmentService:
    def __init__(
        self,
        repo: EquipmentRepository,
        storage: FileStorageService = file_storage,
        module_repo: ModuleRepository | None = None,
        process_recipe_repo: ProcessRecipeRepository | None = None,
        flow_recipe_repo: FlowRecipeRepository | None = None,
    ):
        self._repo = repo
        self._storage = storage
        self._module_repo = module_repo or ModuleRepository()
        self._process_repo = process_recipe_repo or ProcessRecipeRepository()
        self._flow_repo = flow_recipe_repo or FlowRecipeRepository()

    def _can_view(self, equipment, user_id: uuid.UUID) -> bool:
        uid = str(user_id)
        viewers = equipment.viewers or []
        editors = equipment.editors or []
        return (
            equipment.owner_id == user_id
            or "*" in viewers
            or "*" in editors
            or uid in viewers
            or uid in editors
        )

    def _can_edit(self, equipment, user_id: uuid.UUID) -> bool:
        editors = equipment.editors or []
        return equipment.owner_id == user_id or "*" in editors or str(user_id) in editors

    def _is_owner(self, equipment, user_id: uuid.UUID) -> bool:
        return equipment.owner_id == user_id

    async def list_by_owner(
        self, session: AsyncSession, owner_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[EquipmentRead]:
        if await is_admin(session, owner_id):
            equipments = await self._repo.find_all(session, skip, limit)
        else:
            equipments = await self._repo.find_accessible_by_user(session, owner_id, skip, limit)
        return [EquipmentRead.model_validate(e) for e in equipments]

    async def create(
        self, session: AsyncSession, owner_id: uuid.UUID, data: EquipmentCreate
    ) -> EquipmentRead:
        equipment_id = uuid.uuid4()
        rel_path = self._storage.equipment_path(equipment_id)
        abs_path = self._storage.write_json(rel_path, {
            "equipment_name": data.equipment_name,
            "cluster_type": "single_cluster",
            "modules": [],
            "timetables": {},
        })
        owner_str = str(owner_id)
        equipment = await self._repo.create(session, {
            "equipment_id": equipment_id,
            "equipment_name": data.equipment_name,
            "equipment_configuration_file_path": abs_path,
            "owner_id": owner_id,
            "viewers": [owner_str],
            "editors": [owner_str],
            "save_status": "saved_temporarily",
        })
        return EquipmentRead.model_validate(equipment)

    async def get(
        self, session: AsyncSession, equipment_id: uuid.UUID, user_id: uuid.UUID
    ) -> EquipmentRead:
        equipment = await self._repo.find_by_id(session, equipment_id)
        if equipment is None:
            raise NotFoundError("Equipment", str(equipment_id))
        if not self._can_view(equipment, user_id) and not await is_admin(session, user_id):
            raise AuthorizationError()
        return EquipmentRead.model_validate(equipment)

    async def copy(
        self,
        session: AsyncSession,
        equipment_id: uuid.UUID,
        user_id: uuid.UUID,
        new_name: str,
    ) -> EquipmentRead:
        """Deep-copy an equipment: new modules + new process/flow recipes, fully
        independent from the source (no shared rows), owned by ``user_id``."""
        source = await self._repo.find_by_id(session, equipment_id)
        if source is None:
            raise NotFoundError("Equipment", str(equipment_id))
        if not self._can_view(source, user_id) and not await is_admin(session, user_id):
            raise AuthorizationError()

        src = self._storage.read_json(source.equipment_configuration_file_path)

        # 1) Duplicate modules (new rows). Sharing rows is unsafe: modules have a
        #    single equipment FK, so linking them to the copy would steal them
        #    from the source. old module_id (int) -> new module_id (int).
        mod_map: dict[int, int] = {}
        for m in src.get("modules", []):
            old_mid = m["module_id"]
            row = await self._module_repo.find_by_id(session, old_mid)
            if row is None:
                continue
            new_row = await self._module_repo.create(session, {
                "module_name": row.module_name,
                "module_type": row.module_type,
                "module_subtype": list(row.module_subtype or []),
                "save_status": row.save_status,
                "equipment_id": None,
            })
            mod_map[old_mid] = new_row.module_id

        def remap_mod(mid):
            try:
                return str(mod_map[int(mid)])
            except (ValueError, KeyError, TypeError):
                return mid

        # 2) Duplicate process recipes (remap module ids). old uuid str -> new uuid str.
        pr_map: dict[str, str] = {}
        for old_pr in src.get("process_recipe_ids", []):
            try:
                old_pr_uuid = uuid.UUID(old_pr)
            except (ValueError, TypeError):
                continue
            pr_row = await self._process_repo.find_by_id(session, old_pr_uuid)
            if pr_row is None:
                continue
            pr_cfg = self._storage.read_json(pr_row.process_recipe_path)
            pr_cfg["user_added_process_modules"] = [
                mod_map.get(mid, mid)
                for mid in pr_cfg.get("user_added_process_modules", [])
            ]
            new_pr_id = uuid.uuid4()
            new_pr_path = self._storage.write_json(
                self._storage.process_recipe_path(new_pr_id), pr_cfg)
            await self._process_repo.create(session, {
                "process_recipe_id": new_pr_id,
                "process_recipe_name": pr_row.process_recipe_name,
                "process_recipe_path": new_pr_path,
                "save_status": pr_row.save_status,
            })
            pr_map[old_pr] = str(new_pr_id)

        # 3) Duplicate flow recipes (remap process_recipe_steps + module_sequence).
        fr_new_ids: list[str] = []
        for old_fr in src.get("flow_recipe_ids", []):
            try:
                old_fr_uuid = uuid.UUID(old_fr)
            except (ValueError, TypeError):
                continue
            fr_row = await self._flow_repo.find_by_id(session, old_fr_uuid)
            if fr_row is None:
                continue
            fr_cfg = self._storage.read_json(fr_row.flow_recipe_path)
            for step in fr_cfg.get("process_recipe_steps", []):
                if step.get("process_recipe_id") in pr_map:
                    step["process_recipe_id"] = pr_map[step["process_recipe_id"]]
            fr_cfg["module_sequence"] = [
                [remap_mod(x) for x in step]
                for step in fr_cfg.get("module_sequence", [])
            ]
            new_fr_id = uuid.uuid4()
            new_fr_path = self._storage.write_json(
                self._storage.flow_recipe_path(new_fr_id), fr_cfg)
            await self._flow_repo.create(session, {
                "flow_recipe_id": new_fr_id,
                "flow_recipe_name": fr_row.flow_recipe_name,
                "flow_recipe_path": new_fr_path,
                "save_status": fr_row.save_status,
            })
            fr_new_ids.append(str(new_fr_id))

        # 4) New equipment config with remapped references.
        new_cfg = dict(src)
        new_cfg["equipment_name"] = new_name
        new_cfg["modules"] = [
            {**m, "module_id": mod_map.get(m["module_id"], m["module_id"])}
            for m in src.get("modules", [])
        ]
        new_cfg["process_recipe_ids"] = list(pr_map.values())
        new_cfg["flow_recipe_ids"] = fr_new_ids

        new_eq_id = uuid.uuid4()
        new_path = self._storage.write_json(
            self._storage.equipment_path(new_eq_id), new_cfg)
        owner_str = str(user_id)
        equipment = await self._repo.create(session, {
            "equipment_id": new_eq_id,
            "equipment_name": new_name,
            "equipment_configuration_file_path": new_path,
            "owner_id": user_id,
            "viewers": [owner_str],
            "editors": [owner_str],
            "save_status": source.save_status,
        })
        await self._module_repo.sync_equipment_link(
            session, new_eq_id, list(mod_map.values()))
        return EquipmentRead.model_validate(equipment)

    async def get_config(
        self, session: AsyncSession, equipment_id: uuid.UUID, user_id: uuid.UUID
    ) -> EquipmentConfig:
        equipment = await self._repo.find_by_id(session, equipment_id)
        if equipment is None:
            raise NotFoundError("Equipment", str(equipment_id))
        if not self._can_view(equipment, user_id) and not await is_admin(session, user_id):
            raise AuthorizationError()
        data = self._storage.read_json(equipment.equipment_configuration_file_path)
        return EquipmentConfig.model_validate(data)

    async def update_config(
        self,
        session: AsyncSession,
        equipment_id: uuid.UUID,
        user_id: uuid.UUID,
        config: EquipmentConfig,
    ) -> EquipmentConfig:
        equipment = await self._repo.find_by_id(session, equipment_id)
        if equipment is None:
            raise NotFoundError("Equipment", str(equipment_id))
        if not self._can_edit(equipment, user_id):
            raise AuthorizationError()
        self._storage.write_json(
            equipment.equipment_configuration_file_path, config.model_dump()
        )
        module_ids = [m.module_id for m in config.modules]
        await self._module_repo.sync_equipment_link(session, equipment_id, module_ids)
        return config

    async def update(
        self,
        session: AsyncSession,
        equipment_id: uuid.UUID,
        user_id: uuid.UUID,
        data: EquipmentUpdate,
    ) -> EquipmentRead:
        equipment = await self._repo.find_by_id(session, equipment_id)
        if equipment is None:
            raise NotFoundError("Equipment", str(equipment_id))
        if not self._can_edit(equipment, user_id):
            raise AuthorizationError()
        updated = await self._repo.update(
            session, equipment_id, data.model_dump(exclude_none=True)
        )
        return EquipmentRead.model_validate(updated)

    async def delete(
        self, session: AsyncSession, equipment_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        equipment = await self._repo.find_by_id(session, equipment_id)
        if equipment is None:
            raise NotFoundError("Equipment", str(equipment_id))
        if not self._is_owner(equipment, user_id):
            raise AuthorizationError("Only the owner can delete equipment")
        self._storage.delete(equipment.equipment_configuration_file_path)
        await self._repo.delete(session, equipment_id)

    async def add_viewer(
        self, session: AsyncSession, equipment_id: uuid.UUID, owner_id: uuid.UUID, viewer_id: str
    ) -> EquipmentRead:
        equipment = await self._repo.find_by_id(session, equipment_id)
        if equipment is None:
            raise NotFoundError("Equipment", str(equipment_id))
        if not self._is_owner(equipment, owner_id):
            raise AuthorizationError("Only the owner can manage viewers")
        new_viewers = [*(equipment.viewers or []), viewer_id] if viewer_id not in (equipment.viewers or []) else list(equipment.viewers)
        updated = await self._repo.update(session, equipment_id, {"viewers": new_viewers})
        return EquipmentRead.model_validate(updated)

    async def remove_viewer(
        self, session: AsyncSession, equipment_id: uuid.UUID, owner_id: uuid.UUID, viewer_id: str
    ) -> EquipmentRead:
        equipment = await self._repo.find_by_id(session, equipment_id)
        if equipment is None:
            raise NotFoundError("Equipment", str(equipment_id))
        if not self._is_owner(equipment, owner_id):
            raise AuthorizationError("Only the owner can manage viewers")
        new_viewers = [v for v in (equipment.viewers or []) if v != viewer_id]
        updated = await self._repo.update(session, equipment_id, {"viewers": new_viewers})
        return EquipmentRead.model_validate(updated)

    async def add_editor(
        self, session: AsyncSession, equipment_id: uuid.UUID, owner_id: uuid.UUID, editor_id: str
    ) -> EquipmentRead:
        equipment = await self._repo.find_by_id(session, equipment_id)
        if equipment is None:
            raise NotFoundError("Equipment", str(equipment_id))
        if not self._is_owner(equipment, owner_id):
            raise AuthorizationError("Only the owner can manage editors")
        new_editors = [*(equipment.editors or []), editor_id] if editor_id not in (equipment.editors or []) else list(equipment.editors)
        updated = await self._repo.update(session, equipment_id, {"editors": new_editors})
        return EquipmentRead.model_validate(updated)

    async def remove_editor(
        self, session: AsyncSession, equipment_id: uuid.UUID, owner_id: uuid.UUID, editor_id: str
    ) -> EquipmentRead:
        equipment = await self._repo.find_by_id(session, equipment_id)
        if equipment is None:
            raise NotFoundError("Equipment", str(equipment_id))
        if not self._is_owner(equipment, owner_id):
            raise AuthorizationError("Only the owner can manage editors")
        new_editors = [e for e in (equipment.editors or []) if e != editor_id]
        updated = await self._repo.update(session, equipment_id, {"editors": new_editors})
        return EquipmentRead.model_validate(updated)
