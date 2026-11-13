"""Results stay open, and every RESULT query reads from one.

The model is the Widget of test_interpreter_lca: 1 kg of product from
2.5 kWh of electricity (GB: 0.25 kg CO2-eq fossil per kWh), 0.8 kg of
steel (2.0 per kg) and 0.5 kg of CO2 emitted by the process itself.
Electricity and steel each come through a bridge (B_ELEC, B_STEEL), so
the system has five processes: the widget, two bridges and the two
background processes behind them. A bridge passes its input straight
through: its direct impacts are zero and its upstream impacts are those
of what stands behind it. Every expected number below is worked out by
hand from that.
"""

import csv
import json

import pytest
import olca_schema as o

from fake_client import ELECTRICITY, FUTURE_VERSION, STEEL, FakeResult
from olcabasic import Session
from olcabasic.engine.results import MAX_OPEN_RESULTS
from test_interpreter_lca import (B_ELEC, B_ELEC_DE, B_STEEL, WIDGET,
                                  WIDGET_FOSSIL, process)

EF = "EF v3.1"
FOSSIL = "Climate change: fossil"
CALC = f'CALCULATE "Widget" USING "{EF}"\n'


@pytest.fixture
def session(client):
    s = Session(client=client)
    assert s.run(WIDGET).ok
    return s


@pytest.fixture
def calc(session):
    r = session.run(CALC)
    assert r.ok, r.errors
    return session


def query(session, code):
    """The structured result of one RESULT command."""
    r = session.run(code)
    assert r.ok, r.errors
    return r.data[-1]["result"]


def rows_by(result, key):
    return {row[key]: row for row in result["rows"]}


def err(r):
    assert not r.ok
    return r.errors[0]


def calculations(client) -> int:
    return sum(1 for c in client.calls if c[0] in ("calculate", "simulate"))


# ── results stay open ────────────────────────────────────────

def test_calculate_keeps_its_result_open(session, client):
    r = session.run(CALC)
    assert r.ok and client.undisposed() == 1
    assert session.open_results == [""]
    assert r.data[-1]["result"]["open_as"] == "(current)"
    assert "handle" not in r.data[-1]["result"]
    assert any("stays open" in w["message"] for w in r.warnings)


def test_the_note_about_open_results_is_said_once(session):
    session.run(CALC)
    assert not any("stays open" in w["message"]
                   for w in session.run(CALC).warnings)


def test_next_calculate_closes_the_previous_result(session, client):
    session.run(CALC)
    session.run(CALC)
    assert len(client.results) == 2 and client.undisposed() == 1


def test_close_result(calc, client):
    r = calc.run("CLOSE RESULT")
    assert r.ok and "Closed the current result" in r.text
    assert client.undisposed() == 0 and calc.open_results == []
    assert "No result is open" in calc.run("CLOSE RESULT").text


def test_named_result_stays_beside_the_current_one(session, client):
    session.run(CALC.strip() + " AS base")
    r = session.run(CALC)
    assert "Result kept open as" not in r.text
    assert sorted(session.open_results) == ["", "base"]
    assert client.undisposed() == 2
    assert session.run("CLOSE RESULT base").ok
    assert session.open_results == [""] and client.undisposed() == 1


def test_naming_a_result_again_replaces_it(session, client):
    session.run(CALC.strip() + " AS base")
    session.run(CALC.strip() + " AS base")
    assert session.open_results == ["base"] and client.undisposed() == 1


def test_close_result_all(session, client):
    for name in ("a", "b", "c"):
        session.run(CALC.strip() + f" AS {name}")
    r = session.run("CLOSE RESULT ALL")
    assert "Closed 3 results" in r.text and client.undisposed() == 0


def test_closing_an_unknown_name_is_an_error(calc):
    e = err(calc.run("CLOSE RESULT nothere"))
    assert "No open result is called 'nothere'" in e["message"]
    assert "AS nothere" in e["hint"]


def test_no_more_than_five_results(session, client):
    assert MAX_OPEN_RESULTS == 5
    for i in range(5):
        assert session.run(CALC.strip() + f" AS r{i}").ok
    e = err(session.run(CALC.strip() + " AS r5"))
    assert e["line"] == 1
    assert "5 results are open already" in e["message"]
    for i in range(5):
        assert f"r{i}" in e["message"]
    assert "CLOSE RESULT" in e["hint"]
    assert client.undisposed() == 5 and len(client.results) == 5
    # the unnamed result counts too
    e = err(session.run(CALC))
    assert "5 results are open already" in e["message"]
    # replacing one of the five is fine
    assert session.run(CALC.strip() + " AS r0").ok


def test_reset_closes_everything(session, client):
    session.run(CALC.strip() + " AS base")
    session.run(CALC)
    session.reset()
    assert client.undisposed() == 0 and session.open_results == []


def test_session_close_and_with_block(client):
    with Session(client=client) as s:
        s.run(WIDGET + CALC)
        assert client.undisposed() == 1
    assert client.undisposed() == 0
    s.run(CALC)
    assert s.close() == 1 and client.undisposed() == 0


def test_a_discarded_session_takes_its_results_with_it(client):
    s = Session(client=client)
    s.run(WIDGET + CALC)
    assert client.undisposed() == 1
    del s
    import gc
    gc.collect()
    assert client.undisposed() == 0


def test_a_program_run_from_a_file_closes_its_results(run, client):
    run(WIDGET + CALC + 'RESULT IMPACTS\n')
    assert client.undisposed() == 0


def test_run_file_closes_results_even_after_an_error(interp, client):
    from olcabasic.errors import BasicError
    with pytest.raises(BasicError, match="no category called"):
        interp.run_program(WIDGET + CALC
                           + 'RESULT IMPACTS CATEGORY "no such"\n')
    assert client.undisposed() == 0


