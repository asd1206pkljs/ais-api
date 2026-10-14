import json
import logging
import uuid
from pathlib import Path

from app.config import settings
from app.services.crypto import DataEncryptionError, EnvelopeCipher, cipher_from_settings, is_encrypted

logger = logging.getLogger(__name__)


class FileStorageService:
    """JSON config storage. Files are encrypted at rest (see app.services.crypto)
    unless ENCRYPT_DATA_AT_REST is off; legacy plaintext files are still read
    while ALLOW_PLAINTEXT_FILES is on so a deployment can migrate gradually."""

    def __init__(
        self,
        base_path: str | None = None,
        cipher: EnvelopeCipher | None = None,
        *,
        encrypt: bool | None = None,
        allow_plaintext: bool | None = None,
    ):
        self._base = Path(base_path or settings.FILE_STORAGE_BASE_PATH)
        self._cipher = cipher
        self._encrypt = settings.ENCRYPT_DATA_AT_REST if encrypt is None else encrypt
        self._allow_plaintext = (
            settings.ALLOW_PLAINTEXT_FILES if allow_plaintext is None else allow_plaintext
        )

    @property
    def cipher(self) -> EnvelopeCipher:
        if self._cipher is None:
            self._cipher = cipher_from_settings()
        return self._cipher

    def _ensure_dir(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _context(path: Path) -> bytes:
        """AAD binding a blob to its place in storage (<kind>/<id>/config.json)."""
        return "/".join(path.parts[-3:]).encode("utf-8")

    def _encode(self, data: dict, path: Path) -> bytes:
        payload = json.dumps(data, indent=2).encode("utf-8")
        return self.cipher.encrypt(payload, self._context(path)) if self._encrypt else payload

    def _decode(self, raw: bytes, path: Path) -> dict:
        if is_encrypted(raw):
            return json.loads(self.cipher.decrypt(raw, self._context(path)).decode("utf-8"))
        if not self._allow_plaintext:
            raise DataEncryptionError("Refusing to read a plaintext config file")
        return json.loads(raw.decode("utf-8"))

    def write_json(self, relative_path: str, data: dict) -> str:
        full_path = self._base / relative_path
        self._ensure_dir(full_path)
        full_path.write_bytes(self._encode(data, full_path))
        return str(full_path)

    def read_json(self, file_path: str) -> dict:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        return self._decode(path.read_bytes(), path)

    def delete(self, file_path: str) -> None:
        path = Path(file_path)
        if path.exists():
            path.unlink()

    def is_encrypted_file(self, file_path: str) -> bool:
        return is_encrypted(Path(file_path).read_bytes())

    def encrypt_in_place(self, file_path: str) -> bool:
        """Encrypt a legacy plaintext file. Returns False if already encrypted."""
        path = Path(file_path)
        raw = path.read_bytes()
        if is_encrypted(raw):
            return False
        data = json.loads(raw.decode("utf-8"))
        path.write_bytes(self.cipher.encrypt(json.dumps(data, indent=2).encode("utf-8"), self._context(path)))
        return True

    def rewrap_in_place(self, file_path: str) -> bool:
        """Move an encrypted file onto the active key. Returns False if unchanged."""
        path = Path(file_path)
        raw = path.read_bytes()
        if not is_encrypted(raw):
            return False
        rewrapped = self.cipher.rewrap(raw, self._context(path))
        if rewrapped is raw:
            return False
        path.write_bytes(rewrapped)
        return True

    def iter_config_files(self):
        """Every config file under the storage root (for migration tasks)."""
        if not self._base.exists():
            return
        for sub in ("equipment", "simulators", "flow_recipes", "process_recipes"):
            yield from sorted((self._base / sub).glob("*/config.json"))

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
