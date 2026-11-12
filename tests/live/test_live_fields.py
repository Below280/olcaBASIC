"""
Live tests: the wider process, flow and system fields against a real
openLCA.

    pytest -m live

One small model in the folder "00: olcaBASIC live fields": a process
with two products, one input (taken from the private baseline program),
uncertainty, a cost, an exchange site, allocation factors and
documentation; and its product system, with a parameter set and an
analysis group. Each field is read back from openLCA, and the ones a
calculation uses are checked through the results.

The system and the process are deleted at the end. The two product
flows and the global parameter stay (see test_live_baseline.py).
"""

import re

import pytest

from test_live_baseline import close

pytestmark = pytest.mark.live

FOLDER = "00: olcaBASIC live fields"
NAME = "olcaBASIC live fields product"
CO = "olcaBASIC live fields co-product"
PARAM = "olcabasic_live_fields_kwh"
# Every background input goes through a bridge (0.4.0). The bridge stays
# in the folder after the run and is reused by the next one.
BRIDGE_SHORT = "olcaBASIC live fields electricity"
BRIDGE = f"BRIDGE | {BRIDGE_SHORT} | kWh"


def near(a, b, tol=1e-6):
    return close(a, b, tol) or abs(a - b) < 1e-12


@pytest.fixture(scope="module")
def provider(runner, baseline):
    """Name and location of the electricity process the baseline
    program uses."""
    m = re.search(r'USE PROCESS "([^"]+)".*kWh LOCATION "([^"]+)"',
                  baseline["program_template"])
    if not m:
        pytest.skip("the baseline program has no electricity input to use")
    return m.groups()


@pytest.fixture(scope="module")
def currency(runner):
    """The reference currency of the database: (name, id)."""
    import olca_schema as o
    client = runner.engine.client
    for d in client.get_descriptors(o.Currency):
        cur = client.get(o.Currency, d.id)
        if cur.ref_currency is None or cur.ref_currency.id == cur.id:
            return cur.name, cur.id
    pytest.skip("the database has no reference currency")


@pytest.fixture(scope="module")
def people(runner):
    """An actor and a source that are in the database, by UUID."""
    import olca_schema as o
    client = runner.engine.client
    actors = client.get_descriptors(o.Actor)
    sources = client.get_descriptors(o.Source)
    if not actors or not sources:
        pytest.skip("the database has no actors or no sources")
    return actors[0], sources[0]


@pytest.fixture(scope="module")
def model(runner, baseline, provider, currency, people):
    method = next(iter(baseline["calculate"]))
    name, location = provider
    actor, source = people
    cleanup = (f'CLOSE RESULT ALL\nCONFIRM DELETE ON\n'
               f'DELETE SYSTEM "{NAME}"\nDELETE PROCESS "{NAME}"')
    runner.session.run(cleanup)
    family = runner.engine.database_family
    if family not in ("ecoinvent", "flcac"):
        runner.run('DATABASE FAMILY "ecoinvent"')
    r = runner.session.run(f'''
SET PROCESS FOLDER "{FOLDER}"
SET FLOW FOLDER "{FOLDER}"
LET {PARAM} = 2 UNCERTAINTY UNIFORM 1.5, 2.5
BRIDGE "{BRIDGE_SHORT}", kWh
  PROVIDER "{name}" LOCATION "{location}"
END BRIDGE
MAKE PROCESS "{NAME}"
  DESCRIPTION "olcaBASIC live test of process fields"
  TYPE UNIT
  INFRASTRUCTURE
  OUTPUT MAKE FLOW "{NAME}", 1, kg, PRODUCT COST 10 CURRENCY "{currency[1]}"
  OUTPUT MAKE FLOW "{CO}", 0.5, kg
  INPUT USE PROCESS "{BRIDGE}", {PARAM}, kWh UNCERTAINTY TRIANGLE 1.5, 2, 2.5 BASE UNCERTAINTY 0.0006 COST 0.3 CURRENCY "{currency[1]}" SITE "{location}"
  DEFAULT ALLOCATION PHYSICAL
  ALLOCATION PHYSICAL
    "{NAME}", 0.7
    "{CO}", 0.3
  END ALLOCATION
  ALLOCATION ECONOMIC
    "{NAME}", 0.9
    "{CO}", 0.1
  END ALLOCATION
  DOCUMENT
    TIME "The year 2025"
    GEOGRAPHY "A test site"
    TECHNOLOGY "A test technology"
    VALID FROM "01/01/2025"
    VALID UNTIL "31/12/2030"
    CREATED "12/11/2026"
    COPYRIGHT YES
    INTENDED APPLICATION "A live test"
    OWNER "{actor.id}"
    SOURCE "{source.id}"
    REVIEW "Independent review" REVIEWER "{actor.id}" DETAILS "A test review"
  END DOCUMENT
END PROCESS
SYSTEM "{NAME}"
  PARAMETER SET "Double"
    {PARAM} = 4
  END PARAMETER SET
  ANALYSIS GROUP "Energy"
    "{name}" LOCATION "{location}"
  END ANALYSIS GROUP
END SYSTEM
VALIDATE "{NAME}"
''')
    assert r.ok, f"{r.errors}\n{r.text}"
    found = runner.engine.process_candidates(NAME)
    assert len(found) == 1
    yield {"id": found[0]["id"], "method": method, "provider": provider,
           "currency": currency, "actor": actor, "source": source}
    runner.session.run(cleanup)