def test_an_error_later_in_a_session_run_leaves_the_result_usable(calc, client):
    assert not calc.run('RESULT IMPACTS CATEGORY "no such"').ok
    assert client.undisposed() == 1
    assert calc.run("RESULT IMPACTS").ok


def test_a_failure_inside_the_calculation_disposes_the_result(
        session, client, monkeypatch):
    def boom(self):
        raise RuntimeError("openLCA fell over")
    monkeypatch.setattr(FakeResult, "get_total_impacts", boom)
    e = err(session.run(CALC))
    assert "openLCA fell over" in e["message"]
    assert len(client.results) == 1 and client.undisposed() == 0
    assert session.open_results == []


def test_result_without_a_calculation(session):
    e = err(session.run("RESULT IMPACTS"))
    assert e["message"] == "No result is open."
    assert "CALCULATE" in e["hint"]


def test_result_in_unknown_name(calc):
    e = err(calc.run("RESULT IMPACTS IN other"))
    assert "No open result is called 'other'" in e["message"]


def test_result_in_name_reads_the_named_result(session):
    session.run('LET elec = 2.5')
    session.run(CALC.strip() + " AS base")
    session.run('UPDATE PARAMETER elec = 5\n' + CALC)
    now = query(session, f'RESULT IMPACTS CATEGORY "{FOSSIL}"')
    base = query(session, f'RESULT IMPACTS CATEGORY "{FOSSIL}" IN base')
    assert base["rows"][0]["amount"] == pytest.approx(WIDGET_FOSSIL)
    assert now["rows"][0]["amount"] == pytest.approx(WIDGET_FOSSIL + 2.5 * 0.25)
    assert base["result"] == "base" and now["result"] == "(current)"


# ── the older commands reuse the current result ──────────────

def test_contribution_reuses_the_current_result(calc, client):
    r = calc.run(f'CONTRIBUTION "Widget" USING "{EF}" TOP 3')
    assert r.ok
    assert calculations(client) == 1 and client.undisposed() == 1
    cc = r.data[-1]["result"]["categories"][FOSSIL]
    assert cc["total"] == pytest.approx(WIDGET_FOSSIL)


def test_inventory_and_tree_reuse_the_current_result(calc, client):
    assert calc.run(f'INVENTORY "Widget" USING "{EF}"').ok
    assert calc.run(f'TREE "Widget" USING "{EF}" CATEGORY "{FOSSIL}"').ok
    assert calculations(client) == 1 and client.undisposed() == 1


def test_contribution_calculates_when_the_current_result_is_another(
        calc, client):
    assert calc.run('CONTRIBUTION "Widget" USING "EF v3.0" TOP 3').ok
    assert calc.run(f'CONTRIBUTION "Widget" USING "{EF}" ALLOCATE NONE').ok
    assert calculations(client) == 3
    assert client.undisposed() == 1          # only the current one


def test_contribution_without_a_current_result_disposes_its_own(
        session, client):
    assert session.run(f'CONTRIBUTION "Widget" USING "{EF}"').ok
    assert calculations(client) == 1 and client.undisposed() == 0


def test_temporary_results_do_not_count_towards_the_limit(session, client):
    for i in range(5):
        session.run(CALC.strip() + f" AS r{i}")
    assert session.run('CONTRIBUTION "Widget" USING "EF v3.0"').ok
    assert client.undisposed() == 5


def test_montecarlo_uses_a_simulation_and_disposes_it(session, client):
    client.mc_jitter = 0.1
    r = session.run(f'MONTECARLO "Widget" USING "{EF}" RUNS 30')
    assert r.ok
    assert ("simulate", client.by_name(o.ProductSystem, "Widget")[0].id) \
        in client.calls
    stats = r.data[-1]["result"]["statistics"][FOSSIL]
    assert stats["std_dev"] > 0 and stats["iterations"] == 30
    assert client.undisposed() == 0


# ── CALCULATE options ────────────────────────────────────────

def test_amount_scales_the_result(session, client):
    r = query(session, CALC.strip() + " AMOUNT 3 kg")
    fossil = next(i for i in r["impacts"] if i["category"] == FOSSIL)
    assert fossil["amount"] == pytest.approx(3 * WIDGET_FOSSIL)
    assert r["setup"]["amount"] == 3 and r["setup"]["unit"] == "kg"
    assert r["demand"]["amount"] == pytest.approx(3.0)
    # another unit of the same property
    r = query(session, CALC.strip() + " AMOUNT 500 g")
    fossil = next(i for i in r["impacts"] if i["category"] == FOSSIL)
    assert fossil["amount"] == pytest.approx(0.5 * WIDGET_FOSSIL)


def test_amount_needs_a_unit_and_a_known_one(session):
    r = session.run(CALC.strip() + " AMOUNT 3")
    assert not r.ok and "AMOUNT needs a unit" in r.errors[0]["message"]
    e = err(session.run(CALC.strip() + " AMOUNT 3 furlongs"))
    assert "Unit 'furlongs' is not in this database" in e["message"]
    e = err(session.run(CALC.strip() + " AMOUNT 0 kg"))
    assert "above zero" in e["message"]


def test_with_costs_and_regionalisation_reach_the_setup(session, client):
    session.run(CALC.strip() + " WITH COSTS WITH REGIONALISATION")
    setup = client.setups[-1]
    assert setup.with_costs is True and setup.with_regionalization is True
    session.run(CALC.strip() + " WITH REGIONALIZATION")       # US spelling
    assert client.setups[-1].with_regionalization is True
    assert not client.setups[-1].with_costs


def test_with_something_else_is_a_parse_error(session):
    r = session.run(CALC.strip() + " WITH LUCK")
    e = err(r)
    assert "WITH 'LUCK'" in e["message"] and "WITH COSTS" in e["hint"]


