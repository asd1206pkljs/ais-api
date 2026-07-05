import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AuthorizationError, NotFoundError
from app.repositories.equipment_repository import EquipmentRepository
from app.repositories.module_repository import ModuleRepository
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
    ):
        self._repo = repo
        self._storage = storage
        self._module_repo = module_repo or ModuleRepository()

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
