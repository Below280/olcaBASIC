"""
Live tests for the EPD workflow.

    pytest -m live

Three groups:

1. What the EPD block refuses on a database with no EN 15804+A2
   method. These run on the ecoinvent test database as it is.
2. Declarations on a real bridge: tags, validity dates, and the
   location-based switch (two providers on one bridge, chosen by a
   global parameter). These need only a database with two processes
   that share a name and differ by location, which the baseline's
   reference model points at.
3. A small EPD from end to end. It needs an EN 15804+A2 method with the
   full indicator set, and is skipped with a clear message when the
   database has none. The method check is not loosened to make it run.

Everything is built in the folder "00: olcaBASIC live EPD" and deleted
at the end, except product flows (see test_live_baseline.py) and the
global parameter epd_location_based, which openLCA keeps database-wide.

No dataset name is written here: the provider is read at run time from
the private baseline file, which is not in the repository.
"""

import csv
import re

import pytest

from runner import LiveRunner
from test_live_baseline import _find_baseline

pytestmark = pytest.mark.live

FOLDER = "00: olcaBASIC live EPD"
EPD_METHOD = "EN15804+A2 (EF 3.1)"
SWITCH = "epd_location_based"


@pytest.fixture(scope="module")
def live():
    runner = LiveRunner()
    family = runner.engine.database_family
    if family not in ("ecoinvent", "flcac"):
        runner.run('DATABASE FAMILY "ecoinvent"')
    yield runner
    runner.session.run("EPD CLOSE")


@pytest.fixture(scope="module")
def providers(live):
    """Two processes with the same name at different locations, taken
    from the first USE PROCESS ... LOCATION line of the private
    baseline program. Returns (first id, second id)."""
    import json
    path = _find_baseline()
    if path is None or not path.exists():
        pytest.skip("no live baseline: set OLCA_LIVE_BASELINE to the path "
                    "of live_baseline.json")
    program = json.loads(path.read_text(encoding="utf-8"))["program_template"]
    m = re.search(r'USE PROCESS "([^"]+)".*kWh LOCATION "([^"]+)"', program)
    if not m:
        pytest.skip("the baseline program has no electricity input to use")
    name, location = m.groups()
    found = live.engine.process_candidates(name)
    first = [c for c in found if c["location"] == location]
    others = [c for c in found if c["location"] != location]
    if not first or not others:
        pytest.skip("the database does not hold that process at two locations")
    return first[0]["id"], others[0]["id"]


def _has_epd_method(live) -> bool:
    return "error" not in live.engine.find_method_strict(EPD_METHOD)


def _block(method=EPD_METHOD, modules="A1, A2, A3, C1, C2, C3, C4, D",
           extra=""):
    return (f'EPD "olcaBASIC live EPD"\n  DECLARED UNIT 1, kg\n'
            f'  METHOD "{method}"\n  FOLDER "{FOLDER}"\n'
            f'  MODULES {modules}\n  BIOGENIC CARBON NO\n{extra}END EPD')


# ── 1. refusals that need no EN 15804+A2 method ──────────────

def test_a_method_that_is_not_en15804_is_refused(live):
    r = live.session.run(_block(method="EF v3.1"))
    assert not r.ok
    assert "not an EN 15804+A2 method" in r.errors[0]["message"]
    assert r.errors[0]["line"] == 3
    assert live.session.runtime.epd is None


def test_the_epd_method_is_refused_when_it_is_not_installed(live):
    if _has_epd_method(live):
        pytest.skip(f"'{EPD_METHOD}' is installed in this database")
    r = live.session.run(_block())
    assert not r.ok
    assert r.errors[0]["line"] == 3
    assert live.session.runtime.epd is None


def test_module_rules_are_checked_before_the_database_is_asked(live):
    r = live.session.run(_block(modules="A1, A2, A3"))
    assert not r.ok
    assert "clause 5.2" in r.errors[0]["message"]


# ── 2. declarations on a real bridge ─────────────────────────

@pytest.fixture(scope="module")
def bridge(live, providers):
    first, second = providers
    name = "BRIDGE | olcaBASIC live electricity | kWh"
    live.session.run(f'CONFIRM DELETE ON\nDELETE SYSTEM "{name}"\n'
                     f'DELETE PROCESS "{name}"')
    r = live.session.run(f'''BRIDGE "olcaBASIC live electricity", kWh
  FOLDER "{FOLDER}/Bridges"
  PROVIDER "{first}"
  ELECTRICITY RESIDUAL
  COUNTRY "GB"
  ENERGY SOURCE "Live test mix, one"
  LOCATION BASED PROVIDER "{second}"
  DATA PRIMARY SOURCE "Database" PROVIDER "live test" YEAR 2024
END BRIDGE''')
    assert r.ok, f"{r.errors}\n{r.text}"
    found = live.engine.process_candidates(name)
    assert len(found) == 1
    yield {"name": name, "id": found[0]["id"]}
    live.session.run(f'CONFIRM DELETE ON\nDELETE SYSTEM "{name}"\n'
                     f'DELETE PROCESS "{name}"')


