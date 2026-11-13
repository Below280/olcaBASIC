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
from live_support import matching_baseline

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
    runner.session.close()


@pytest.fixture(scope="module")
def providers(live):
    """Two processes with the same name at different locations, taken
    from the first USE PROCESS ... LOCATION line of the private
    baseline program. Returns (first id, second id)."""
    program = matching_baseline(live.engine)["program_template"]
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
    methods = [m["name"] for m in
               live.engine.list_impact_methods().get("methods", [])]
    other = next((n for n in methods if "15804" not in n), None)
    if other is None:
        pytest.skip("every impact method in this database is an EN 15804 one")
    r = live.session.run(_block(method=other))
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
EPD SAVE REPLACE
'''
    names = ["A1: Raw material supply", "A2: Transport", "A3: Manufacturing",
             "A3 | Manufacturing"]
    epd_name = "olcaBASIC live EPD"
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

        # EPD SAVE: openLCA's own Epd entity, one stored result per
        # module, each with the report's numbers
        import olca_schema as o
        client = live.engine.client
        found = [d for d in client.get_descriptors(o.Epd)
                 if d.name == epd_name]
        assert len(found) == 1
        epd = client.get(o.Epd, found[0].id)
        assert [m.name for m in epd.modules] == ["A1", "A2", "A3"]
        assert epd.product is not None and epd.product.amount == 1.0
        assert epd.product.flow.name == "A3: Manufacturing"
        by_category = {row[0]: float(row[4]) for row in results}
        for module in epd.modules:
            stored = client.get(o.Result, module.result.id)
            assert stored.name == f"{epd_name} | {module.name}"
            assert len(stored.impact_results) == 38
            if module.name == "A3":
                for i in stored.impact_results:
                    want = by_category[i.indicator.name]
                    assert abs(i.amount - want) <= 1e-9 * max(abs(want),
                                                              1e-30)
        # one analysis group per module system, named after the module
        systems = {d.name: d.id
                   for d in client.get_descriptors(o.ProductSystem)}
        a3 = client.get(o.ProductSystem, systems["A3: Manufacturing"])
        assert [g.name for g in a3.analysis_groups] == ["A3"]
        assert {p.name for p in a3.analysis_groups[0].processes} == {
            "A3: Manufacturing", "A3 | Manufacturing"}
        assert live.session.open_results == []
    finally:
        live.session.run(
            f'CONFIRM DELETE ON\nDELETE EPD "{epd_name}"\n' + "\n".join(
                f'DELETE RESULT "{epd_name} | {m}"'
                for m in ("A1", "A2", "A3")))
        cleanup = "CONFIRM DELETE ON\n" + "\n".join(
            f'DELETE SYSTEM "{n}"' for n in names if ":" in n) + "\n" + "\n".join(
            f'DELETE PROCESS "{n}"' for n in names)
        live.session.run(cleanup)


# ── 4. PARAMETERISE PROCESS, on a bridge of our own ──────────

def test_parameterise_needs_confirm_and_keeps_the_amount(live, providers):
    """Only ever run on a process this test created: a plain bridge,
    whose one input has a fixed amount of 1."""
    name = "BRIDGE | olcaBASIC live parameterise | kWh"
    cleanup = f'CONFIRM DELETE ON\nDELETE PROCESS "{name}"'
    live.session.run(cleanup)
    try:
        r = live.session.run(f'''BRIDGE "olcaBASIC live parameterise", kWh
  FOLDER "{FOLDER}/Bridges"
  PROVIDER "{providers[0]}"
