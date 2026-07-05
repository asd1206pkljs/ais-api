import json
import uuid
from pathlib import Path

from app.config import settings


class FileStorageService:
    def __init__(self, base_path: str | None = None):
        self._base = Path(base_path or settings.FILE_STORAGE_BASE_PATH)

    def _ensure_dir(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

    def write_json(self, relative_path: str, data: dict) -> str:
        full_path = self._base / relative_path
        self._ensure_dir(full_path)
        full_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return str(full_path)

    def read_json(self, file_path: str) -> dict:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def delete(self, file_path: str) -> None:
        path = Path(file_path)
        if path.exists():
            path.unlink()

    def equipment_path(self, equipment_id: uuid.UUID) -> str:
        return f"equipment/{equipment_id}/config.json"

    def flow_recipe_path(self, recipe_id: uuid.UUID) -> str:
        return f"flow_recipes/{recipe_id}/config.json"

    def process_recipe_path(self, recipe_id: uuid.UUID) -> str:
        return f"process_recipes/{recipe_id}/config.json"

    def simulator_path(self, simulator_id: uuid.UUID) -> str:
        return f"simulators/{simulator_id}/config.json"

    def job_result_dir(self, job_id: int, base_path: str | None = None) -> str:
        """Create (if missing) and return the absolute training-result directory for a job."""
        base = Path(base_path or settings.TRAIN_RESULTS_BASE_PATH)
        target = base / str(job_id)
        target.mkdir(parents=True, exist_ok=True)
        return str(target)


file_storage = FileStorageService()
