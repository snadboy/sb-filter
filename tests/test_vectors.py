"""Run FILTER.md's shared vectors against the pure matcher. No Home Assistant needed:

    python3 tests/test_vectors.py        (or: pytest tests/)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The package __init__ imports Home Assistant; the grammar and matcher do not.
# Register a stub package that points at the directory so the pure modules
# (and their relative imports) load with plain python3.
import importlib  # noqa: E402
import types  # noqa: E402

_pkg = types.ModuleType("sb_filter_pure")
_pkg.__path__ = [str(ROOT / "custom_components" / "sb_filter")]
sys.modules["sb_filter_pure"] = _pkg
GRAMMAR_VERSION = importlib.import_module("sb_filter_pure.const").GRAMMAR_VERSION
parse_filter = importlib.import_module("sb_filter_pure.grammar").parse_filter
_m = importlib.import_module("sb_filter_pure.matcher")
DeviceRow, EntityRow, Snapshot, StateRow, evaluate = _m.DeviceRow, _m.EntityRow, _m.Snapshot, _m.StateRow, _m.evaluate

VECTORS = json.loads((ROOT / "tests" / "vectors.json").read_text())


def _snapshot() -> tuple[Snapshot, datetime]:
    s = VECTORS["snapshot"]
    snap = Snapshot(
        states={k: StateRow(state=v["state"], attributes=v["attributes"], last_changed=datetime.fromisoformat(v["last_changed"]))
                for k, v in s["states"].items()},
        entities={k: EntityRow(device_id=v.get("device_id"), area_id=v.get("area_id"), labels=tuple(v.get("labels") or []))
                  for k, v in s["entities"].items()},
        devices={k: DeviceRow(area_id=v.get("area_id"), labels=tuple(v.get("labels") or [])) for k, v in s["devices"].items()},
        formatted=lambda entity_id: s["formatted"].get(entity_id),
        vocabulary=lambda entity_id: [tuple(p) for p in s.get("vocabulary", {}).get(entity_id, [])],
    )
    return snap, datetime.fromisoformat(s["now"])


def test_grammar_version():
    assert VECTORS["grammar"] == GRAMMAR_VERSION, "vectors.json targets another grammar version"


def _run_case(case: dict) -> None:
    snap, now = _snapshot()
    flt = parse_filter(case["config"])
    res = evaluate(flt, snap, now)
    assert list(res.ids) == case["expect_ids"], f"{case['name']}: got {list(res.ids)}"
    if "pattern_counts" in case:
        assert list(res.pattern_counts) == case["pattern_counts"], f"{case['name']}: counts {list(res.pattern_counts)}"
    if "configured" in case:
        assert res.configured is case["configured"], f"{case['name']}: configured={res.configured}"
    if "unreadable" in case:
        assert list(flt.unreadable) == case["unreadable"], f"{case['name']}: unreadable={list(flt.unreadable)}"
    if "unmatched_values" in case:
        got = [{"value": u.value, "suggestions": list(u.suggestions)} for u in res.unmatched_values]
        assert got == case["unmatched_values"], f"{case['name']}: unmatched={got}"


def test_vectors():
    for case in VECTORS["cases"]:
        _run_case(case)


if __name__ == "__main__":
    test_grammar_version()
    failed = 0
    for case in VECTORS["cases"]:
        try:
            _run_case(case)
            print(f"  ok   {case['name']}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {e}")
    print(f"{len(VECTORS['cases']) - failed}/{len(VECTORS['cases'])} vectors pass")
    sys.exit(1 if failed else 0)
