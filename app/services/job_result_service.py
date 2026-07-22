"""Read a job's training-result bundle (summary.csv + eqp_logs/*.csv) from its
result_path and shape it for the ais-web result viewer (gantt + scatter).

The bundle is written into the job's result_path by exp-web's Report feature.
This service only reads; it mirrors exp-web's CSV transformations so the
frontend charts consume an identical shape.
"""
import json
import os
from pathlib import Path

import pandas as pd

from app.exceptions import NotFoundError, ValidationError


def _bundle_dir(result_path: str | None) -> Path:
    if not result_path:
        raise NotFoundError("JobResult", "result_path not set")
    return Path(result_path)


def _safe_episode_name(ep_name: str) -> str:
    """Reject path separators / traversal so ep_name can't escape eqp_logs/."""
    name = ep_name.strip()
    if not name or "/" in name or "\\" in name or ".." in name:
        raise ValidationError("Invalid episode name")
    return name


def get_summary(result_path: str | None) -> list[dict]:
    """Parse summary.csv into scatter-plot records (mirrors exp-web /summary)."""
    path = _bundle_dir(result_path) / "summary.csv"
    if not path.exists():
        raise NotFoundError("JobResult", "summary.csv not found")
    df = pd.read_csv(path)
    if "steps" in df.columns and "rewards" in df.columns:
        max_steps = df["steps"].max()
        df["adj_rewards"] = df.apply(
            lambda row: row["rewards"] if row["steps"] >= max_steps else 0, axis=1
        )
    if "filename" in df.columns:
        df["filename_short"] = df["filename"].apply(
            lambda f: os.path.splitext(os.path.basename(str(f)))[0]
        )
    return df.fillna(0).to_dict(orient="records")


def list_episodes(result_path: str | None) -> list[str]:
    """Episode names (basenames) available in the bundle's eqp_logs/ dir."""
    eqp_dir = _bundle_dir(result_path) / "eqp_logs"
    if not eqp_dir.is_dir():
        return []
    return sorted(p.stem for p in eqp_dir.glob("*.csv"))


def get_gantt_config(result_path: str | None) -> dict:
    """exp-web's saved gantt y-axis config (gantt_config.json), {} if absent.

    exp-web writes {"visible": [...], "hidden": [...]} into the experiment dir
    (= the job's result_path), so serving it verbatim lets ais-web reuse the
    row order/visibility configured in exp-web.
    """
    path = _bundle_dir(result_path) / "gantt_config.json"
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def get_episode_logs(result_path: str | None, ep_name: str) -> list[dict]:
    """Parse eqp_logs/{ep}.csv into gantt bars (mirrors exp-web /logs)."""
    name = _safe_episode_name(ep_name)
    path = _bundle_dir(result_path) / "eqp_logs" / f"{name}.csv"
    if not path.exists():
        raise NotFoundError("JobResult", f"episode log not found: {name}")
    df = pd.read_csv(path)
    df["start_time"] = df["start_time"].astype(float)
    df["end_time"] = df["end_time"].astype(float)
    df["duration"] = df["end_time"] - df["start_time"]
    if "lot_id" in df.columns:
        df.loc[df.lot_id.isna(), "lot_id"] = -1
        df["lot_id"] = df["lot_id"].astype(int)
    if "wafer_id" in df.columns:
        df.loc[df.wafer_id.isna(), "wafer_id"] = -1
        df["wafer_id"] = df["wafer_id"].astype(int)
    return df.fillna("").to_dict(orient="records")