def test_as_needs_a_plain_word(session):
    assert "AS needs a name" in err(session.run(
        CALC.strip() + ' AS "base"'))["message"]
    assert "cannot be called ALL" in err(session.run(
        CALC.strip() + " AS all"))["message"]


def test_options_in_any_order(session, client):
    assert session.run(f'CALCULATE "Widget" USING "{EF}" AS x WITH COSTS '
                       f'AMOUNT 2 kg ALLOCATE NONE').ok
    setup = client.setups[-1]
    assert setup.amount == 2 and setup.with_costs
    assert setup.allocation == o.AllocationType.NO_ALLOCATION


# ── RESULT IMPACTS, CATEGORIES, PROCESSES, DEMAND ────────────

def test_result_impacts(calc):
    r = query(calc, "RESULT IMPACTS")
    assert r["query"] == "impacts" and r["system"] == "Widget"
    assert r["method"] == EF
    assert r["columns"] == ["category", "amount", "unit"]
    by = rows_by(r, "category")
    assert len(by) == 6
    assert by[FOSSIL]["amount"] == pytest.approx(2.725)
    assert by[FOSSIL]["unit"] == "kg CO2-Eq"
    # 2.5 x (0.25 + 0.001) + 0.8 x (2.0 + 0.01) + 0.5
    assert by["Climate change"]["amount"] == pytest.approx(2.7355)
    assert by["Acidification"]["amount"] == pytest.approx(0.0074)


def test_result_impacts_one_category(calc, client):
    before = len(client.calls)
    r = query(calc, 'RESULT IMPACTS CATEGORY "Acidification"')
    assert [row["category"] for row in r["rows"]] == ["Acidification"]
    assert r["rows"][0]["amount"] == pytest.approx(2.5 * 0.0004 + 0.8 * 0.008)
    assert calculations(client) == 1


def test_category_by_unique_part_and_ambiguous_part(calc):
    r = query(calc, 'RESULT IMPACTS CATEGORY "acidif"')
    assert r["rows"][0]["category"] == "Acidification"
    e = err(calc.run('RESULT IMPACTS CATEGORY "Climate change:"'))
    assert "matches 2 categories" in e["message"]
    assert "Climate change: fossil" in e["message"]
    # an exact name wins over the names that contain it
    assert query(calc, 'RESULT IMPACTS CATEGORY "Climate change"')[
        "rows"][0]["category"] == "Climate change"
    e = err(calc.run('RESULT IMPACTS CATEGORY "Ozone"'))
    assert "no category called 'Ozone'" in e["message"]
    assert "RESULT CATEGORIES" in e["hint"]


def test_result_categories_processes_demand(calc):
    cats = query(calc, "RESULT CATEGORIES")
    assert len(cats["rows"]) == 6 and cats["rows"][0]["unit"]
    procs = query(calc, "RESULT PROCESSES")
    names = {row["process"] for row in procs["rows"]}
    assert names == {"Widget", B_ELEC, B_STEEL, ELECTRICITY, STEEL}
    assert rows_by(procs, "process")[ELECTRICITY]["location"] == "GB"
    demand = query(calc, "RESULT DEMAND")
    assert demand["rows"][0]["process"] == "Widget"
    assert demand["rows"][0]["amount"] == pytest.approx(1.0)


# ── RESULT FLOWS ─────────────────────────────────────────────

CO2 = "Carbon dioxide, fossil"


def test_result_flows_total(calc):
    r = query(calc, "RESULT FLOWS")
    assert len(r["rows"]) == 1
    row = r["rows"][0]
    assert row["flow"] == CO2 and row["amount"] == pytest.approx(0.5)
    assert row["direction"] == "output" and row["unit"] == "kg"
    assert "air" in row["compartment"].lower()
    r = query(calc, f'RESULT FLOWS FLOW "{CO2}"')
    assert r["rows"][0]["amount"] == pytest.approx(0.5)
    r = query(calc, "RESULT FLOWS LIST")
    assert r["columns"] == ["flow", "compartment", "direction", "unit"]
    assert [row["flow"] for row in r["rows"]] == [CO2]


def test_result_flows_of_a_process(calc):
    total = query(calc, 'RESULT FLOWS OF PROCESS "Widget"')
    direct = query(calc, 'RESULT FLOWS OF PROCESS "Widget" DIRECT')
    assert total["rows"][0]["amount"] == pytest.approx(0.5)
    assert direct["rows"][0]["amount"] == pytest.approx(0.5)
    assert "its own exchanges" in direct["title"]
    steel = query(calc, f'RESULT FLOWS OF PROCESS "{STEEL}" DIRECT')
    assert steel["rows"][0]["amount"] == 0
    one = query(calc, f'RESULT FLOWS OF PROCESS "Widget" DIRECT FLOW "{CO2}"')
    assert one["rows"][0]["amount"] == pytest.approx(0.5)
    one = query(calc, f'RESULT FLOWS OF PROCESS "Widget" FLOW "{CO2}"')
    assert one["rows"][0]["amount"] == pytest.approx(0.5)


def test_result_flow_by_process(calc):
    r = query(calc, f'RESULT FLOW "{CO2}" BY PROCESS')
    by = rows_by(r, "process")
    assert r["total"] == pytest.approx(0.5) and r["unit"] == "kg"
    assert by["Widget"]["amount"] == pytest.approx(0.5)
    assert by["Widget"]["share_pct"] == pytest.approx(100.0)
    assert by[STEEL]["amount"] == 0
    assert r["rows"][0]["process"] == "Widget"        # largest first


