"""Link legacy recipes/modules to the equipment that references them and give
them that equipment's owner (data migration for the multi-user permission model).

    python -m app.tasks.migrate_ownership [--dry-run] [--assign-orphans-to EMAIL]

Prints a JSON report (equipment scanned, rows linked, remaining orphans) that
doubles as the data-migration evidence. Safe to re-run.
"""
import argparse
import asyncio
import json
import uuid
from dataclasses import asdict, dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.equipment_repository import EquipmentRepository
from app.repositories.flow_recipe_repository import FlowRecipeRepository
from app.repositories.module_repository import ModuleRepository
from app.repositories.process_recipe_repository import ProcessRecipeRepository
from app.repositories.user_repository import UserRepository
from app.services.file_storage_service import FileStorageService, file_storage


@dataclass
class OwnershipReport:
    equipment_scanned: int = 0
    equipment_unreadable: list[str] = field(default_factory=list)
    flow_recipes_linked: int = 0
    process_recipes_linked: int = 0
    modules_linked: int = 0
    orphan_flow_recipes: list[str] = field(default_factory=list)
    orphan_process_recipes: list[str] = field(default_factory=list)
    orphan_modules: list[int] = field(default_factory=list)
    orphans_assigned_to: str | None = None
    dry_run: bool = False


def _uuids(values: list) -> list[uuid.UUID]:
    out = []
    for v in values or []:
        try:
            out.append(uuid.UUID(str(v)))
        except (ValueError, TypeError):
            continue
    return out


class OwnershipMigration:
    def __init__(
        self,
        storage: FileStorageService = file_storage,
        equipment_repo: EquipmentRepository | None = None,
        flow_repo: FlowRecipeRepository | None = None,
        process_repo: ProcessRecipeRepository | None = None,
        module_repo: ModuleRepository | None = None,
        user_repo: UserRepository | None = None,
    ):
        self._storage = storage
        self._equipment = equipment_repo or EquipmentRepository()
        self._flows = flow_repo or FlowRecipeRepository()
        self._processes = process_repo or ProcessRecipeRepository()
        self._modules = module_repo or ModuleRepository()
        self._users = user_repo or UserRepository()

    async def run(
        self, session: AsyncSession, *, dry_run: bool = False, assign_orphans_to: str | None = None
    ) -> OwnershipReport:
        report = OwnershipReport(dry_run=dry_run)
        skip = 0
        while True:
            batch = await self._equipment.find_all(session, skip, 200)
            if not batch:
                break
            for equipment in batch:
                report.equipment_scanned += 1
                try:
                    cfg = self._storage.read_json(equipment.equipment_configuration_file_path)
                except Exception:  # noqa: BLE001 - reported, not fatal
                    report.equipment_unreadable.append(str(equipment.equipment_id))
                    continue
                flow_ids = _uuids(cfg.get("flow_recipe_ids", []))
                process_ids = _uuids(cfg.get("process_recipe_ids", []))
                module_ids = [m["module_id"] for m in cfg.get("modules", []) if "module_id" in m]
                report.flow_recipes_linked += len(flow_ids)
                report.process_recipes_linked += len(process_ids)
                report.modules_linked += len(module_ids)
                if dry_run:
                    continue
                await self._flows.sync_equipment_link(session, equipment.equipment_id, flow_ids, equipment.owner_id)
                await self._processes.sync_equipment_link(
                    session, equipment.equipment_id, process_ids, equipment.owner_id)
                await self._modules.sync_equipment_link(
                    session, equipment.equipment_id, module_ids, equipment.owner_id)  # commits
            skip += len(batch)
        if not dry_run:
            await session.commit()

        report.orphan_flow_recipes = [str(r.flow_recipe_id) for r in await self._flows.find_unowned(session)]
        report.orphan_process_recipes = [str(r.process_recipe_id) for r in await self._processes.find_unowned(session)]
        report.orphan_modules = [m.module_id for m in await self._modules.find_unowned(session)]

        if assign_orphans_to and not dry_run:
            owner = await self._users.find_by_email(session, assign_orphans_to.strip().lower())
            if owner is None:
                raise SystemExit(f"No verified account for {assign_orphans_to}")
            for r in await self._flows.find_unowned(session):
                r.owner_id = owner.user_id
            for r in await self._processes.find_unowned(session):
                r.owner_id = owner.user_id
            for m in await self._modules.find_unowned(session):
                m.owner_id = owner.user_id
            await session.commit()
            report.orphans_assigned_to = owner.user_email
        return report


async def _main(args: argparse.Namespace) -> None:
    from app.database import async_session_factory, engine

    async with async_session_factory() as session:
        report = await OwnershipMigration().run(
            session, dry_run=args.dry_run, assign_orphans_to=args.assign_orphans_to
        )
    await engine.dispose()
    print(json.dumps(asdict(report), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="report only, change nothing")
    parser.add_argument("--assign-orphans-to", metavar="EMAIL",
                        help="give recipes/modules no equipment references to this account")
    asyncio.run(_main(parser.parse_args()))