END BRIDGE''')
        assert r.ok, f"{r.errors}\n{r.text}"
        found = live.engine.process_candidates(name)
        assert len(found) == 1
        pid = found[0]["id"]

        r = live.session.run(f'PARAMETERISE PROCESS "{name}"')
        assert not r.ok
        assert "refused without CONFIRM" in r.errors[0]["message"]
        assert "1 fixed amount " in r.errors[0]["message"]
        before = live.engine.process_structure(pid)
        assert before["parameters"] == {}
        assert [l["formula"] for l in before["links"]] == [None]

        r = live.session.run(f'PARAMETERISE PROCESS "{name}" CONFIRM')
        assert r.ok, f"{r.errors}\n{r.text}"
        after = live.engine.process_structure(pid)
        assert list(after["parameters"].values()) == [1.0]
        assert [l["formula"] for l in after["links"]] == list(after["parameters"])
        assert after["links"][0]["provider_id"] == providers[0]

        r = live.session.run(f'PARAMETERISE PROCESS "{name}" CONFIRM')
        assert r.ok and "Nothing to parameterise" in r.text
    finally:
        live.session.run(cleanup)


# ── 5. the EPD toolkit on a small EPD under a programme ──────

TOOLKIT_FOLDER = "00: olcaBASIC live EPD toolkit"
TOOLKIT_PARAM = "olcabasic_live_toolkit_kwh"


@pytest.mark.slow
def test_the_toolkit_on_a_small_epd(live, bridge, tmp_path):
    """Data quality over the impact indicators with the residual check
    and ratings, the register, the assessment table, group sensitivity
    and the model export, against the real EN 15804+A2 method. The
    model is the live EPD test model with a programme named: one
    process in A3 that buys electricity through the bridge.

    The global parameter stays in the database (deleting one on a
    server before openLCA 2.7 means reading every process)."""
    if not _has_epd_method(live):
        pytest.skip(f"this database has no '{EPD_METHOD}' method")
    import json
    sheet = tmp_path / "register.csv"
    table = tmp_path / "assessment.md"
    sens = tmp_path / "sensitivity.csv"
    model = tmp_path / "model.json"
    report = tmp_path / "report.csv"
    document = tmp_path / "epd.md"
    ratings = ('  RATING GEOGRAPHY "Good" REASON "Live test, same market"\n'
               '  RATING TECHNOLOGY "Good" REASON "Live test"\n'
               '  RATING TIME "Fair" REASON "Live test"\n')
    name = "olcaBASIC live toolkit EPD"
    names = ["A1: Raw material supply", "A2: Transport", "A3: Manufacturing",
             "A3 | Manufacturing"]

    def cleanup():
        client = live.engine.client
        import olca_schema as o
        code = ["CONFIRM DELETE ON", "EPD CLOSE"]
        for cls, word in ((o.ProductSystem, "SYSTEM"), (o.Process, "PROCESS")):
            for d in client.get_descriptors(cls):
                if (d.category or "").startswith(TOOLKIT_FOLDER) \
                        and d.name in names:
                    code.append(f'DELETE {word} "{d.id}"')
        live.session.run("\n".join(code))

    cleanup()
    program = f'''
LET {TOOLKIT_PARAM} = 2
EPD "{name}"
  PROGRAMME "IES" GPI "5.1.0"
  PCR "Live test PCR" VERSION "1"
  DATABASE "Live test database" VERSION "1"
  DECLARED UNIT 1, kg
  METHOD "{EPD_METHOD}"
  FOLDER "{TOOLKIT_FOLDER}"
  MODULES A1, A2, A3
  BIOGENIC CARBON NO
  EXEMPT C AND D
    INTEGRATED "Live test"
    NOT IDENTIFIABLE "Live test"
    END OF LIFE SCENARIOS "Live test"
  END EXEMPT
END EPD
EDIT PROCESS "{bridge["id"]}"
{ratings}END EDIT
MODULE A1
  TOTAL "Raw material supply"
END MODULE
MODULE A2
  TOTAL "Transport"
END MODULE
MODULE A3
  MAKE PROCESS "Manufacturing"
    DESCRIPTION "olcaBASIC live EPD toolkit test"
    DATA PRIMARY SOURCE "Collected" PROVIDER "EPD owner" YEAR 2025
{ratings}    OUTPUT MAKE FLOW "olcaBASIC live toolkit product", 1, kg, PRODUCT
    INPUT USE PROCESS "{bridge["name"]}", {TOOLKIT_PARAM}, kWh
  END PROCESS
  TOTAL "Manufacturing"