def test_declarations_are_stored_on_the_process(live, bridge):
    got = live.engine.get_process_tags(bridge["id"], "epd")
    assert "error" not in got, got
    tags = got["tags"]
    assert tags["data"] == "PRIMARY"
    assert tags["source"] == "Database"
    assert tags["provider"] == "live test"
    assert tags["year"] == "2024"
    assert tags["electricity"] == "RESIDUAL"
    assert tags["country"] == "GB"
    assert tags["energy_source"] == "Live test mix; one"   # comma kept out
    assert tags["switch"] == SWITCH
    structure = live.engine.process_structure(bridge["id"])
    assert str(structure["valid_from"]).startswith("2024-01-01")
    assert str(structure["valid_until"]).startswith("2024-12-31")


def test_the_bridge_has_two_providers_on_one_flow(live, bridge, providers):
    structure = live.engine.process_structure(bridge["id"])
    links = {l["provider_id"]: l["formula"] for l in structure["links"]}
    assert links == {providers[0]: f"1 - {SWITCH}", providers[1]: SWITCH}


@pytest.mark.slow
def test_the_switch_moves_the_bridge_to_its_second_provider(live, bridge):
    """Builds one product system (about two minutes on ecoinvent)."""
    methods = live.engine.list_impact_methods()
    names = [m["name"] for m in methods.get("methods", [])]
    method = next((n for n in ("IPCC 2021", EPD_METHOD) if n in names), None)
    if method is None:
        pytest.skip("no impact method to calculate with")
    r = live.session.run(f'SYSTEM "{bridge["name"]}"\n'
                         f'VALIDATE "{bridge["name"]}"')
    assert r.ok, f"{r.errors}\n{r.text}"
    main = live.engine.process_contributions(bridge["name"], method)
    assert "error" not in main, main
    other = live.engine.process_contributions(
        bridge["name"], method, parameters={SWITCH: 1.0})
    assert "error" not in other, other
    differ = [c for c in main["totals"]
              if abs(main["totals"][c] - other["totals"][c])
              > 1e-9 * max(abs(main["totals"][c]), 1e-30)]
    assert differ, "the switch changed nothing: both runs give the same totals"


# ── 3. a small EPD, end to end ───────────────────────────────

@pytest.mark.slow
def test_a_small_epd_end_to_end(live, bridge, tmp_path):
    if not _has_epd_method(live):
        pytest.skip(
            f"this database has no '{EPD_METHOD}' method (the EN 15804+A2 "
            f"indicator set, 38 categories). Import the LCIA method pack "
            f"that holds it to run the live EPD test. The method check is "
            f"not loosened to run against another method.")
    out = tmp_path / "live_epd.csv"
    exempt = ('  EXEMPT C AND D\n    INTEGRATED "Live test"\n'
              '    NOT IDENTIFIABLE "Live test"\n'
              '    END OF LIFE SCENARIOS "Live test"\n  END EXEMPT\n')
    program = _block(modules="A1, A2, A3", extra=exempt) + f'''
CONFIRM DELETE ON
MODULE A1
  TOTAL "Raw material supply"
END MODULE
MODULE A2
  TOTAL "Transport"
END MODULE
MODULE A3
  MAKE PROCESS "Manufacturing"
    DESCRIPTION "olcaBASIC live EPD test"
    OUTPUT MAKE FLOW "olcaBASIC live EPD product", 1, kg, PRODUCT
    INPUT USE PROCESS "{bridge["name"]}", 2, kWh
  END PROCESS
  TOTAL "Manufacturing"
END MODULE
EPD SYSTEMS
EPD CHECK
EPD CALCULATE
EPD REPORT "{out.as_posix()}"
'''
    names = ["A1: Raw material supply", "A2: Transport", "A3: Manufacturing",
             "A3 | Manufacturing"]
    try:
        r = live.session.run(program)
        assert r.ok, f"{r.errors}\n{r.text}"
        with open(out, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        start = rows.index(["Results"])
        assert rows[start + 1] == ["Indicator", "Unit", "A1", "A2", "A3",
                                   "A1-A3"]
        results = rows[start + 2:]
        assert len(results) == 38
        for row in results:
            a1, a2, a3, stage = (float(v) for v in row[2:])
            assert a1 == 0 and a2 == 0
            assert abs(stage - a3) <= 1e-9 * max(abs(a3), 1e-30)
        assert any(float(row[4]) != 0 for row in results)
    finally:
        cleanup = "CONFIRM DELETE ON\n" + "\n".join(
            f'DELETE SYSTEM "{n}"' for n in names if ":" in n) + "\n" + "\n".join(
            f'DELETE PROCESS "{n}"' for n in names)
        live.session.run(cleanup)
