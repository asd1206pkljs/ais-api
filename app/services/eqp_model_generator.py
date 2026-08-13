"""
EqpModelGenerator: dict 형태의 config → eqp_models/{name}/ 디렉토리 생성

외부 의존성 없음 (SQLAlchemy, FastAPI 불필요).
ais 학습 환경에서 직접 import 가능.

입력:
  equipment_config: {
    equipment_name, cluster_type,
    modules: [{module_id(int), module_type, display_name, cluster(list)}],
    timetables: {str(api_module_id): ModuleTimeConfig}
  }
  flow_recipe_configs: [{flow_recipe_name, module_sequence([[int]]), process_recipe_steps}]
  process_recipe_configs: [{process_recipe_id, process_recipe_name, user_added_process_modules([int])}]

출력: eqp_models/{equipment_name}/ 디렉토리 전체
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path


CLUSTER_NAME_MAP = {
    "efem": "efem",
    "vacuum_cluster_1": "vtm0",
    "vacuum_cluster_2": "vtm1",
}
MODULE_TYPE_PREFIX = {
    "loadport": "loadport",
    "loadlock": "loadlock",
    "aligner": "aligner",
    "process_module": "process_module",
    "robot": "robot_arm",
    "buffer": "buffer",
}
CLUSTER_ORDER = ["efem", "vacuum_cluster_1", "vacuum_cluster_2"]
MAX_WAFER_COUNT = 25
LOT_HISTORY_SIZE = 1000     # lot_history.json 엔트리 수 (flow_recipe 랜덤 샘플링)
DEFAULT_MOVE_TIME = [5.0]   # timetable 미설정 시 robot 이동 기본값 (초)
DEFAULT_GET_TIME  = [5.0]   # timetable 미설정 시 robot get 기본값 (초)
DEFAULT_PUT_TIME  = [5.0]   # timetable 미설정 시 robot put 기본값 (초)


def _time_value(cfg: dict | None) -> list[float]:
    if not cfg:
        return []
    if cfg.get("useTimeTable"):
        return []
    raw = cfg.get("fixedTime", "")
    try:
        return [float(raw)] if raw else []
    except (ValueError, TypeError):
        return []


def _door_values(cfg: dict | None) -> tuple[list[float], list[float]]:
    if not cfg:
        return [], []
    if cfg.get("useTimeTable"):
        return [], []
    try:
        raw_open = cfg.get("fixedOpenTime", "")
        raw_close = cfg.get("fixedCloseTime", "")
        open_v = [float(raw_open)] if raw_open else []
        close_v = [float(raw_close)] if raw_close else []
        return open_v, close_v
    except (ValueError, TypeError):
        return [], []


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")


def _engine_cluster(web_cluster: str) -> str:
    return CLUSTER_NAME_MAP.get(web_cluster, web_cluster)


def _transfer_module_field(clusters: list[str]):
    eng = [_engine_cluster(c) for c in clusters]
    return eng[0] if len(eng) == 1 else eng


class EqpModelGenerator:
    def __init__(
        self,
        equipment_config: dict,
        flow_recipe_configs: list[dict],
        process_recipe_configs: list[dict],
    ):
        self.equipment_config = equipment_config
        self.flow_recipe_configs = flow_recipe_configs
        self.process_recipe_configs = process_recipe_configs

        self.modules: list[dict] = sorted(
            equipment_config["modules"],
            key=lambda m: (
                min(
                    (CLUSTER_ORDER.index(c) for c in m["cluster"] if c in CLUSTER_ORDER),
                    default=99,
                ),
                m["module_id"],
            ),
        )
        self.module_by_api_id: dict[int, dict] = {m["module_id"]: m for m in self.modules}
        # JSON 경계에서 한 번만 정규화: 키를 int로 통일 (JSON은 key를 str로 직렬화하므로)
        self.timetables: dict[int, dict] = {
            int(k): v
            for k, v in equipment_config.get("timetables", {}).items()
            if str(k).lstrip("-").isdigit()
        }

        self._build_name_maps()

        self.pr_uuid_to_engine: dict[str, str] = {
            pr["process_recipe_id"]: f"process_recipe{idx}"
            for idx, pr in enumerate(self.process_recipe_configs)
            if pr.get("process_recipe_id")
        }

    def _build_name_maps(self) -> None:
        counters: dict[str, int] = defaultdict(int)
        self.engine_name: dict[int, str] = {}
        self.loadlock_pairs: dict[int, tuple[str, str]] = {}
        self.engine_type: dict[int, str] = {}

        ll_counter = 0
        for mod in self.modules:
            mid = mod["module_id"]
            mtype = mod["module_type"]
            if mtype == "loadlock":
                n = ll_counter
                ll_counter += 1
                inslot = f"loadlock_inslot{n}"
                outslot = f"loadlock_outslot{n}"
                self.loadlock_pairs[mid] = (inslot, outslot)
                self.engine_name[mid] = inslot
                self.engine_type[mid] = "loadlock"
            elif mtype == "robot":
                n = counters["robot"]
                counters["robot"] += 1
                self.engine_name[mid] = f"robot_arm{n}"
                self.engine_type[mid] = "robot_arm"
            else:
                prefix = MODULE_TYPE_PREFIX.get(mtype, mtype)
                n = counters[mtype]
                counters[mtype] += 1
                self.engine_name[mid] = f"{prefix}{n}"
                self.engine_type[mid] = mtype

    def _tt(self, api_id: int) -> dict:
        return self.timetables.get(api_id, {})

    def _by_type(self, mtype: str) -> list[dict]:
        return [m for m in self.modules if m["module_type"] == mtype]

    def _reachable_names(self, robot_mod: dict) -> list[str]:
        """robot이 접근 가능한 모든 engine 이름 (loadlock은 inslot+outslot 둘 다)."""
        robot_clusters = set(_engine_cluster(c) for c in robot_mod["cluster"])
        result: list[str] = []
        for m in self.modules:
            if m["module_type"] == "robot":
                continue
            mod_clusters = set(_engine_cluster(c) for c in m["cluster"])
            if robot_clusters & mod_clusters:
                mid = m["module_id"]
                if mid in self.loadlock_pairs:
                    inslot, outslot = self.loadlock_pairs[mid]
                    if inslot not in result:
                        result.append(inslot)
                    if outslot not in result:
                        result.append(outslot)
                else:
                    name = self.engine_name[mid]
                    if name not in result:
                        result.append(name)
        return result

    def _find_robots_between(self, names_a: list[str], names_b: list[str]) -> list[str]:
        set_a, set_b = set(names_a), set(names_b)
        result = []
        for mod in self.modules:
            if mod["module_type"] != "robot":
                continue
            accessible = set(self._reachable_names(mod))
            if (accessible & set_a) and (accessible & set_b):
                result.append(self.engine_name[mod["module_id"]])
        return sorted(result)

    def _ids_to_engine_names(self, api_ids: list) -> list[str]:
        """loadlock은 inslot+outslot 둘 다 반환 (reachability 계산용)."""
        result = []
        for aid in api_ids:
            mid = int(aid) if not isinstance(aid, int) else aid
            if mid not in self.module_by_api_id:
                continue
            if mid in self.loadlock_pairs:
                inslot, outslot = self.loadlock_pairs[mid]
                result.extend([inslot, outslot])
            else:
                result.append(self.engine_name[mid])
        return result

    def _ids_to_engine_names_directed(self, api_ids: list, use_inslot: bool) -> list[str]:
        """loadlock은 방향에 따라 inslot 또는 outslot만 반환."""
        result = []
        for aid in api_ids:
            mid = int(aid) if not isinstance(aid, int) else aid
            if mid not in self.module_by_api_id:
                continue
            if mid in self.loadlock_pairs:
                inslot, outslot = self.loadlock_pairs[mid]
                result.append(inslot if use_inslot else outslot)
            else:
                result.append(self.engine_name[mid])
        return result

    def _all_loadlock_names(self, api_ids: list) -> list[str]:
        """loadlock step의 inslot+outslot 이름 전부 반환 (robot 탐색용)."""
        result = []
        for aid in api_ids:
            mid = int(aid) if not isinstance(aid, int) else aid
            if mid in self.loadlock_pairs:
                inslot, outslot = self.loadlock_pairs[mid]
                result.extend([inslot, outslot])
        return result

    def _robot_is_efem_side(self, prev_names: list[str], ll_all_names: list[str]) -> bool:
        """이전 step과 loadlock 사이를 잇는 robot이 EFEM 영역인지 반환.
        True → inslot (atmospheric→vacuum), False → outslot (vacuum→atmospheric).
        """
        prev_set = set(prev_names)
        ll_set = set(ll_all_names)
        for mod in self.modules:
            if mod["module_type"] != "robot":
                continue
            reachable = set(self._reachable_names(mod))
            if (reachable & prev_set) and (reachable & ll_set):
                return "efem" in [_engine_cluster(c) for c in mod["cluster"]]
        return True  # 기본값: inslot

    def _build_full_module_sequence(self, raw: list[list]) -> list[list[str]]:
        """non-robot step 목록에 robot step을 자동 삽입.

        loadlock 방향은 직전 non-loadlock step과 loadlock 사이 robot의 클러스터로 결정:
          - EFEM robot → inslot (atmospheric→vacuum)
          - vacuum robot → outslot (vacuum→atmospheric)
        """
        if not raw:
            return []

        def step_has_loadlock(step: list) -> bool:
            return any(
                (int(aid) if not isinstance(aid, int) else aid) in self.loadlock_pairs
                for aid in step
            )

        last_non_ll_names: list[str] = []
        converted = []
        for step in raw:
            if step_has_loadlock(step):
                ll_all = self._all_loadlock_names(step)
                use_inslot = self._robot_is_efem_side(last_non_ll_names, ll_all)
                names = self._ids_to_engine_names_directed(step, use_inslot=use_inslot)
            else:
                names = self._ids_to_engine_names(step)
                if names:
                    last_non_ll_names = names
            if names:
                converted.append(names)

        if not converted:
            return []

        full = [converted[0]]
        for i in range(1, len(converted)):
            robots = self._find_robots_between(converted[i - 1], converted[i])
            if robots:
                full.append(robots)
            full.append(converted[i])
        return full

    # ── 파일 생성 ─────────────────────────────────────────────────────────────

    def generate(self, output_dir: str) -> None:
        out = Path(output_dir)
        eqp_name = self.equipment_config["equipment_name"]
        self._gen_env_config(out, eqp_name)
        self._gen_transfer_modules(out)
        self._gen_loadports(out)
        self._gen_aligners(out)
        self._gen_process_modules(out)
        self._gen_loadlocks(out)
        self._gen_buffers(out)
        self._gen_robot_arms(out)
        self._gen_process_recipe_config(out)
        self._gen_flow_recipe_config(out)
        self._gen_lot_config(out)
        self._gen_lot_history(out)
        self._gen_actions(out)

    def _gen_env_config(self, out: Path, eqp_name: str) -> None:
        _write_json(out / "env_config.json", {
            "eqp_name": eqp_name,
            "use_same_recipe_in_lot": True,
            "num_loadports": len(self._by_type("loadport")),
            "num_loadlocks": len(self._by_type("loadlock")),
            "max_wafer_count": MAX_WAFER_COUNT,
            "max_proceed_time": 10,
        })

    def _gen_transfer_modules(self, out: Path) -> None:
        cluster_static: dict[str, list[str]] = defaultdict(list)
        cluster_robots: dict[str, list[str]] = defaultdict(list)
        cluster_order: list[str] = []

        for mod in self.modules:
            mid = mod["module_id"]
            mtype = mod["module_type"]
            for wc in mod["cluster"]:
                ec = _engine_cluster(wc)
                if ec not in cluster_order:
                    cluster_order.append(ec)
                if mtype == "robot":
                    name = self.engine_name[mid]
                    if name not in cluster_robots[ec]:
                        cluster_robots[ec].append(name)
                elif mtype == "loadlock":
                    inslot, outslot = self.loadlock_pairs[mid]
                    for n in [inslot, outslot]:
                        if n not in cluster_static[ec]:
                            cluster_static[ec].append(n)
                else:
                    name = self.engine_name[mid]
                    if name not in cluster_static[ec]:
                        cluster_static[ec].append(name)

        cluster_type_map = {"efem": 1}
        result = []
        for i, ec in enumerate(cluster_order):
            result.append({
                "name": ec,
                "display_name": ec.upper(),
                "module_id": i,
                "module_type": cluster_type_map.get(ec, 0),
                "static_modules": cluster_static[ec],
                "robot_arms": cluster_robots[ec],
            })
        _write_json(out / "modules" / "transfer_modules.json", result)

    def _gen_loadports(self, out: Path) -> None:
        result = []
        for seq_idx, mod in enumerate(self._by_type("loadport")):
            mid = mod["module_id"]
            name = self.engine_name[mid]
            tt = self._tt(mid)
            entry: dict = {
                "name": name,
                "display_name": mod.get("display_name", name),
                "module_id": seq_idx,   # 환경은 lot_list[module_id] 인덱스로 사용 → 0-based 순서
                "module_type": "loadport",
                "transfer_module": _transfer_module_field(mod["cluster"]),
            }
            if tt.get("hasDoor"):
                open_t, close_t = _door_values(tt.get("door"))
                open_rel = f"modules/timetables/{name}-door_open.json"
                close_rel = f"modules/timetables/{name}-door_close.json"
                _write_json(out / open_rel, open_t)
                _write_json(out / close_rel, close_t)
                entry["door_open_timetable"] = open_rel
                entry["door_close_timetable"] = close_rel
            else:
                entry["door_open_timetable"] = None
                entry["door_close_timetable"] = None
            result.append(entry)
        _write_json(out / "modules" / "loadports.json", result)

    def _gen_align_timetable(self, tt: dict) -> dict[str, list[float]]:
        """alignTime: {loadlock_module_id(int): TimeConfig} →
        {loadlock_inslot_name: [float]}  (전체 loadlock 망라, 없는 항목은 [])
        """
        all_ll_inslots = [
            self.loadlock_pairs[m["module_id"]][0]
            for m in self._by_type("loadlock")
        ]
        # alignTime 키도 JSON 경계에서 int로 정규화
        raw_align: dict = tt.get("alignTime", {}) if tt else {}
        align_time_cfg: dict[int, dict] = {
            int(k): v
            for k, v in raw_align.items()
            if str(k).lstrip("-").isdigit()
        }
        result: dict[str, list[float]] = {inslot: [] for inslot in all_ll_inslots}
        for ll_id, time_cfg in align_time_cfg.items():
            if ll_id not in self.loadlock_pairs:
                continue
            inslot = self.loadlock_pairs[ll_id][0]
            result[inslot] = _time_value(time_cfg)
        return result

    def _gen_aligners(self, out: Path) -> None:
        result = []
        for seq_idx, mod in enumerate(self._by_type("aligner")):
            mid = mod["module_id"]
            name = self.engine_name[mid]
            tt = self._tt(mid)
            align_t = self._gen_align_timetable(tt)
            align_rel = f"modules/timetables/{name}-align.json"
            _write_json(out / align_rel, align_t)

            door_open_rel = door_close_rel = None
            if tt and tt.get("hasDoor"):
                open_t, close_t = _door_values(tt.get("door"))
                door_open_rel = f"modules/timetables/{name}-door_open.json"
                door_close_rel = f"modules/timetables/{name}-door_close.json"
                _write_json(out / door_open_rel, open_t)
                _write_json(out / door_close_rel, close_t)

            result.append({
                "name": name,
                "display_name": mod.get("display_name", name),
                "module_id": seq_idx,
                "module_type": "aligner",
                "transfer_module": _transfer_module_field(mod["cluster"]),
                "align_timetable": align_rel,
                "door_open_timetable": door_open_rel,
                "door_close_timetable": door_close_rel,
            })
        _write_json(out / "modules" / "aligners.json", result)

    def _gen_process_modules(self, out: Path) -> None:
        result = []
        for seq_idx, mod in enumerate(self._by_type("process_module")):
            mid = mod["module_id"]
            name = self.engine_name[mid]
            tt = self._tt(mid)
            open_t, close_t = _door_values(tt.get("door") if tt else None)
            door_open_rel = f"modules/timetables/{name}-door_open.json"
            door_close_rel = f"modules/timetables/{name}-door_close.json"
            _write_json(out / door_open_rel, open_t)
            _write_json(out / door_close_rel, close_t)
            result.append({
                "name": name,
                "display_name": mod.get("display_name", name),
                "module_id": seq_idx,
                "module_type": "process_module",
                "transfer_module": _transfer_module_field(mod["cluster"]),
                "door_open_timetable": door_open_rel,
                "door_close_timetable": door_close_rel,
            })
        _write_json(out / "modules" / "process_modules.json", result)

    def _gen_loadlocks(self, out: Path) -> None:
        result = []
        for seq_idx, mod in enumerate(self._by_type("loadlock")):
            mid = mod["module_id"]
            inslot, outslot = self.loadlock_pairs[mid]
            tt = self._tt(mid)
            pump_t = _time_value(tt.get("pumpTime") if tt else None)
            vent_t = _time_value(tt.get("ventTime") if tt else None)
            pumped_open, pumped_close = _door_values(tt.get("doorPumped") if tt else None)
            vented_open, vented_close = _door_values(tt.get("doorVented") if tt else None)

            n = inslot.replace("loadlock_inslot", "")
            pump_rel = f"modules/timetables/loadlock{n}-pump.json"
            vent_rel = f"modules/timetables/loadlock{n}-vent.json"
            in_open_rel = f"modules/timetables/loadlock{n}_inslot-door_open.json"
            in_close_rel = f"modules/timetables/loadlock{n}_inslot-door_close.json"
            out_open_rel = f"modules/timetables/loadlock{n}_outslot-door_open.json"
            out_close_rel = f"modules/timetables/loadlock{n}_outslot-door_close.json"

            _write_json(out / pump_rel, pump_t)
            _write_json(out / vent_rel, vent_t)
            _write_json(out / in_open_rel, pumped_open)
            _write_json(out / in_close_rel, pumped_close)
            _write_json(out / out_open_rel, vented_open)
            _write_json(out / out_close_rel, vented_close)

            clusters = [_engine_cluster(c) for c in mod["cluster"]]
            tf = clusters[0] if len(clusters) == 1 else clusters
            pair = [
                {
                    "name": inslot,
                    "display_name": mod.get("display_name", f"LoadLock{n}"),
                    "module_id": seq_idx,
                    "module_type": "loadlock_inslot",
                    "transfer_module": tf,
                    "door_open_timetable": in_open_rel,
                    "door_close_timetable": in_close_rel,
                    "pump_timetable": pump_rel,
                    "vent_timetable": vent_rel,
                },
                {
                    "name": outslot,
                    "display_name": mod.get("display_name", f"LoadLock{n}"),
                    "module_id": seq_idx,
                    "module_type": "loadlock_outslot",
                    "transfer_module": tf,
                    "door_open_timetable": out_open_rel,
                    "door_close_timetable": out_close_rel,
                    "pump_timetable": pump_rel,
                    "vent_timetable": vent_rel,
                },
            ]
            result.append(pair)
        _write_json(out / "modules" / "loadlocks.json", result)

    def _gen_buffers(self, out: Path) -> None:
        result = []
        for seq_idx, mod in enumerate(self._by_type("buffer")):
            mid = mod["module_id"]
            name = self.engine_name[mid]
            tt = self._tt(mid)
            cooling_t = _time_value(tt.get("coolingTime") if tt else None)
            cooling_rel = f"modules/timetables/{name}-cooling.json"
            _write_json(out / cooling_rel, cooling_t)

            door_open_rel = door_close_rel = None
            if tt and tt.get("hasDoor"):
                open_t, close_t = _door_values(tt.get("door"))
                door_open_rel = f"modules/timetables/{name}-door_open.json"
                door_close_rel = f"modules/timetables/{name}-door_close.json"
                _write_json(out / door_open_rel, open_t)
                _write_json(out / door_close_rel, close_t)

            result.append({
                "name": name,
                "display_name": mod.get("display_name", name),
                "module_id": seq_idx,
                "module_type": "buffer",
                "transfer_module": _transfer_module_field(mod["cluster"]),
                "cooling_timetable": cooling_rel,
                "door_open_timetable": door_open_rel,
                "door_close_timetable": door_close_rel,
            })
        _write_json(out / "modules" / "buffers.json", result)

    def _gen_robot_arms(self, out: Path) -> None:
        result = []
        for seq_idx, mod in enumerate(self._by_type("robot")):
            mid = mod["module_id"]
            name = self.engine_name[mid]
            tt = self._tt(mid)
            reachable = self._reachable_names(mod)

            move_data: dict = {
                fn: {tn: [DEFAULT_MOVE_TIME, DEFAULT_MOVE_TIME] for tn in reachable if tn != fn}
                for fn in reachable
            }
            get_data: dict = {n: DEFAULT_GET_TIME for n in reachable}
            put_data: dict = {n: DEFAULT_PUT_TIME for n in reachable}

            if tt:
                # moveTimes 키는 "from_id__to_id" 형식
                move_times: dict[tuple[int, int], dict] = {}
                for pair_key, move_val in tt.get("moveTimes", {}).items():
                    parts = pair_key.split("__")
                    if len(parts) != 2:
                        continue
                    try:
                        move_times[(int(parts[0]), int(parts[1]))] = move_val
                    except ValueError:
                        continue
                for (from_id, to_id), move_val in move_times.items():
                    # A loadlock expands to two engine positions (inslot/outslot).
                    # Apply the user's move time to BOTH slots on the source AND
                    # destination side, so inslot/outslot moves share one value
                    # instead of the un-set slot falling back to DEFAULT_MOVE_TIME.
                    from_names: list[str] = []
                    if from_id in self.loadlock_pairs:
                        from_names.extend(self.loadlock_pairs[from_id])
                    elif from_id in self.engine_name:
                        from_names.append(self.engine_name[from_id])
                    to_names: list[str] = []
                    if to_id in self.loadlock_pairs:
                        to_names.extend(self.loadlock_pairs[to_id])
                    elif to_id in self.engine_name:
                        to_names.append(self.engine_name[to_id])
                    if not from_names or not to_names:
                        continue
                    with_w = _time_value(move_val.get("withWafer"))
                    same = move_val.get("sameTimeRegardlessOfWafer", False)
                    without_w = with_w if same else _time_value(move_val.get("withoutWafer"))
                    for from_name in from_names:
                        for to_name in to_names:
                            if from_name == to_name:
                                continue
                            if from_name not in move_data:
                                move_data[from_name] = {}
                            move_data[from_name][to_name] = [with_w, without_w]

                get_times: dict[int, dict] = {
                    int(k): v for k, v in tt.get("getTimes", {}).items()
                    if str(k).lstrip("-").isdigit()
                }
                for api_id, val in get_times.items():
                    t = _time_value(val)
                    if api_id in self.loadlock_pairs:
                        for n in self.loadlock_pairs[api_id]:
                            get_data[n] = t
                    elif api_id in self.engine_name:
                        get_data[self.engine_name[api_id]] = t

                put_times: dict[int, dict] = {
                    int(k): v for k, v in tt.get("putTimes", {}).items()
                    if str(k).lstrip("-").isdigit()
                }
                for api_id, val in put_times.items():
                    t = _time_value(val)
                    if api_id in self.loadlock_pairs:
                        for n in self.loadlock_pairs[api_id]:
                            put_data[n] = t
                    elif api_id in self.engine_name:
                        put_data[self.engine_name[api_id]] = t

            move_rel = f"modules/timetables/{name}-move.json"
            get_rel = f"modules/timetables/{name}-get.json"
            put_rel = f"modules/timetables/{name}-put.json"
            _write_json(out / move_rel, move_data)
            _write_json(out / get_rel, get_data)
            _write_json(out / put_rel, put_data)

            transfer = _transfer_module_field(mod["cluster"])
            result.append({
                "name": name,
                "display_name": mod.get("display_name", name),
                "module_id": seq_idx,
                "module_type": "robot_arm",
                "transfer_module": transfer,
                "move_timetable": move_rel,
                "get_timetable": get_rel,
                "put_timetable": put_rel,
            })
        _write_json(out / "modules" / "robot_arms.json", result)

    def _gen_process_recipe_config(self, out: Path) -> None:
        result = []
        for idx, pr in enumerate(self.process_recipe_configs):
            engine_name = f"process_recipe{idx}"
            pr_uuid = pr.get("process_recipe_id", "")
            pm_names = []
            process_times: dict[str, list] = {}

            for api_mid in pr.get("user_added_process_modules", []):
                pm_eng = self.engine_name.get(api_mid)
                if not pm_eng:
                    continue
                pm_names.append(pm_eng)
                pm_tt = self._tt(api_mid)
                per_recipe = pm_tt.get("processTimesPerRecipe", {}) if pm_tt else {}
                time_cfg = per_recipe.get(pr_uuid)
                process_times[pm_eng] = _time_value(time_cfg)

            time_rel = f"materials/timetables/{engine_name}.json"
            _write_json(out / time_rel, process_times)
            result.append({
                "name": engine_name,
                "display_name": pr.get("process_recipe_name", engine_name),
                "process_modules": pm_names,
                "process_time_table": time_rel,
            })
        _write_json(out / "materials" / "process_recipe_config.json", result)

    def _gen_flow_recipe_config(self, out: Path) -> None:
        result = []
        for idx, fr in enumerate(self.flow_recipe_configs):
            engine_name = f"flow_recipe{idx}"
            pr_names = [
                self.pr_uuid_to_engine[s["process_recipe_id"]]
                for s in sorted(fr.get("process_recipe_steps", []), key=lambda x: x.get("step", 0))
                if s.get("process_recipe_id") in self.pr_uuid_to_engine
            ]
            raw_seq = fr.get("module_sequence", [])
            full_seq = self._build_full_module_sequence(raw_seq)
            result.append({
                "name": engine_name,
                "display_name": fr.get("flow_recipe_name", engine_name),
                "process_recipes": pr_names,
                "module_sequence": full_seq,
            })
        _write_json(out / "materials" / "flow_recipe_config.json", result)

    def _gen_lot_config(self, out: Path) -> None:
        lps = self._by_type("loadport")
        _write_json(out / "materials" / "lot_config.json", [
            {"lot_id": i, "max_wafer_count": MAX_WAFER_COUNT} for i in range(len(lps))
        ])

    def _gen_lot_history(self, out: Path) -> None:
        flows = [f"flow_recipe{i}" for i in range(len(self.flow_recipe_configs))] or ["flow_recipe0"]
        _write_json(out / "materials" / "lot_history.json", [
            {"name": f"LOT{i + 1}", "flow_recipe": random.choice(flows), "wafer_count": MAX_WAFER_COUNT}
            for i in range(LOT_HISTORY_SIZE)
        ])

    def _gen_actions(self, out: Path) -> None:
        _write_json(out / "actions" / "proceed.json", {
            "name": "proceed", "module": None, "dst_module": None, "type": "active",
        })
        for mod in self._by_type("robot"):
            mid = mod["module_id"]
            name = self.engine_name[mid]
            reachable = self._reachable_names(mod)
            actions = [
                {"name": "move", "module": name, "dst_module": dst, "type": "active"}
                for dst in sorted(reachable)
            ]
            actions.append({"name": "get", "module": name, "dst_module": name, "type": "passive"})
            actions.append({"name": "put", "module": name, "dst_module": None, "type": "passive"})
            _write_json(out / "actions" / f"{name}.json", actions)

        for mod in self._by_type("loadlock"):
            mid = mod["module_id"]
            inslot, outslot = self.loadlock_pairs[mid]
            for slot_name, action_name in [(inslot, "pump"), (outslot, "vent")]:
                _write_json(out / "actions" / f"{slot_name}.json", [
                    {"name": action_name, "module": slot_name, "dst_module": None, "type": "active"},
                    {"name": "door_open", "module": slot_name, "dst_module": None, "type": "passive"},
                    {"name": "door_close", "module": slot_name, "dst_module": None, "type": "passive"},
                ])

        for mod in self._by_type("process_module"):
            mid = mod["module_id"]
            name = self.engine_name[mid]
            _write_json(out / "actions" / f"{name}.json", [
                {"name": "process", "module": name, "dst_module": None, "type": "passive"},
                {"name": "door_open", "module": name, "dst_module": None, "type": "passive"},
                {"name": "door_close", "module": name, "dst_module": None, "type": "passive"},
            ])

        ll_inslots = [self.loadlock_pairs[m["module_id"]][0] for m in self._by_type("loadlock")]
        for mod in self._by_type("aligner"):
            mid = mod["module_id"]
            name = self.engine_name[mid]
            _write_json(out / "actions" / f"{name}.json", [
                {"name": "align", "module": name, "dst_module": ll, "type": "active"}
                for ll in sorted(ll_inslots)
            ])
