"""Encrypt legacy plaintext config files in place, or re-wrap encrypted files
onto the active DATA_ENCRYPTION_KEY after a key rotation.

    python -m app.tasks.encrypt_files [--dry-run]           # plaintext → encrypted
    python -m app.tasks.encrypt_files --rewrap [--dry-run]  # old KEK → active KEK

Idempotent; prints a JSON report. Run once after deploying the multi-user
security release, then set ALLOW_PLAINTEXT_FILES=false.
"""
import argparse
import asyncio
import json
from dataclasses import asdict, dataclass, field

from app.services.file_storage_service import FileStorageService, file_storage


@dataclass
class EncryptReport:
    scanned: int = 0
    encrypted: int = 0
    rewrapped: int = 0
    already_current: int = 0
    failed: list[str] = field(default_factory=list)
    dry_run: bool = False


def run(storage: FileStorageService = file_storage, *, rewrap: bool = False, dry_run: bool = False) -> EncryptReport:
    report = EncryptReport(dry_run=dry_run)
    for path in storage.iter_config_files():
        report.scanned += 1
        file_path = str(path)
        try:
            encrypted = storage.is_encrypted_file(file_path)
            if not encrypted:
                if not dry_run:
                    storage.encrypt_in_place(file_path)
                report.encrypted += 1
            elif rewrap:
                if dry_run:
                    changed = storage.cipher.key_id_of(path.read_bytes()) != storage.cipher._ring.active_kid
                else:
                    changed = storage.rewrap_in_place(file_path)
                report.rewrapped += int(changed)
                report.already_current += int(not changed)
            else:
                report.already_current += 1
        except Exception as e:  # noqa: BLE001 - keep going, report at the end
            report.failed.append(f"{file_path}: {e}")
    return report


async def _main(args: argparse.Namespace) -> None:
    report = run(rewrap=args.rewrap, dry_run=args.dry_run)
    print(json.dumps(asdict(report), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rewrap", action="store_true", help="re-wrap onto the active key after rotation")
    asyncio.run(_main(parser.parse_args()))