def test_process_fields_are_read_back(runner, model):
    got = runner.engine.get_process_fields(model["id"])
    assert "error" not in got, got
    assert got["type"] == "UNIT" and got["infrastructure"] is True
    assert got["default_allocation"] == "PHYSICAL"
    by = {e["flow"]: e for e in got["exchanges"]}
    product = by[NAME]
    assert product["cost"]["value"] == 10
    assert product["cost"]["currency"] == model["currency"][0]
    elec = next(e for e in got["exchanges"] if e["is_input"])
    assert elec["uncertainty"]["kind"] == "TRIANGLE"
    assert elec["uncertainty"]["values"] == [1.5, 2.0, 2.5]
    assert elec["base_uncertainty"] == 0.0006
    assert elec["cost"]["value"] == 0.3 and elec["site"]
    physical = {f["product"]: f["value"] for f in got["allocation"]["PHYSICAL"]}
    economic = {f["product"]: f["value"] for f in got["allocation"]["ECONOMIC"]}
    assert physical == {NAME: 0.7, CO: 0.3}
    assert economic == {NAME: 0.9, CO: 0.1}
    doc = got["document"]
    assert doc["time_description"] == "The year 2025"
    assert doc["geography_description"] == "A test site"
    assert doc["valid_from"] == "2025-01-01"
    assert doc["valid_until"] == "2030-12-31"
    assert doc["creation_date"] == "2026-11-12"
    assert doc["is_copyright_protected"] is True
    assert doc["data_set_owner"] == model["actor"].name
    assert doc["sources"] == [model["source"].name]
    assert doc["reviews"][0]["type"] == "Independent review"
    assert doc["reviews"][0]["reviewers"] == [model["actor"].name]


def test_the_global_parameter_carries_its_uncertainty(runner, model):
    import olca_schema as o
    client = runner.engine.client
    d = next(p for p in client.get_descriptors(o.Parameter)
             if p.name == PARAM)
    param = client.get(o.Parameter, d.id)
    assert param.uncertainty.distribution_type == \
        o.UncertaintyType.UNIFORM_DISTRIBUTION
    assert (param.uncertainty.minimum, param.uncertainty.maximum) == (1.5, 2.5)


def test_show_reads_the_fields_in_the_form_they_are_typed(runner, model):
    r = runner.session.run(f'SHOW PROCESS "{NAME}" FIELDS')
    assert r.ok, r.errors
    assert "UNCERTAINTY TRIANGLE 1.5, 2, 2.5" in r.text
    assert "ALLOCATION PHYSICAL" in r.text and f'"{CO}", 0.3' in r.text
    assert 'VALID FROM "2025-01-01"' in r.text
    r = runner.session.run(f'SHOW SYSTEM "{NAME}" SETS')
    assert 'PARAMETER SET "Double"' in r.text and f"{PARAM} = 4" in r.text
    r = runner.session.run(f'SHOW SYSTEM "{NAME}" GROUPS')
    assert 'ANALYSIS GROUP "Energy"' in r.text


def totals(result):
    return {i["category"]: i["amount"] for i in result["impacts"]}


@pytest.fixture(scope="module")
def unallocated(runner, model):
    return totals(runner.run(
        f'CALCULATE "{NAME}" USING "{model["method"]}" ALLOCATE NONE'))