def test_unknown_and_ambiguous_names_in_a_result(calc):
    e = err(calc.run('RESULT FLOWS FLOW "Methane, fossil"'))
    assert "No elementary flow called 'Methane, fossil'" in e["message"]
    assert "RESULT FLOWS LIST" in e["hint"]
    e = err(calc.run('RESULT FLOWS OF PROCESS "Gadget"'))
    assert "No process called 'Gadget' is in this result" in e["message"]
    assert "RESULT PROCESSES" in e["hint"]
    e = err(calc.run('RESULT FLOWS OF PROCESS "market for"'))
    assert "matches 2 processes" in e["message"] and "LOCATION" in e["hint"]
    e = err(calc.run('RESULT FLOWS DIRECT'))
    assert "DIRECT needs a process" in e["message"]


def test_process_by_location(session, client):
    """Two processes with one name in the same result need LOCATION."""
    assert session.run(f'''
MAKE PROCESS "Two grids"
  OUTPUT MAKE FLOW "Two grids", 1, kg, PRODUCT
  INPUT USE PROCESS "{B_ELEC}", 1, kWh
  INPUT USE PROCESS "{B_ELEC_DE}", 1, kWh
END PROCESS
SYSTEM "Two grids"
CALCULATE "Two grids" USING "{EF}"''').ok
    e = err(session.run(f'RESULT REQUIREMENTS OF PROCESS "{ELECTRICITY}"'))
    assert "matches 2 processes" in e["message"]
    assert "[GB]" in e["message"] and "[DE]" in e["message"]
    r = query(session, f'RESULT CONTRIBUTION OF PROCESS "{ELECTRICITY}" '
                       f'LOCATION "DE" CATEGORY "{FOSSIL}"')
    assert r["rows"][0]["amount"] == pytest.approx(0.40)


# ── RESULT CONTRIBUTION ──────────────────────────────────────

def test_contribution_by_process_direct_one_category(calc):
    r = query(calc, f'RESULT CONTRIBUTION BY PROCESS DIRECT CATEGORY "{FOSSIL}"')
    by = rows_by(r, "process")
    assert r["total"] == pytest.approx(2.725)
    assert by["Widget"]["amount"] == pytest.approx(0.5)
    assert by[ELECTRICITY]["amount"] == pytest.approx(0.625)
    assert by[STEEL]["amount"] == pytest.approx(1.6)
    assert by[B_ELEC]["amount"] == 0 and by[B_STEEL]["amount"] == 0
    assert sum(row["share_pct"] for row in r["rows"]) == pytest.approx(100.0)
    assert [row["process"] for row in r["rows"]][:3] == [
        STEEL, ELECTRICITY, "Widget"]


def test_contribution_by_process_with_supply_chain(calc):
    r = query(calc, f'RESULT CONTRIBUTION BY PROCESS CATEGORY "{FOSSIL}"')
    by = rows_by(r, "process")
    assert by["Widget"]["amount"] == pytest.approx(2.725)
    assert by["Widget"]["share_pct"] == pytest.approx(100.0)
    assert by[STEEL]["amount"] == pytest.approx(1.6)


def test_contribution_by_process_every_category(calc):
    r = query(calc, "RESULT CONTRIBUTION BY PROCESS DIRECT TOP 1")
    assert r["columns"][0] == "category"
    # the largest contributor in each of the six categories
    assert len(r["rows"]) == 6
    fossil = next(row for row in r["rows"] if row["category"] == FOSSIL)
    assert fossil["process"] == STEEL
    r = query(calc, "RESULT CONTRIBUTION BY PROCESS")
    assert len(r["rows"]) == 30         # six categories, five processes


def test_contribution_of_one_process(calc):
    r = query(calc, f'RESULT CONTRIBUTION OF PROCESS "{STEEL}"')
    by = rows_by(r, "category")
    assert by[FOSSIL]["amount"] == pytest.approx(1.6)
    assert by[FOSSIL]["share_pct"] == pytest.approx(1.6 / 2.725 * 100)
    assert by["Acidification"]["amount"] == pytest.approx(0.0064)
    r = query(calc, f'RESULT CONTRIBUTION OF PROCESS "Widget" DIRECT')
    assert rows_by(r, "category")[FOSSIL]["amount"] == pytest.approx(0.5)
    r = query(calc, f'RESULT CONTRIBUTION OF PROCESS "Widget" DIRECT '
                    f'CATEGORY "{FOSSIL}"')
    assert r["rows"][0]["amount"] == pytest.approx(0.5)
    r = query(calc, f'RESULT CONTRIBUTION OF PROCESS "Widget" '
                    f'CATEGORY "{FOSSIL}"')
    assert r["rows"][0]["amount"] == pytest.approx(2.725)


def test_contribution_by_flow(calc):
    r = query(calc, f'RESULT CONTRIBUTION BY FLOW CATEGORY "{FOSSIL}"')
    assert r["rows"][0]["flow"] == CO2
    # 0.5 kg x factor 1; the rest of the total comes from the canned
    # impacts of the background datasets, which have no flows
    assert r["rows"][0]["amount"] == pytest.approx(0.5)
    assert r["rows"][0]["share_pct"] == pytest.approx(0.5 / 2.725 * 100)
    r = query(calc, f'RESULT CONTRIBUTION BY FLOW CATEGORY "{FOSSIL}" '
                    f'FLOW "{CO2}"')
    assert r["rows"][0]["amount"] == pytest.approx(0.5)
    r = query(calc, "RESULT CONTRIBUTION BY FLOW")
    assert {row["category"] for row in r["rows"]} == {
        "Climate change", FOSSIL}
    e = err(calc.run(f'RESULT CONTRIBUTION BY FLOW FLOW "{CO2}"'))
    assert "needs the category" in e["message"]


def test_result_factors(calc):
    r = query(calc, f'RESULT FACTORS CATEGORY "{FOSSIL}"')
    row = r["rows"][0]
    assert row["flow"] == CO2 and row["factor"] == pytest.approx(1.0)
    assert row["factor_unit"] == "kg CO2-Eq per kg"
    r = query(calc, f'RESULT FACTORS CATEGORY "Acidification" FLOW "{CO2}"')
    assert r["rows"][0]["factor"] == 0


