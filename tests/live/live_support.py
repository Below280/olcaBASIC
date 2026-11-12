"""Finding the live baseline that belongs to the open database."""

import json
import os
from pathlib import Path

import pytest


def _find_baselines():
    env = os.getenv("OLCA_LIVE_BASELINE")
    if env:
        return [Path(env)]
    found = []
    for parent in Path(__file__).resolve().parents:
        first = parent / "REBUILD_PLAN" / "live_baseline.json"
        if first.exists():
            found.append(first)
        second = parent / "REBUILD_PLAN_2"
        if second.is_dir():
            found.extend(sorted(second.glob("live_baseline_*.json")))
        if found:
            break
    return found


def _mismatch(info, expected):
    """Why a baseline does not belong to the open database, or ""."""
    # A few extra entities are fine (these tests leave a flow behind,
    # and the reference model may or may not be present).
    for kind in ("processes", "flows"):
        if abs(info.get(kind, 0) - expected[kind]) > 25:
            return (f"{info.get(kind)} {kind} against {expected[kind]}")
    if info.get("impact_methods") != expected["impact_methods"]:
        return (f"{info.get('impact_methods')} impact methods against "
                f"{expected['impact_methods']}")
    return ""


def matching_baseline(engine):
    """The baseline captured from the database that is open. Skips the
    test (with the reason) when there is none."""
    paths = [p for p in _find_baselines() if p.exists()]
    if not paths:
        pytest.skip("no live baseline: set OLCA_LIVE_BASELINE to the path of "
                    "a live_baseline file")
    info = engine.get_database_info()
    reasons = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        why = _mismatch(info, data["database_info"])
        if not why:
            return data
        reasons.append(f"{path.name}: {why}")
    # A different database gives different numbers, so say so instead
    # of failing.
    pytest.skip("no baseline was captured from the open database ("
                + "; ".join(reasons) + ")")