END MODULE
EPD SYSTEMS
EPD CHECK
EPD CALCULATE
EPD DQ SHEET "{sheet.as_posix()}"
EPD DATA QUALITY
EPD DQ TABLE "{table.as_posix()}"
EPD SENSITIVITY BY 10% SAVE "{sens.as_posix()}"
  GROUP "Electricity" VARY {TOOLKIT_PARAM}
END EPD SENSITIVITY
EPD EXPORT MODEL "{model.as_posix()}"
EPD REPORT "{report.as_posix()}"
EPD DOCUMENT "{document.as_posix()}"
  OWNER "Live test owner"
  OWNER ADDRESS "Live test address"
  OWNER CONTACT "live@example.com"
  OWNER DESCRIPTION "Live test organisation."
  PRODUCT DESCRIPTION "Live test product."
  PRODUCT IDENTIFICATION "Live test identification"
  MANUFACTURING "One process that uses electricity."
  SITE "Live test town, United Kingdom"
  CONTENT "Live test material", 1 kg
  SVHC NONE
  GEOGRAPHY A1, A2, A3 "GB"
  OMITTED A4, A5, B1, B2, B3, B4, B5, B6, B7 "Live test"
END EPD DOCUMENT
'''
    try:
        r = live.session.run(program)
        assert r.ok, f"{r.errors}\n{r.text[-4000:]}"
        epd = live.session.runtime.epd
        calls = {c["call"]: c["result"] for c in r.data}

        # the impact indicators are found by their codes in the real method
        dq = calls["epd_data_quality"]
        assert dq["passed"] and dq["errors"] == []
        assert dq["impact_indicators"] == 20
        assert dq["indicators_reported"] == 38
        from olcabasic.workflows import en15804
        assert en15804.indicator_code(epd.gwp_indicator) == "GWP-GHG"
        assert epd.category_with_code("GWP-biogenic")
        # everything comes through the bridge, so it carries the result
        assert dq["rows"][0]["process"] == bridge["name"]
        assert dq["rows"][0]["share_of_gwp"] > 99.0
        assert [c["process"] for c in dq["coverage"]] == [bridge["name"]]

        # the register names what stands behind the bridge
        with open(sheet, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        row = dict(zip(rows[0], rows[1]))
        assert row["Dataset"] == bridge["name"] and row["Kind"] == "bridge"
        assert row["Background process"]
        assert row["Rating: geography"] == "Good"
        assert row["Reason: geography"] == "Live test, same market"
        text = table.read_text(encoding="utf-8")
        assert "Good. Live test, same market" in text

        # one group, one module recalculated twice; electricity is all
        # of A3, so 10% more of it is 10% more of every indicator
        s = calls["epd_sensitivity"]
        assert s["calculations"] == 2
        assert s["groups"][0]["modules"] == ["A3"]
        gwp = next(x for x in s["table"]["A to C"]
                   if x["indicator"] == epd.gwp_indicator)
        base = gwp["baseline"]
        assert base != 0
        assert abs(gwp["Electricity +10%"] - 1.1 * base) <= 1e-6 * abs(base)
        assert abs(gwp["Electricity -10%"] - 0.9 * base) <= 1e-6 * abs(base)

        # the model, written out
        data = json.loads(model.read_text(encoding="utf-8"))
        assert data["metadata"]["system_count"] == 3
        made = [p for p in data["processes"].values()
                if p["name"] == "A3 | Manufacturing"]
        assert len(made) == 1
        ex = next(x for x in made[0]["exchanges"] if x["default_provider"])
        assert ex["default_provider"]["name"] == bridge["name"]
        assert ex["amount_formula"] == TOOLKIT_PARAM
        assert any(g["name"] == TOOLKIT_PARAM
                   for g in data["global_parameters"])
        # the EPD document: every result of the real method, a draft
        # until the statements and the verification are given
        doc = document.read_text(encoding="utf-8")
        assert doc.startswith("> **DRAFT, not for publication.**")
        assert "## Environmental performance" in doc
        assert "| GWP-GHG |" in doc and "| X | X | X | ND |" in doc
        assert "exemption of EN 15804+A2, 5.2" in doc
        assert calls["epd_document"]["draft"] is True
        assert live.session.open_results == []
    finally:
        cleanup()