# ── intensity, scaling, requirements ─────────────────────────

def test_result_intensity(calc, client):
    # one unit of electricity is 1 MJ (the reference unit); 1 kWh = 3.6 MJ
    r = query(calc, f'RESULT INTENSITY OF PROCESS "{ELECTRICITY}"')
    assert rows_by(r, "category")[FOSSIL]["amount"] == pytest.approx(0.25 / 3.6)
    assert ("rpc_call", "result/impact-intensities-of") in client.calls
    r = query(calc, f'RESULT INTENSITY OF PROCESS "Widget" CATEGORY "{FOSSIL}"')
    assert r["rows"][0]["amount"] == pytest.approx(2.725)
    r = query(calc, 'RESULT INTENSITY OF PROCESS "Widget" FLOWS')
    assert r["rows"][0]["amount"] == pytest.approx(0.5)
    r = query(calc, f'RESULT INTENSITY OF PROCESS "Widget" FLOW "{CO2}"')
    assert r["rows"][0]["amount"] == pytest.approx(0.5)


def test_intensity_scales_with_nothing(session):
    """An intensity is per unit: a larger demand does not change it."""
    session.run(CALC.strip() + " AMOUNT 10 kg")
    r = query(session, f'RESULT INTENSITY OF PROCESS "Widget" CATEGORY "{FOSSIL}"')
    assert r["rows"][0]["amount"] == pytest.approx(2.725)


def test_result_scaling(calc):
    r = query(calc, "RESULT SCALING")
    by = rows_by(r, "process")
    assert by["Widget"]["amount"] == pytest.approx(1.0)
    assert by[ELECTRICITY]["amount"] == pytest.approx(2.5)   # 2.5 runs of 1 kWh
    assert by[STEEL]["amount"] == pytest.approx(0.8)
    r = query(calc, 'RESULT SCALING OF PROCESS "Widget"')
    by = rows_by(r, "process")
    assert by["Widget"]["amount"] == pytest.approx(1.0)
    assert by[B_ELEC]["amount"] == pytest.approx(-9.0)       # MJ
    assert by[B_STEEL]["amount"] == pytest.approx(-0.8)
    r = query(calc, f'RESULT SCALING OF PROCESS "{ELECTRICITY}" UNSCALED')
    # openLCA sends the whole column, zeros and all: only the entries
    # that are not zero are shown
    assert len(r["rows"]) == 1
    assert r["rows"][0]["amount"] == pytest.approx(3.6)
    r = query(calc, f'RESULT SCALING OF PROCESS "{ELECTRICITY}"')
    assert r["rows"][0]["amount"] == pytest.approx(9.0)
    assert "UNSCALED needs a process" in err(
        calc.run("RESULT SCALING UNSCALED"))["message"]


def test_result_requirements_and_totality(calc, client):
    r = query(calc, "RESULT REQUIREMENTS")
    by = rows_by(r, "process")
    assert by[ELECTRICITY]["amount"] == pytest.approx(9.0)   # MJ
    assert by[STEEL]["amount"] == pytest.approx(0.8)
    r = query(calc, f'RESULT REQUIREMENTS OF PROCESS "{STEEL}"')
    assert r["rows"][0]["amount"] == pytest.approx(0.8)
    r = query(calc, "RESULT TOTALITY")
    assert rows_by(r, "process")[ELECTRICITY]["amount"] == pytest.approx(9.0)
    assert ("rpc_call", "result/totality-factors") in client.calls
    r = query(calc, f'RESULT TOTALITY OF PROCESS "{STEEL}"')
    assert r["rows"][0]["amount"] == pytest.approx(0.8)
    assert ("rpc_call", "result/totality-factor-of") in client.calls


# ── RESULT TREE ──────────────────────────────────────────────

def test_result_tree_of_a_category(calc):
    r = query(calc, f'RESULT TREE CATEGORY "{FOSSIL}"')
    root = r["root"]
    assert root["process"] == "Widget"
    assert root["amount"] == pytest.approx(2.725)
    assert root["direct"] == pytest.approx(0.5)
    kids = {k["process"]: k for k in root["children"]}
    assert kids[B_STEEL]["amount"] == pytest.approx(1.6)
    assert kids[B_STEEL]["share_pct"] == pytest.approx(1.6 / 2.725 * 100)
    assert kids[B_ELEC]["amount"] == pytest.approx(0.625)
    # the widget, each bridge, and what stands behind each bridge
    assert [row["level"] for row in r["rows"]] == [0, 1, 2, 1, 2]
    assert r["rows"][1]["process"] == B_STEEL      # largest branch first
    assert r["rows"][2]["process"] == STEEL
    r = query(calc, f'RESULT TREE CATEGORY "{FOSSIL}" LEVELS 1')
    assert [row["level"] for row in r["rows"]] == [0, 1, 1]


def test_result_tree_top_limits_each_level(calc):
    r = query(calc, f'RESULT TREE CATEGORY "{FOSSIL}" TOP 1 LEVELS 2')
    root = r["root"]
    assert [k["process"] for k in root["children"]] == [B_STEEL]
    assert root["other"]["count"] == 1
    assert root["other"]["amount"] == pytest.approx(0.625)
    assert r["rows"][-1]["process"] == "(1 others)"
    r = query(calc, f'RESULT TREE CATEGORY "{FOSSIL}" LEVELS 0')
    assert r["root"]["children"] == []


def test_result_tree_of_a_flow(calc):
    r = query(calc, f'RESULT TREE FLOW "{CO2}"')
    assert r["root"]["amount"] == pytest.approx(0.5)
    assert r["root"]["direct"] == pytest.approx(0.5) and r["unit"] == "kg"
    assert all(k["amount"] == 0 for k in r["root"]["children"])