def test_allocation_factors_scale_the_result(runner, model, unallocated):
    method = model["method"]
    for option, share in (("ALLOCATE PHYSICAL", 0.7),
                          ("ALLOCATE ECONOMIC", 0.9), ("", 0.7)):
        got = totals(runner.run(
            f'CALCULATE "{NAME}" USING "{method}" {option}'))
        for cat, whole in unallocated.items():
            assert near(got[cat], share * whole), (option, cat)


def test_the_parameter_set_doubles_the_electricity(runner, model, unallocated):
    got = totals(runner.run(
        f'CALCULATE "{NAME}" USING "{model["method"]}" ALLOCATE NONE '
        f'PARAMETER SET "Double"'))
    for cat, whole in unallocated.items():
        assert near(got[cat], 2 * whole), cat


def test_stored_scenarios_run_from_the_system(runner, model):
    got = runner.run(f'RUN SCENARIOS ON "{NAME}" USING "{model["method"]}" '
                     f'ALLOCATE NONE FROM SYSTEM')
    assert list(got["results"]) == ["Double"]


def test_results_by_analysis_group(runner, model, unallocated):
    runner.run(f'CALCULATE "{NAME}" USING "{model["method"]}" ALLOCATE NONE')
    cat, total = next((c, v) for c, v in unallocated.items() if abs(v) > 1e-12)
    rows = runner.run(f'RESULT IMPACTS BY GROUP CATEGORY "{cat}"')["rows"]
    by = {r["group"]: r["amount"] for r in rows}
    assert near(sum(by.values()), total)
    # everything comes through the electricity; the process itself
    # emits nothing
    assert near(by["Energy"], total)
    flows = runner.run("RESULT FLOWS TOP 1")["rows"]
    rows = runner.run(
        f'RESULT FLOWS BY GROUP FLOW "{flows[0]["flow_id"]}"')["rows"]
    assert near(sum(r["amount"] for r in rows), flows[0]["amount"])


def test_costs_on_the_exchanges_reach_the_result(runner, model):
    runner.run(f'CALCULATE "{NAME}" USING "{model["method"]}" ALLOCATE NONE '
               f'WITH COSTS')
    direct = runner.run(f'RESULT COSTS OF PROCESS "{NAME}" DIRECT')
    # 0.3 for the electricity, less 10 of revenue for the product
    assert near(direct["rows"][0]["amount"], 0.3 - 10)
    groups = runner.run("RESULT COSTS BY GROUP")["rows"]
    total = runner.run("RESULT COSTS")["rows"][0]["amount"]
    assert near(sum(r["amount"] for r in groups), total)


def test_montecarlo_runs_as_a_simulation(runner, model):
    got = runner.run(f'MONTECARLO "{NAME}" USING "{model["method"]}" RUNS 5')
    stats = got["statistics"]
    assert got["iterations"] == 5
    assert any(s["std_dev"] > 0 for s in stats.values())


def test_edit_removes_and_changes_fields(runner, model):
    r = runner.session.run(f'''
EDIT PROCESS "{NAME}"
  UPDATE INPUT "{BRIDGE}" UNCERTAINTY NONE NO COST NO SITE
  INFRASTRUCTURE NO
  REMOVE ALLOCATION ECONOMIC
  DOCUMENT
    TIME "The year 2026"
  END DOCUMENT
END EDIT''')
    assert r.ok, f"{r.errors}\n{r.text}"
    got = runner.engine.get_process_fields(model["id"])
    elec = next(e for e in got["exchanges"] if e["is_input"])
    assert elec["uncertainty"] is None and elec["cost"] is None
    assert elec["site"] == "" and got["infrastructure"] is False
    assert "ECONOMIC" not in got["allocation"]
    assert got["document"]["time_description"] == "The year 2026"
    assert got["document"]["geography_description"] == "A test site"


def test_flow_fields(runner, model):
    r = runner.session.run(f'''
EDIT FLOW "{CO}"
  SET CAS "50-00-0"
  SET FORMULA "CH2O"
  SET SYNONYMS "live test synonym"
  SET INFRASTRUCTURE YES
END EDIT''')
    assert r.ok, f"{r.errors}\n{r.text}"
    found = runner.engine.search_flows(CO)["flows"]
    got = runner.engine.get_flow_fields(found[0]["id"])
    assert (got["cas"], got["formula"], got["synonyms"]) == (
        "50-00-0", "CH2O", "live test synonym")
    assert got["infrastructure"] is True
