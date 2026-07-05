"""Unit tests for EqpModelGenerator loadlock direction logic."""

import pytest

from app.services.eqp_model_service import EqpModelGenerator


def _make_equipment_config(modules: list[dict]) -> dict:
    return {
        "equipment_name": "test_eqp",
        "cluster_type": "single_cluster",
        "modules": modules,
        "timetables": {},
    }


def _base_modules():
    """기본 모듈 구성: loadport(efem), loadlock(efem+vacuum), process_module(vacuum), robot x2."""
    return [
        {"module_id": 1, "module_type": "loadport", "cluster": ["efem"]},
        {"module_id": 2, "module_type": "loadlock", "cluster": ["efem", "vacuum_cluster_1"]},
        {"module_id": 3, "module_type": "process_module", "cluster": ["vacuum_cluster_1"]},
        {"module_id": 4, "module_type": "robot", "cluster": ["efem"]},
        {"module_id": 5, "module_type": "robot", "cluster": ["vacuum_cluster_1"]},
    ]


@pytest.fixture
def generator():
    cfg = _make_equipment_config(_base_modules())
    return EqpModelGenerator(cfg, [], [])


class TestAllLoadlockNames:
    def test_returns_inslot_and_outslot(self, generator):
        names = generator._all_loadlock_names([2])
        assert "loadlock_inslot0" in names
        assert "loadlock_outslot0" in names

    def test_ignores_non_loadlock(self, generator):
        names = generator._all_loadlock_names([1])
        assert names == []

    def test_multiple_loadlocks(self):
        modules = _base_modules() + [
            {"module_id": 6, "module_type": "loadlock", "cluster": ["efem", "vacuum_cluster_1"]},
        ]
        gen = EqpModelGenerator(_make_equipment_config(modules), [], [])
        names = gen._all_loadlock_names([2, 6])
        assert "loadlock_inslot0" in names
        assert "loadlock_outslot0" in names
        assert "loadlock_inslot1" in names
        assert "loadlock_outslot1" in names


class TestRobotIsEfemSide:
    def test_efem_robot_detected_when_prev_is_loadport(self, generator):
        """loadport(efem) → loadlock: 사이 robot은 EFEM robot."""
        prev_names = ["loadport0"]
        ll_names = generator._all_loadlock_names([2])
        assert generator._robot_is_efem_side(prev_names, ll_names) is True

    def test_vacuum_robot_detected_when_prev_is_process_module(self, generator):
        """process_module(vacuum) → loadlock: 사이 robot은 vacuum robot."""
        prev_names = ["process_module0"]
        ll_names = generator._all_loadlock_names([2])
        assert generator._robot_is_efem_side(prev_names, ll_names) is False

    def test_returns_true_when_no_robot_found(self, generator):
        """robot을 찾지 못하면 기본값 True(inslot)."""
        assert generator._robot_is_efem_side([], []) is True


class TestIdsToEngineNamesDirected:
    def test_inslot_used_when_use_inslot_true(self, generator):
        names = generator._ids_to_engine_names_directed([2], use_inslot=True)
        assert names == ["loadlock_inslot0"]

    def test_outslot_used_when_use_inslot_false(self, generator):
        names = generator._ids_to_engine_names_directed([2], use_inslot=False)
        assert names == ["loadlock_outslot0"]

    def test_non_loadlock_module_unaffected(self, generator):
        names = generator._ids_to_engine_names_directed([3], use_inslot=True)
        assert names == ["process_module0"]

    def test_multiple_loadlocks_same_direction(self):
        modules = _base_modules() + [
            {"module_id": 6, "module_type": "loadlock", "cluster": ["efem", "vacuum_cluster_1"]},
        ]
        gen = EqpModelGenerator(_make_equipment_config(modules), [], [])
        assert gen._ids_to_engine_names_directed([2, 6], use_inslot=True) == [
            "loadlock_inslot0", "loadlock_inslot1"
        ]
        assert gen._ids_to_engine_names_directed([2, 6], use_inslot=False) == [
            "loadlock_outslot0", "loadlock_outslot1"
        ]


class TestBuildFullModuleSequenceLoadlockDirection:
    def test_efem_robot_before_loadlock_uses_inslot(self, generator):
        """loadport → loadlock → process_module: EFEM robot이 앞에 옴 → inslot."""
        raw = [[1], [2], [3]]
        full = generator._build_full_module_sequence(raw)
        print(f"\natm->vac: {full}")
        ll_steps = [s for s in full if any("loadlock" in n for n in s)]
        assert len(ll_steps) == 1
        assert all("inslot" in n for n in ll_steps[0]), f"Expected inslot, got {ll_steps[0]}"

    def test_vacuum_robot_before_loadlock_uses_outslot(self, generator):
        """process_module → loadlock → loadport: vacuum robot이 앞에 옴 → outslot."""
        raw = [[3], [2], [1]]
        full = generator._build_full_module_sequence(raw)
        print(f"\nvac->atm: {full}")
        ll_steps = [s for s in full if any("loadlock" in n for n in s)]
        assert len(ll_steps) == 1
        assert all("outslot" in n for n in ll_steps[0]), f"Expected outslot, got {ll_steps[0]}"

    def test_round_trip_inslot_then_outslot(self, generator):
        """왕복: loadport→loadlock(inslot)→process_module→loadlock(outslot)→loadport."""
        raw = [[1], [2], [3], [2], [1]]
        full = generator._build_full_module_sequence(raw)
        print(f"\nround-trip: {full}")
        ll_steps = [s for s in full if any("loadlock" in n for n in s)]
        assert len(ll_steps) == 2
        assert all("inslot" in n for n in ll_steps[0]), f"First LL should be inslot, got {ll_steps[0]}"
        assert all("outslot" in n for n in ll_steps[1]), f"Second LL should be outslot, got {ll_steps[1]}"

    def test_robots_inserted_between_steps(self, generator):
        raw = [[1], [2], [3]]
        full = generator._build_full_module_sequence(raw)
        robot_steps = [s for s in full if any("robot_arm" in n for n in s)]
        assert len(robot_steps) >= 1

    def test_empty_sequence_returns_empty(self, generator):
        assert generator._build_full_module_sequence([]) == []

    def test_loadlock_first_step_defaults_to_inslot(self, generator):
        """이전 non-loadlock step이 없으면 기본값 inslot."""
        raw = [[2], [3]]
        full = generator._build_full_module_sequence(raw)
        ll_steps = [s for s in full if any("loadlock" in n for n in s)]
        assert all("inslot" in n for n in ll_steps[0])