def test_result_tree_needs_one_subject(calc):
    r = calc.run("RESULT TREE")
    assert "takes one of CATEGORY" in err(r)["message"]


# ── costs ────────────────────────────────────────────────────

@pytest.fixture
def costed(session, client):
    """Costs on the Widget: electricity 0.50, steel 1.20, and 5.00 of
    revenue for the product, in the reference currency."""
    eur = o.Currency(id="eur", name="Euro", code="EUR", conversion_factor=1.0)
    eur.ref_currency = o.Ref(id="eur", name="Euro")
    client.store["Currency"]["eur"] = eur
    proc = process(client, "Widget")
    for ex in proc.exchanges:
        ex.currency = o.Ref(id="eur", name="Euro")
        if ex.is_quantitative_reference:
            ex.cost_value = 5.0
        elif "electricity" in client._flow_name(ex.flow.id):
            ex.cost_value = 0.5
        elif "steel" in client._flow_name(ex.flow.id):
            ex.cost_value = 1.2
    assert session.run(CALC.strip() + " WITH COSTS").ok
    return session


def test_result_costs(costed):
    r = query(costed, "RESULT COSTS")
    assert r["rows"][0]["amount"] == pytest.approx(0.5 + 1.2 - 5.0)
    assert r["rows"][0]["currency"] == "Euro"
    assert "net" in r["note"]
    r = query(costed, "RESULT COSTS BY PROCESS")
    by = rows_by(r, "process")
    assert by["Widget"]["amount"] == pytest.approx(-3.3)
    assert by[STEEL]["amount"] == 0
    r = query(costed, 'RESULT COSTS OF PROCESS "Widget"')
    assert r["rows"][0]["amount"] == pytest.approx(-3.3)
    r = query(costed, 'RESULT COSTS OF PROCESS "Widget" DIRECT')
    assert r["rows"][0]["amount"] == pytest.approx(-3.3)
    r = query(costed, 'RESULT COSTS INTENSITY OF PROCESS "Widget"')
    assert r["rows"][0]["amount"] == pytest.approx(-3.3)


def test_costs_scale_with_the_amount(costed):
    costed.run(CALC.strip() + " WITH COSTS AMOUNT 2 kg")
    assert query(costed, "RESULT COSTS")["rows"][0]["amount"] == \
        pytest.approx(-6.6)
    # the intensity is per unit and does not change
    r = query(costed, 'RESULT COSTS INTENSITY OF PROCESS "Widget"')
    assert r["rows"][0]["amount"] == pytest.approx(-3.3)


def test_result_costs_tree(costed):
    r = query(costed, "RESULT COSTS TREE")
    assert r["root"]["amount"] == pytest.approx(-3.3)
    assert r["subject"] == "costs" and r["unit"] == "Euro"
    same = query(costed, "RESULT TREE COSTS LEVELS 1")
    assert same["root"]["amount"] == pytest.approx(-3.3)


def test_costs_need_a_result_with_costs(calc):
    for code in ("RESULT COSTS", "RESULT COSTS BY PROCESS",
                 'RESULT COSTS OF PROCESS "Widget"', "RESULT TREE COSTS"):
        e = err(calc.run(code))
        assert e["message"] == "This result was calculated without costs."
        assert "WITH COSTS" in e["hint"]


# ── normalised and weighted ──────────────────────────────────

@pytest.fixture
def nw(session, client):
    method = next(m for m in client.store["ImpactMethod"].values()
                  if m.name == EF)
    fossil = next(c for c in method.impact_categories if c.name == FOSSIL)
    acid = next(c for c in method.impact_categories
                if c.name == "Acidification")
    method.nw_sets = [o.NwSet(id="nw1", name="Test set", factors=[
        o.NwFactor(impact_category=fossil, normalisation_factor=100.0,
                   weighting_factor=0.2),
        o.NwFactor(impact_category=acid, normalisation_factor=0.5,
                   weighting_factor=0.1)])]
    return session


def test_result_normalised_and_weighted(nw):
    assert nw.run(CALC.strip() + ' NW SET "Test set"').ok
    r = query(nw, "RESULT NORMALISED")
    by = rows_by(r, "category")
    assert by[FOSSIL]["amount"] == pytest.approx(2.725 / 100)
    assert by["Acidification"]["amount"] == pytest.approx(0.0074 / 0.5)
    assert r["nw_set"] == "Test set"
    assert query(nw, "RESULT NORMALIZED")["rows"] == r["rows"]
    w = rows_by(query(nw, "RESULT WEIGHTED"), "category")
    assert w[FOSSIL]["amount"] == pytest.approx(2.725 / 100 * 0.2)
    assert w["Acidification"]["amount"] == pytest.approx(0.0074 / 0.5 * 0.1)


def test_nw_set_must_exist(nw):
    e = err(nw.run(CALC.strip() + ' NW SET "Other set"'))
    assert "has no NW set called 'Other set'" in e["message"]
    assert '"Test set"' in e["hint"]
    e = err(nw.run('CALCULATE "Widget" USING "EF v3.0" NW SET "Test set"'))
    assert "has no normalisation and weighting sets" in e["message"]


def test_normalised_needs_an_nw_set(calc):
    e = err(calc.run("RESULT NORMALISED"))
    assert "needs a normalisation and weighting set" in e["message"]
    assert 'NW SET "name"' in e["hint"]
    assert "RESULT WEIGHTED needs" in err(calc.run("RESULT WEIGHTED"))["message"]


# ── analysis groups ──────────────────────────────────────────

@pytest.fixture
def grouped(session, client):
    system = client.by_name(o.ProductSystem, "Widget")[0]
    elec = next(p for p in client.store["Process"].values()
                if p.name == ELECTRICITY
                and client._location_code(p.location) == "GB")
    system.analysis_groups = [o.AnalysisGroup(
        name="Energy", processes=[o.Ref(id=elec.id)])]
    assert session.run(CALC).ok
    return session


