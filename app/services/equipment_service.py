import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ResourceType, SharePermission
from app.enums import audit_action as act
from app.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.models.equipment import Equipment
from app.repositories.equipment_repository import EquipmentRepository
from app.repositories.flow_recipe_repository import FlowRecipeRepository
from app.repositories.module_repository import ModuleRepository
from app.repositories.process_recipe_repository import ProcessRecipeRepository
from app.schemas.equipment import EquipmentCreate, EquipmentRead, EquipmentUpdate
from app.schemas.equipment_config import EquipmentConfig
from app.services.access import AccessPolicy, access_policy
from app.services.audit_service import AuditService, audit
from app.services.file_storage_service import FileStorageService, file_storage
from app.services.sharing_service import SharingService

RTYPE = ResourceType.EQUIPMENT.value


def _uuids(values: list) -> list[uuid.UUID]:
    out = []
    for v in values:
        try:
            out.append(uuid.UUID(str(v)))
        except (ValueError, TypeError):
            continue
    return out


class EquipmentService:
    def __init__(
        self,
        repo: EquipmentRepository,
        storage: FileStorageService = file_storage,
        module_repo: ModuleRepository | None = None,
        process_recipe_repo: ProcessRecipeRepository | None = None,
        flow_recipe_repo: FlowRecipeRepository | None = None,
        access: AccessPolicy = access_policy,
        sharing: SharingService | None = None,
        audit_svc: AuditService = audit,
    ):
        self._repo = repo
        self._storage = storage
        self._module_repo = module_repo or ModuleRepository()
        self._process_repo = process_recipe_repo or ProcessRecipeRepository()
        self._flow_repo = flow_recipe_repo or FlowRecipeRepository()
        self._access = access
        self._sharing = sharing or SharingService(access=access, audit_svc=audit_svc)
        self._audit = audit_svc

    # --- helpers ---------------------------------------------------------------

    async def _load(self, session: AsyncSession, equipment_id: uuid.UUID) -> Equipment:
        equipment = await self._repo.find_by_id(session, equipment_id)
        if equipment is None or equipment.save_status == "deleted":
            raise NotFoundError("Equipment", str(equipment_id))
        return equipment

    async def _can_view(self, session, equipment, user_id) -> bool:
        return await self._access.can_view(session, RTYPE, equipment.equipment_id, equipment.owner_id, user_id)

    async def _can_edit(self, session, equipment, user_id) -> bool:
        return await self._access.can_edit(session, RTYPE, equipment.equipment_id, equipment.owner_id, user_id)

    async def _reads(
        self, session: AsyncSession, rows: list[Equipment], viewer_id: uuid.UUID | None = None
    ) -> list[EquipmentRead]:
        lists = await self._sharing.access_lists(
            session, RTYPE, [str(e.equipment_id) for e in rows],
            viewer_id=viewer_id, owners={str(e.equipment_id): e.owner_id for e in rows},
        )
        out = []
        for e in rows:
            viewers, editors = lists.get(str(e.equipment_id), ([], []))
            read = EquipmentRead.model_validate(e)
            out.append(read.model_copy(update={"viewers": viewers, "editors": editors}))
        return out

    async def _read(
        self, session: AsyncSession, row: Equipment, viewer_id: uuid.UUID | None = None
    ) -> EquipmentRead:
        (read,) = await self._reads(session, [row], viewer_id)
        return read

    async def _authorize_children(
        self, session: AsyncSession, equipment: Equipment, cfg: dict, user_id: uuid.UUID
    ) -> None:
        """Every recipe/module a config references must be one the caller may
        edit. Otherwise an editor could link a stranger's rows into their
        equipment and inherit access to them. Unowned legacy rows and rows
        already attached to this equipment are accepted."""
        checks = (
            (ResourceType.FLOW_RECIPE.value, "flow_recipe_id",
             await self._flow_repo.find_by_ids(session, _uuids(cfg.get("flow_recipe_ids", [])))),
            (ResourceType.PROCESS_RECIPE.value, "process_recipe_id",
             await self._process_repo.find_by_ids(session, _uuids(cfg.get("process_recipe_ids", [])))),
            (ResourceType.MODULE.value, "module_id",
             await self._module_repo.find_by_ids(
                 session, [m["module_id"] for m in cfg.get("modules", []) if isinstance(m.get("module_id"), int)])),
        )
        for rtype, id_attr, rows in checks:
            for row in rows:
                if row.owner_id in (None, user_id, equipment.owner_id) or row.equipment_id == equipment.equipment_id:
                    continue
                if not await self._access.can_edit_linked(
                    session, rtype, getattr(row, id_attr), row.owner_id, row.equipment_id, user_id
                ):
                    # Same wording as a missing row: do not confirm that it exists.
                    raise ValidationError(f"{rtype} '{getattr(row, id_attr)}' not found")

    async def _link_children(
        self, session: AsyncSession, equipment: Equipment, config: dict | EquipmentConfig
    ) -> None:
        """Attach the modules/recipes a config references to the equipment so
        their access follows the equipment's; unowned legacy rows get its owner.
        Callers run _authorize_children first."""
        cfg = config.model_dump() if isinstance(config, EquipmentConfig) else config
        module_ids = [m["module_id"] for m in cfg.get("modules", [])]
        await self._flow_repo.sync_equipment_link(
            session, equipment.equipment_id, _uuids(cfg.get("flow_recipe_ids", [])), equipment.owner_id)
        await self._process_repo.sync_equipment_link(
            session, equipment.equipment_id, _uuids(cfg.get("process_recipe_ids", [])), equipment.owner_id)
        await self._module_repo.sync_equipment_link(
            session, equipment.equipment_id, module_ids, equipment.owner_id)  # commits

    async def _viewable(self, session: AsyncSession, rtype: str, id_attr: str, row, user_id: uuid.UUID) -> bool:
        return await self._access.can_view_linked(
            session, rtype, getattr(row, id_attr), row.owner_id, row.equipment_id, user_id)

    # --- CRUD ------------------------------------------------------------------

    async def list_by_owner(
        self, session: AsyncSession, owner_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[EquipmentRead]:
        """Admins see every equipment's metadata (console); users see what they
        own or were granted, directly or through a group."""
        if await self._access.is_admin(session, owner_id):
            equipments = await self._repo.find_all(session, skip, limit)
        else:
            principals = await self._access.principals(session, owner_id)
            equipments = await self._repo.find_accessible_by_user(session, owner_id, principals, skip, limit)
        return await self._reads(session, equipments, owner_id)

    async def create(self, session: AsyncSession, owner_id: uuid.UUID, data: EquipmentCreate) -> EquipmentRead:
        equipment_id = uuid.uuid4()
        rel_path = self._storage.equipment_path(equipment_id)
        abs_path = self._storage.write_json(rel_path, {
            "equipment_name": data.equipment_name,
            "cluster_type": "single_cluster",
            "modules": [],
            "timetables": {},
        })
        equipment = await self._repo.create(session, {
            "equipment_id": equipment_id,
            "equipment_name": data.equipment_name,
            "equipment_configuration_file_path": abs_path,
            "owner_id": owner_id,
            "save_status": "saved_temporarily",
        })
        await self._audit.record(session, act.RESOURCE_CREATED, resource_type=RTYPE, resource_id=equipment_id,
                                 details={"name": data.equipment_name})
        return await self._read(session, equipment, owner_id)

    async def get(self, session: AsyncSession, equipment_id: uuid.UUID, user_id: uuid.UUID) -> EquipmentRead:
        """Metadata only; admins may read it for the console."""
        equipment = await self._load(session, equipment_id)
        if not await self._can_view(session, equipment, user_id) and not await self._access.is_admin(session, user_id):
            raise AuthorizationError()
        return await self._read(session, equipment, user_id)

    async def copy(
        self, session: AsyncSession, equipment_id: uuid.UUID, user_id: uuid.UUID, new_name: str
    ) -> EquipmentRead:
        """Deep-copy an equipment: new modules + new process/flow recipes, fully
        independent from the source, owned by ``user_id``. Requires view access
        (copying reads the content, so there is no admin bypass)."""
        source = await self._load(session, equipment_id)
        if not await self._can_view(session, source, user_id):
            raise AuthorizationError()

        src = self._storage.read_json(source.equipment_configuration_file_path)

        # 1) Duplicate modules (new rows, owned by the copier). old id -> new id.
        mod_map: dict[int, int] = {}
        for m in src.get("modules", []):
            old_mid = m["module_id"]
            row = await self._module_repo.find_by_id(session, old_mid)
            if row is None or not await self._viewable(session, ResourceType.MODULE.value, "module_id", row, user_id):
                continue
            new_row = await self._module_repo.create(session, {
                "module_name": row.module_name,
                "module_type": row.module_type,
                "module_subtype": list(row.module_subtype or []),
                "save_status": row.save_status,
                "equipment_id": None,
                "owner_id": user_id,
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
            if pr_row is None or not await self._viewable(
                session, ResourceType.PROCESS_RECIPE.value, "process_recipe_id", pr_row, user_id
            ):
                continue
            pr_cfg = self._storage.read_json(pr_row.process_recipe_path)
            pr_cfg["user_added_process_modules"] = [
                mod_map.get(mid, mid) for mid in pr_cfg.get("user_added_process_modules", [])
            ]
            new_pr_id = uuid.uuid4()
            new_pr_path = self._storage.write_json(self._storage.process_recipe_path(new_pr_id), pr_cfg)
            await self._process_repo.create(session, {
                "process_recipe_id": new_pr_id,
                "process_recipe_name": pr_row.process_recipe_name,
                "process_recipe_path": new_pr_path,
                "save_status": pr_row.save_status,
                "owner_id": user_id,
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
            if fr_row is None or not await self._viewable(
                session, ResourceType.FLOW_RECIPE.value, "flow_recipe_id", fr_row, user_id
            ):
                continue
            fr_cfg = self._storage.read_json(fr_row.flow_recipe_path)
            for step in fr_cfg.get("process_recipe_steps", []):
                if step.get("process_recipe_id") in pr_map:
                    step["process_recipe_id"] = pr_map[step["process_recipe_id"]]
            fr_cfg["module_sequence"] = [
                [remap_mod(x) for x in step] for step in fr_cfg.get("module_sequence", [])
            ]
            new_fr_id = uuid.uuid4()
            new_fr_path = self._storage.write_json(self._storage.flow_recipe_path(new_fr_id), fr_cfg)
            await self._flow_repo.create(session, {
                "flow_recipe_id": new_fr_id,
                "flow_recipe_name": fr_row.flow_recipe_name,
                "flow_recipe_path": new_fr_path,
                "save_status": fr_row.save_status,
                "owner_id": user_id,
            })
            fr_new_ids.append(str(new_fr_id))

        # 4) New equipment config with remapped references.
        new_cfg = dict(src)
        new_cfg["equipment_name"] = new_name
        new_cfg["modules"] = [
            {**m, "module_id": mod_map.get(m["module_id"], m["module_id"])} for m in src.get("modules", [])
        ]
        new_cfg["process_recipe_ids"] = list(pr_map.values())
        new_cfg["flow_recipe_ids"] = fr_new_ids

        new_eq_id = uuid.uuid4()
        new_path = self._storage.write_json(self._storage.equipment_path(new_eq_id), new_cfg)
        equipment = await self._repo.create(session, {
            "equipment_id": new_eq_id,
            "equipment_name": new_name,
            "equipment_configuration_file_path": new_path,
            "owner_id": user_id,
            "save_status": source.save_status,
        })
        await self._link_children(session, equipment, new_cfg)
        await self._audit.record(session, act.RESOURCE_COPIED, resource_type=RTYPE, resource_id=new_eq_id,
                                 details={"source": str(equipment_id)})
        return await self._read(session, equipment, user_id)

    async def get_config(self, session: AsyncSession, equipment_id: uuid.UUID, user_id: uuid.UUID) -> EquipmentConfig:
        equipment = await self._load(session, equipment_id)
        if not await self._can_view(session, equipment, user_id):
            raise AuthorizationError()
        data = self._storage.read_json(equipment.equipment_configuration_file_path)
        await self._audit.record(session, act.RESOURCE_READ, resource_type=RTYPE, resource_id=equipment_id,
                                 details={"part": "config"})
        return EquipmentConfig.model_validate(data)

    async def update_config(
        self, session: AsyncSession, equipment_id: uuid.UUID, user_id: uuid.UUID, config: EquipmentConfig
    ) -> EquipmentConfig:
        equipment = await self._load(session, equipment_id)
        if not await self._can_edit(session, equipment, user_id):
            raise AuthorizationError()
        await self._authorize_children(session, equipment, config.model_dump(), user_id)
        self._storage.write_json(equipment.equipment_configuration_file_path, config.model_dump())
        await self._link_children(session, equipment, config)
        await self._audit.record(session, act.RESOURCE_UPDATED, resource_type=RTYPE, resource_id=equipment_id,
                                 details={"part": "config"})
        return config

    async def update(
        self, session: AsyncSession, equipment_id: uuid.UUID, user_id: uuid.UUID, data: EquipmentUpdate
    ) -> EquipmentRead:
        equipment = await self._load(session, equipment_id)
        if not await self._can_edit(session, equipment, user_id):
            raise AuthorizationError()
        changes = data.model_dump(exclude_none=True)
        updated = await self._repo.update(session, equipment_id, changes)
        await self._audit.record(session, act.RESOURCE_UPDATED, resource_type=RTYPE, resource_id=equipment_id,
                                 details=changes)
        return await self._read(session, updated, user_id)

    async def delete(self, session: AsyncSession, equipment_id: uuid.UUID, user_id: uuid.UUID) -> None:
        equipment = await self._load(session, equipment_id)
        if not self._access.is_owner(equipment.owner_id, user_id):
            raise AuthorizationError("Only the owner can delete equipment")
        self._storage.delete(equipment.equipment_configuration_file_path)
        await self._sharing.delete_for_resource(session, RTYPE, equipment_id)
        await self._repo.delete(session, equipment_id)
        await self._audit.record(session, act.RESOURCE_DELETED, resource_type=RTYPE, resource_id=equipment_id)

    # --- legacy sharing endpoints (POST/DELETE .../viewers|editors) ------------------

    async def add_viewer(self, session, equipment_id, owner_id, viewer_id: str) -> EquipmentRead:
        await self._sharing.grant_legacy(session, RTYPE, str(equipment_id), owner_id, viewer_id, SharePermission.VIEW)
        return await self._read(session, await self._load(session, equipment_id), owner_id)

    async def remove_viewer(self, session, equipment_id, owner_id, viewer_id: str) -> EquipmentRead:
        await self._sharing.revoke_legacy(session, RTYPE, str(equipment_id), owner_id, viewer_id, SharePermission.VIEW)
        return await self._read(session, await self._load(session, equipment_id), owner_id)

    async def add_editor(self, session, equipment_id, owner_id, editor_id: str) -> EquipmentRead:
        await self._sharing.grant_legacy(session, RTYPE, str(equipment_id), owner_id, editor_id, SharePermission.EDIT)
        return await self._read(session, await self._load(session, equipment_id), owner_id)

    async def remove_editor(self, session, equipment_id, owner_id, editor_id: str) -> EquipmentRead:
        await self._sharing.revoke_legacy(session, RTYPE, str(equipment_id), owner_id, editor_id, SharePermission.EDIT)
        return await self._read(session, await self._load(session, equipment_id), owner_id)
