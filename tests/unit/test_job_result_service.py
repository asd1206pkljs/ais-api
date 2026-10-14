import json

import pytest

from app.exceptions import NotFoundError, ValidationError
from app.services import job_result_service as jrs


@pytest.fixture
def bundle(tmp_path):
    (tmp_path / "summary.csv").write_text(
        "filename,steps,rewards,score\n/a/b/ep1.csv,10,1.5,\n/a/b/ep2.csv,5,0.5,2\n"
    )
    logs = tmp_path / "eqp_logs"
    logs.mkdir()
    (logs / "ep1.csv").write_text("module,start_time,end_time,lot_id,wafer_id\nrobot0,0,1.5,,2\npm0,1.5,4,1,\n")
    (logs / "ep2.csv").write_text("module,start_time,end_time\nrobot0,0,1\n")
    (tmp_path / "gantt_config.json").write_text(json.dumps({"visible": ["robot0"], "hidden": []}))
    return str(tmp_path)


def test_summary_adjusts_rewards_and_shortens_filename(bundle):
    rows = jrs.get_summary(bundle)
    assert rows[0]["filename_short"] == "ep1" and rows[0]["adj_rewards"] == 1.5
    assert rows[1]["adj_rewards"] == 0 and rows[0]["score"] == 0  # NaN → 0


def test_summary_requires_path_and_file(tmp_path):
    with pytest.raises(NotFoundError):
        jrs.get_summary(None)
    with pytest.raises(NotFoundError):
        jrs.get_summary(str(tmp_path))


def test_episodes_and_gantt_config(bundle, tmp_path):
    assert jrs.list_episodes(bundle) == ["ep1", "ep2"]
    assert jrs.list_episodes(str(tmp_path / "nowhere")) == []
    assert jrs.get_gantt_config(bundle) == {"visible": ["robot0"], "hidden": []}
    assert jrs.get_gantt_config(str(tmp_path / "nowhere")) == {}
    (tmp_path / "gantt_config.json").write_text("not json")
    assert jrs.get_gantt_config(bundle) == {}
    (tmp_path / "gantt_config.json").write_text("[1, 2]")
    assert jrs.get_gantt_config(bundle) == {}


def test_episode_logs(bundle):
    rows = jrs.get_episode_logs(bundle, "ep1")
    assert rows[0]["duration"] == 1.5 and rows[0]["lot_id"] == -1 and rows[0]["wafer_id"] == 2
    assert rows[1]["lot_id"] == 1 and rows[1]["wafer_id"] == -1
    rows = jrs.get_episode_logs(bundle, " ep2 ")
    assert rows[0]["duration"] == 1.0 and "lot_id" not in rows[0]
    with pytest.raises(NotFoundError):
        jrs.get_episode_logs(bundle, "ep9")
    for bad in ("", "../x", "a/b", "a\\b"):
        with pytest.raises(ValidationError):
            jrs.get_episode_logs(bundle, bad)