def test_impacts_by_group(grouped):
    r = query(grouped, f'RESULT IMPACTS BY GROUP CATEGORY "{FOSSIL}"')
    by = rows_by(r, "group")
    assert by["Energy"]["amount"] == pytest.approx(0.625)
    # steel is in no group, so it counts with what it supplies: the top
    assert by["Top"]["amount"] == pytest.approx(0.5 + 1.6)
    assert sum(row["amount"] for row in r["rows"]) == pytest.approx(2.725)
    every = query(grouped, "RESULT IMPACTS BY GROUP")
    assert len(every["rows"]) == 12


def test_a_group_behind_an_ungrouped_process_says_why_it_is_empty(
        session, client):
    """Found live: in a large system openLCA gives a group nothing
    unless the reference process uses a grouped process directly, and
    then no row comes back. The answer says so, and what to do."""
    client.large_system = True
    system = client.by_name(o.ProductSystem, "Widget")[0]
    elec = next(p for p in client.store["Process"].values()
                if p.name == ELECTRICITY
                and client._location_code(p.location) == "GB")
    system.analysis_groups = [o.AnalysisGroup(
        name="Energy", processes=[o.Ref(id=elec.id)])]
    assert session.run(CALC).ok
    r = query(session, f'RESULT IMPACTS BY GROUP CATEGORY "{FOSSIL}"')
    assert r["rows"] == []
    assert "the bridge, not the background process behind it" in r["note"]
    # with the bridge in the group, the group has the electricity
    widget = client.by_name(o.Process, "Widget")[0]
    names = {p.id: p.name for p in client.store["Process"].values()}
    bridge = next(ex.default_provider for ex in widget.exchanges
                  if ex.default_provider is not None
                  and "lectricity" in names[ex.default_provider.id])
    system.analysis_groups = [o.AnalysisGroup(
        name="Energy", processes=[o.Ref(id=bridge.id)])]
    assert session.run(CALC).ok
    r = query(session, f'RESULT IMPACTS BY GROUP CATEGORY "{FOSSIL}"')
    assert rows_by(r, "group")["Energy"]["amount"] == pytest.approx(0.625)
    assert "note" not in r


def test_flows_and_costs_by_group(grouped, client):
    r = query(grouped, f'RESULT FLOWS BY GROUP FLOW "{CO2}"')
    assert rows_by(r, "group")["Top"]["amount"] == pytest.approx(0.5)
    assert rows_by(r, "group")["Energy"]["amount"] == 0
    e = err(grouped.run("RESULT FLOWS BY GROUP"))
    assert "needs FLOW" in e["message"]
    proc = process(client, "Widget")
    for ex in proc.exchanges:
        if not ex.is_quantitative_reference and ex.is_input:
            ex.cost_value = 1.0
    grouped.run(CALC.strip() + " WITH COSTS")
    r = query(grouped, "RESULT COSTS BY GROUP")
    assert rows_by(r, "group")["Top"]["amount"] == pytest.approx(2.0)


def test_groups_need_groups(calc):
    for code in (f'RESULT IMPACTS BY GROUP', f'RESULT FLOWS BY GROUP FLOW "{CO2}"'):
        e = err(calc.run(code))
        assert "has no analysis groups" in e["message"]
        assert "ANALYSIS GROUP" in e["hint"]


# ── results by tag need the tag-results methods ──────────────────────────

def test_by_tag_says_which_version_it_needs(calc):
    e = err(calc.run(f'RESULT IMPACTS BY TAG CATEGORY "{FOSSIL}"'))
    assert "needs a later openLCA than 2.7.0" in e["message"]
    assert "result/tag-results-of-impact" in e["message"]


def test_by_tag_on_a_server_that_has_it(session, client):
    client.server_version = FUTURE_VERSION
    process(client, "Widget").tags = ["foreground", "site"]
    session.run(CALC.strip() + " WITH COSTS")
    r = query(session, f'RESULT IMPACTS BY TAG CATEGORY "{FOSSIL}"')
    by = rows_by(r, "tag")
    assert by["foreground"]["amount"] == pytest.approx(0.5)
    assert by["site"]["amount"] == pytest.approx(0.5)
    r = query(session, f'RESULT FLOWS BY TAG FLOW "{CO2}"')
    assert rows_by(r, "tag")["site"]["amount"] == pytest.approx(0.5)
    r = query(session, "RESULT COSTS BY TAG")
    assert rows_by(r, "tag")["site"]["amount"] == 0
    assert "needs CATEGORY" in err(
        session.run("RESULT IMPACTS BY TAG"))["message"]


# ── Sankey ───────────────────────────────────────────────────

def test_result_sankey(calc, tmp_path):
    path = tmp_path / "sankey.json"
    r = query(calc, f'RESULT SANKEY CATEGORY "{FOSSIL}" SAVE "{path}"')
    nodes = {n["process"]: n for n in r["nodes"]}
    assert nodes["Widget"]["amount"] == pytest.approx(2.725)
    assert nodes["Widget"]["direct"] == pytest.approx(0.5)
    assert nodes[STEEL]["amount"] == pytest.approx(1.6)
    assert nodes[B_STEEL]["amount"] == pytest.approx(1.6)
    assert nodes[B_STEEL]["direct"] == 0
    root = r["root_index"]
    assert r["nodes"][root]["process"] == "Widget"
    links = {(e["from"], e["to"]): e["share"] for e in r["edges"]}
    assert links[(nodes[B_STEEL]["index"], root)] == pytest.approx(
        1.6 / 2.725)
    assert (nodes[STEEL]["index"], nodes[B_STEEL]["index"]) in links
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert len(saved["nodes"]) == 5 and len(saved["edges"]) == 4


