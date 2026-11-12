"""
Live tests: rebuild the reference model in openLCA and check that every
result matches what the v1.16.0 engine produced before the rebuild.

They need openLCA running with the IPC server on port 8080 and the same
ecoinvent database the baseline was captured from, and they are run with

    pytest -m live

The baseline holds results derived from licensed data, so it is not in
this repository. It is found through the OLCA_LIVE_BASELINE environment
variable, or by looking in the parent folders for
REBUILD_PLAN/live_baseline.json.

Everything the tests create goes in the folder "00: olcaBASIC live test"
and the process and product system are deleted at the end.
"""

import json
import os
from pathlib import Path

import pytest

from runner import LiveRunner

pytestmark = pytest.mark.live


def _find_baseline():
    env = os.getenv("OLCA_LIVE_BASELINE")
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "REBUILD_PLAN" / "live_baseline.json"
        if candidate.exists():
            return candidate
    return None


@pytest.fixture(scope="module")
def baseline():
    path = _find_baseline()
    if path is None or not path.exists():
        pytest.skip("no live baseline: set OLCA_LIVE_BASELINE to the path of "
                    "live_baseline.json")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def names(baseline):
    return baseline["live_test_names"]


@pytest.fixture(scope="module")
def tol(baseline):
    return baseline["meta"].get("tolerance_rel", 1e-6)


@pytest.fixture(scope="module")
def live(baseline, names):
    """Build the reference model once, hand over the runner, clean up."""
    runner = LiveRunner()
    info = runner.engine.get_database_info()
    expected = baseline["database_info"]
    if (info.get("processes"), info.get("flows")) != (
            expected["processes"], expected["flows"]):
        pytest.skip(
            f"the open database has {info.get('processes')} processes and "
            f"{info.get('flows')} flows; the baseline was captured from one "
            f"with {expected['processes']} and {expected['flows']}")
    runner.run(baseline["program_template"].format(**names))
    yield runner
    runner.run(f'CONFIRM DELETE ON\nDELETE SYSTEM "{names["name"]}"\n'
               f'DELETE PROCESS "{names["name"]}"')


def close(a, b, tol):
    if a == b:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol * max(abs(a), abs(b))


def rename(text, baseline, names):
    """Baseline text with the reference names swapped for the test names."""
    ref = baseline["reference_names"]
    for key in ("name", "folder", "param"):
        text = text.replace(ref[key], names[key])
    return text


def test_process_matches_the_baseline(live, baseline, names):
    found = live.engine.search_processes(names["name"])["processes"]
    assert len(found) == 1
    got = live.engine.get_process_details(found[0]["id"])
    want = baseline["process_details"]
    assert got["category"] == names["folder"]

    def exchanges(details, swap):
        rows = set()
        for ex in details["exchanges"]:
            formula = ex["formula"] or ""
            flow = ex["flow"]
            if swap:
                formula = rename(formula, baseline, names)
                flow = rename(flow, baseline, names)
            rows.add((flow, formula, ex["unit"], bool(ex["is_input"]),
                      bool(ex["is_qref"]), ex["provider"]))
        return rows

    assert exchanges(got, False) == exchanges(want, True)
    assert ({p["name"]: p["value"] for p in got["parameters"]}
            == {p["name"]: p["value"] for p in want["parameters"]})


def test_system_validates_like_the_baseline(live, baseline, names):
    got = live.engine.validate_system(names["name"])
    want = baseline["validate"]
    assert got["valid"] == want["valid"]
    assert got["summary"] == want["summary"]
    assert ([f["message"] for f in got["findings"]]
            == [f["message"] for f in want["findings"]])


@pytest.mark.parametrize("method", ["EF v3.1", "IPCC 2021"])
def test_calculate_matches_the_baseline(live, baseline, names, tol, method):
    got = live.run(f'CALCULATE "{names["name"]}" USING "{method}"')
    want = baseline["calculate"][method]
    assert got["method"] == want["method"]
    got_by = {i["category"]: i for i in got["impacts"]}
    want_by = {i["category"]: i for i in want["impacts"]}
    assert set(got_by) == set(want_by)
    for cat, w in want_by.items():
        g = got_by[cat]
        assert g["unit"] == w["unit"], cat
        assert close(g["amount"], w["amount"], tol), (
            f"{method} / {cat}: {g['amount']!r} is not {w['amount']!r}")


def test_sensitivity_matches_the_baseline(live, baseline, names, tol):
    spec = baseline["sensitivity"]
    params = [rename(p, baseline, names) for p in spec["parameters"]]
    vary = "\n".join(f"  VARY {p}" for p in params)
    got = live.run(
        f'SENSITIVITY ON "{names["name"]}" USING "{spec["method"]}" '
        f'BY {spec["variation_pct"]}%\n{vary}\nEND SENSITIVITY')
    want = spec["result"]
    assert got["tested"] == params and got["missing"] == []
    for cat, w in want["baseline"].items():
        assert close(got["baseline"][cat]["amount"], w["amount"], tol), cat
    for ref_param, w in want["sensitivity"].items():
        g = got["sensitivity"][rename(ref_param, baseline, names)]
        assert close(g["baseline_value"], w["baseline_value"], tol)
        for side in ("minus", "plus"):
            assert set(g[side]) == set(w[side])
            for cat, amount in w[side].items():
                assert close(g[side][cat], amount, tol), (
                    f"{ref_param} {side} / {cat}: {g[side][cat]!r} is not "
                    f"{amount!r}")


@pytest.mark.slow
def test_contribution_matches_the_baseline(live, baseline, names, tol):
    """Slow: the engine asks openLCA about every process in the system
    (about six minutes on the ecoinvent test database)."""
    spec = baseline["contribution"]
    cats = ", ".join(f'"{c}"' for c in spec["categories"])
    got = live.run(
        f'CONTRIBUTION "{names["name"]}" USING "{spec["method"]}" '
        f'TOP {spec["top"]}\n  CATEGORIES {cats}\nEND CONTRIBUTION')
    want = spec["result"]
    assert set(got["categories"]) == set(want["categories"])
    for cat, w in want["categories"].items():
        g = got["categories"][cat]
        assert close(g["total"], w["total"], tol), cat
        assert g["unit"] == w["unit"]
        assert len(g["contributors"]) == len(w["contributors"]), cat
        for gc, wc in zip(g["contributors"], w["contributors"]):
            assert gc["process"] == rename(wc["process"], baseline, names), cat
            assert gc["flow"] == rename(wc["flow"], baseline, names), cat
            assert close(gc["amount"], wc["amount"], tol), (
                f"{cat} / {wc['process']}: {gc['amount']!r} is not "
                f"{wc['amount']!r}")
            assert abs(gc["pct"] - wc["pct"]) <= 0.011, cat
