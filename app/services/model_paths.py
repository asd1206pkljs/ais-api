"""Filesystem-safe names for generated eqp_model directories.

Equipment names come from user-controlled config, so they are reduced to a
safe character set and the final path is checked to stay under its base.
"""
import re
from pathlib import Path

from app.exceptions import ValidationError

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_LEN = 100


def safe_model_name(raw: str, fallback: str) -> str:
    name = _SAFE.sub("_", (raw or "").strip()).strip("._") or fallback
    return name[:_MAX_LEN]


def model_output_dir(base: Path, name: str) -> str:
    target = (base / name).resolve()
    if base.resolve() not in target.parents:
        raise ValidationError("Invalid equipment name for model generation")
    return str(target)