def test_sankey_min_share_and_max_nodes(calc):
    r = query(calc, f'RESULT SANKEY CATEGORY "{FOSSIL}" MIN SHARE 30%')
    assert {n["process"] for n in r["nodes"]} == {"Widget", B_STEEL, STEEL}
    r = query(calc, f'RESULT SANKEY CATEGORY "{FOSSIL}" MAX NODES 1')
    assert len(r["nodes"]) == 1
    r = query(calc, f'RESULT SANKEY FLOW "{CO2}"')
    assert r["nodes"][r["root_index"]]["amount"] == pytest.approx(0.5)


def test_sankey_does_not_save_as_csv(calc, tmp_path):
    e = err(calc.run(f'RESULT SANKEY CATEGORY "{FOSSIL}" '
                     f'SAVE "{tmp_path / "s.csv"}"'))
    assert "SAVE \"file.json\"" in e["hint"]


# ── TOP and SAVE on every query ──────────────────────────────

def test_top_keeps_the_largest_rows(calc):
    r = query(calc, f'RESULT CONTRIBUTION BY PROCESS DIRECT '
                    f'CATEGORY "{FOSSIL}" TOP 2')
    assert [row["process"] for row in r["rows"]] == [STEEL, ELECTRICITY]
    assert r["row_count"] == 5 and r["top"] == 2
    text = calc.run(f'RESULT CONTRIBUTION BY PROCESS DIRECT '
                    f'CATEGORY "{FOSSIL}" TOP 2').text
    assert "Showing 2 of 5 rows (TOP 2)" in text


def test_impacts_keep_the_method_order(calc):
    r = query(calc, "RESULT IMPACTS TOP 2")
    assert [row["category"] for row in r["rows"]] == [
        "Acidification", "Climate change"]


def test_save_writes_csv(calc, tmp_path):
    path = tmp_path / "impacts.csv"
    r = calc.run(f'RESULT IMPACTS SAVE "{path}"')
    assert r.ok and f"Saved to {path}" in r.text
    rows = list(csv.reader(path.open(encoding="utf-8")))
    assert rows[0] == ["category", "amount", "unit"]
    assert len(rows) == 7
    fossil = next(r for r in rows if r[0] == FOSSIL)
    assert float(fossil[1]) == pytest.approx(2.725)


def test_top_and_save_together(calc, tmp_path):
    path = tmp_path / "top.csv"
    calc.run(f'RESULT SCALING SAVE "{path}" TOP 1')
    rows = list(csv.reader(path.open(encoding="utf-8")))
    assert len(rows) == 2 and rows[1][0] in (ELECTRICITY, B_ELEC)


def test_save_results_after_a_query(calc, tmp_path):
    path = tmp_path / "later.csv"
    calc.run("RESULT REQUIREMENTS")
    assert calc.run(f'SAVE RESULTS "{path}"').ok
    assert path.read_text(encoding="utf-8").startswith("process,location")


def test_text_output_is_a_table(calc):
    text = calc.run("RESULT IMPACTS").text
    assert "Impact totals" in text and "System: Widget" in text
    assert f"Method: {EF}" in text and "Impact category" in text
    assert "2.725000" in text


# ── the grammar refuses what makes no sense ──────────────────

@pytest.mark.parametrize("code,fragment", [
    ("RESULT IMPACTS DIRECT", "does not take DIRECT"),
    ("RESULT CATEGORIES CATEGORY \"x\"", "does not take CATEGORY"),
    ("RESULT FACTORS", "needs CATEGORY"),
    ("RESULT INTENSITY", "needs OF PROCESS"),
    ("RESULT INTENSITY OF PROCESS \"x\" FLOWS CATEGORY \"y\"", "takes one of"),
    ("RESULT CONTRIBUTION", "needs BY PROCESS, BY FLOW or OF PROCESS"),
    ("RESULT CONTRIBUTION BY PROCESS OF PROCESS \"x\"", "not both"),
    ("RESULT FLOW \"x\"", "BY PROCESS"),
    ("RESULT COSTS BY FLOW", "BY PROCESS, BY GROUP or BY TAG"),
    ("RESULT COSTS DIRECT", "needs OF PROCESS"),
    ("RESULT SANKEY", "takes CATEGORY"),
    ("RESULT IMPACTS BY", "BY must be followed by"),
    ("RESULT IMPACTS TOP 0", "TOP needs a number above 0"),
    ("RESULT IMPACTS IN \"base\"", "IN needs the name"),
])
def test_malformed_result_commands(session, code, fragment):
    e = err(session.run(code))
    assert fragment in e["message"], e
    assert e["line"] == 1 and "HELP RESULT" in e["hint"]


def test_result_is_still_a_variable_name(session):
    r = session.run("result = 5\nclose = 2\nPRINT result + close")
    assert r.ok and r.text.strip() == "7"


def test_help_result(session):
    text = session.run("HELP RESULT").text
    for word in ("RESULT IMPACTS", "RESULT COSTS", "RESULT SANKEY",
                 "CLOSE RESULT", "RESULT NORMALISED / RESULT NORMALIZED"):
        assert word in text
    assert "RESULT NORMALISED" in session.run("HELP RESULT NORMALIZED").text


# ── dry run ──────────────────────────────────────────────────

def test_dry_run_checks_result_names(session):
    r = session.run(CALC.strip() + " AS base\nRESULT IMPACTS IN base\n"
                    "CLOSE RESULT base\nRESULT COSTS IN base", dry_run=True)
    e = err(r)
    assert e["line"] == 4 and "No open result is called 'base'" in e["message"]
    r = session.run("RESULT IMPACTS", dry_run=True)
    assert err(r)["message"] == "No result is open."
    assert session.run(CALC + "RESULT IMPACTS", dry_run=True).ok
    # a result opened by an earlier run counts
    session.run(CALC)
    assert session.run("RESULT IMPACTS", dry_run=True).ok
