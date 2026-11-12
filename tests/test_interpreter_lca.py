"""Interpreter tests against the fake openLCA client."""

import pytest
import olca_schema as o

from fake_client import ELECTRICITY, STEEL, WATER, PLASTIC, bg_id
from olcabasic.interpreter import BasicError

SETUP = '''
CONFIRM DELETE ON
SET PROCESS FOLDER "00: Test"
SET FLOW FOLDER "00: Test"
'''

# Every background input goes through a bridge (0.4.0). These are the
# bridges the tests use; a program names them B_ELEC, B_STEEL and so on.
# (Lower-case names, so that a test can find an exchange by "electricity"
# or "steel" in its flow name as before.)
B_ELEC = "BRIDGE | electricity | kWh"            # United Kingdom
B_ELEC_DE = "BRIDGE | electricity DE | kWh"
B_STEEL = "BRIDGE | steel | kg"
B_WATER = "BRIDGE | water | kg"                  # RER
B_PLASTIC = "BRIDGE | plastic | kg"              # RER
BRIDGES = f'''
BRIDGE "electricity", kWh
  PROVIDER "{ELECTRICITY}" LOCATION "GB"
END BRIDGE
BRIDGE "electricity DE", kWh
  PROVIDER "{ELECTRICITY}" LOCATION "DE"
END BRIDGE
BRIDGE "steel", kg
  PROVIDER "{STEEL}"
END BRIDGE
BRIDGE "water", kg
  PROVIDER "{WATER}" LOCATION "RER"
END BRIDGE
BRIDGE "plastic", kg
  PROVIDER "{PLASTIC}" LOCATION "RER"
END BRIDGE
'''

WIDGET = SETUP + BRIDGES + f'''
LET elec = 2.5
MAKE PROCESS "Widget"
  OUTPUT MAKE FLOW "Widget", 1, kg, PRODUCT
  INPUT USE PROCESS "{B_ELEC}", elec, kWh
  INPUT USE PROCESS "{B_STEEL}", 0.8, kg
  OUTPUT "Carbon dioxide, fossil", 0.5, kg TO AIR
END PROCESS
SYSTEM "Widget"
'''

# 2.5 kWh x 0.25 + 0.8 kg x 2.0 + 0.5 kg CO2
WIDGET_FOSSIL = 2.5 * 0.25 + 0.8 * 2.0 + 0.5


def process(client, name):
    found = client.by_name(o.Process, name)
    assert len(found) == 1, f"{len(found)} processes called {name}"
    return found[0]


def impact(interp, category):
    for i in interp.runtime.last_results["impacts"]:
        if i["category"] == category:
            return i["amount"]
    raise KeyError(category)


# ── FIND ─────────────────────────────────────────────────────

def test_find_process_lists_matches(run):
    out = run('FIND PROCESS "test steel"')
    assert "1 results (of 1 total)" in out
    assert "market for test steel" in out


def test_find_process_shows_duplicates_by_location(run):
    out = run('FIND PROCESS "test electricity"')
    assert "3 results (of 3 total)" in out


def test_find_flow(run):
    out = run('FIND FLOW "Carbon dioxide"')
    assert out.count("Carbon dioxide, fossil") == 2


def test_find_method(run):
    out = run('FIND METHOD "EF v3.1"')
    assert "EF v3.1" in out and "EF v3.1 no LT" in out and "EF v3.0" not in out


def test_find_unit(run):
    out = run('FIND UNIT "kWh"')
    assert "flow_property_name: Energy" in out


# ── MAKE PROCESS ─────────────────────────────────────────────

def test_make_process_creates_flow_process_and_parameters(run, client):
    out = run(WIDGET)
    assert "Process created: Widget (4 exchanges, 3 parameters)" in out
    proc = process(client, "Widget")
    assert proc.category == "00: Test"
    assert len(client.by_name(o.Flow, "Widget")) == 1
    qref = [ex for ex in proc.exchanges if ex.is_quantitative_reference]
    assert len(qref) == 1 and not qref[0].is_input


def test_use_process_sets_the_provider_at_the_location(run, client):
    run(WIDGET)
    proc = process(client, "Widget")
    ex = next(e for e in proc.exchanges
              if client._flow_name(e.flow.id) == B_ELEC)
    assert ex.unit.name == "kWh"
    assert client.store["Process"][ex.default_provider.id].name == B_ELEC
    # the bridge names the background process, at the location asked for
    behind = next(e for e in process(client, B_ELEC).exchanges if e.is_input)
    provider = client.store["Process"][behind.default_provider.id]
    assert provider.name == ELECTRICITY
    assert client._location_code(provider.location) == "GB"


def test_variable_amount_becomes_a_global_parameter(run, client):
    run(WIDGET)
    proc = process(client, "Widget")
    ex = next(e for e in proc.exchanges if e.amount_formula == "elec")
    assert ex.amount == 0.0
    params = client.by_name(o.Parameter, "elec")
    assert len(params) == 1 and params[0].value == 2.5
    assert params[0].parameter_scope == o.ParameterScope.GLOBAL_SCOPE


def test_bare_amounts_become_process_parameters(run, client):
    run(WIDGET)
    proc = process(client, "Widget")
    names = sorted(p.name for p in proc.parameters)
    assert names == ["p00_Widget__Widget_kg",
                     "p02_Widget__BRIDGE_steel_kg_kg",
                     "p03_Widget__Carbon_dioxide_fossi_kg"]


def test_formula_parameter_from_derived_variable(run, client):
    run(SETUP + BRIDGES + f'''
LET base = 2
LET double = base * 2
MAKE PROCESS "Derived"
  OUTPUT MAKE FLOW "Derived", 1, kg, PRODUCT
  INPUT USE PROCESS "{B_STEEL}", double, kg
END PROCESS''')
    double = client.by_name(o.Parameter, "double")[0]
    assert double.formula == "(base * 2.0)" and not double.is_input_parameter
    assert client.by_name(o.Parameter, "base")[0].value == 2.0


def test_local_let_stays_a_process_parameter(run, client):
    run(SETUP + BRIDGES + f'''
MAKE PROCESS "Local"
  LET mass = 3
  OUTPUT MAKE FLOW "Local", 1, kg, PRODUCT
  INPUT USE PROCESS "{B_STEEL}", mass, kg
END PROCESS''')
    proc = process(client, "Local")
    assert any(p.name == "mass" and p.value == 3.0 for p in proc.parameters)
    assert client.by_name(o.Parameter, "mass") == []


def test_making_a_process_twice_warns_and_does_not_duplicate(run, client):
    run(WIDGET)
    out = run(WIDGET)
    assert "WARNING: process 'Widget' already exists in 00: Test" in out
    assert len(client.by_name(o.Process, "Widget")) == 1
    assert len(client.by_name(o.Flow, "Widget")) == 1


def test_ambiguous_use_process_is_an_error_listing_the_candidates(interp, client):
    """Changed on purpose in 0.4.0 (command map section 7): this was a
    warning that used the first match."""
    with pytest.raises(BasicError) as e:
        interp.run_program(SETUP + f'''
MAKE PROCESS "Ambiguous"
  OUTPUT MAKE FLOW "Ambiguous", 1, kg, PRODUCT
  INPUT USE PROCESS "{ELECTRICITY}", 1, kWh
END PROCESS''')
    text = str(e.value)
    assert "matches 3 processes" in text and e.value.line == 8
    for row in client.by_name(o.Process, ELECTRICITY):
        assert row.id in text
        assert client._location_code(row.location) in text
    assert 'Add LOCATION "code"' in e.value.hint and "PROVIDER" in e.value.hint
    assert client.by_name(o.Process, "Ambiguous") == []
    assert client.by_name(o.Flow, "Ambiguous") == []


def test_unknown_location_lists_what_is_available(interp):
    with pytest.raises(BasicError) as e:
        interp.run_program(SETUP + f'''
MAKE PROCESS "X"
  OUTPUT MAKE FLOW "X", 1, kg, PRODUCT
  INPUT USE PROCESS "{ELECTRICITY}", 1, kWh LOCATION "FR"
END PROCESS''')
    assert 'No \'' in str(e.value) and "Available: DE, GB, RoW" in str(e.value)


def test_unknown_process_name_is_an_error(interp):
    with pytest.raises(BasicError) as e:
        interp.run_program(SETUP + '''
MAKE PROCESS "X"
  OUTPUT MAKE FLOW "X", 1, kg, PRODUCT
  INPUT USE PROCESS "no such thing", 1, kg
END PROCESS''')
    assert "No process found matching 'no such thing'" in str(e.value)
    assert "FIND PROCESS" in str(e.value)


def test_unknown_elementary_flow_is_an_error(interp):
    with pytest.raises(BasicError) as e:
        interp.run_program(SETUP + '''
MAKE PROCESS "X"
  OUTPUT MAKE FLOW "X", 1, kg, PRODUCT
  OUTPUT "Unobtainium", 1, kg TO AIR
END PROCESS''')
    assert "Elementary flow 'Unobtainium' not found" in str(e.value)


def test_elementary_flow_in_several_compartments_says_which(run):
    out = run(WIDGET)
    assert "exists in 2 sub-compartments" in out
    assert "Emission to air/unspecified" in out


def test_provider_by_uuid(run, client):
    row = next(p for p in client.by_name(o.Process, ELECTRICITY)
               if client._location_code(p.location) == "DE")
    run(SETUP + f'''
BRIDGE "by uuid", kWh
  PROVIDER "{row.id}"
END BRIDGE
MAKE PROCESS "ByUuid"
  OUTPUT MAKE FLOW "ByUuid", 1, kg, PRODUCT
  INPUT USE PROCESS "{B_ELEC}", 1, kWh PROVIDER "BRIDGE | by uuid | kWh"
END PROCESS'''.replace(B_ELEC, "BRIDGE | by uuid | kWh"))
    behind = [e for e in process(client, "BRIDGE | by uuid | kWh").exchanges
              if e.is_input][0]
    assert behind.default_provider.id == row.id
    ex = [e for e in process(client, "ByUuid").exchanges if e.is_input][0]
    assert ex.default_provider.id == process(client,
                                             "BRIDGE | by uuid | kWh").id


def test_legacy_input_new_prints_a_deprecation_note_once(run):
    out = run(SETUP + '''
PROCESS "Legacy"
  OUTPUT NEW "Legacy", 1, kg, PRODUCT
  INPUT NEW "Legacy input a", 1, kg
  INPUT NEW "Legacy input b", 1, kg
END PROCESS''')
    assert out.count("INPUT NEW and OUTPUT NEW are deprecated") == 1


def test_bridge(run, client):
    row = client.by_name(o.Process, STEEL)[0]
    out = run(SETUP + f'''
BRIDGE "BRIDGE | Steel | kg", kg
  FOLDER "00: Test/Bridges"
  PROVIDER "{row.id}"
END BRIDGE''')
    assert "Bridge created: BRIDGE | Steel | kg (kg)" in out
    proc = process(client, "BRIDGE | Steel | kg")
    assert proc.category == "00: Test/Bridges" and len(proc.exchanges) == 2


def test_make_flow_is_idempotent(run, client):
    out = run(SETUP + 'MAKE FLOW "Thing", kg, PRODUCT\nMAKE FLOW "Thing", kg, PRODUCT')
    assert "Flow created: Thing" in out and "Flow exists: Thing" in out
    assert len(client.by_name(o.Flow, "Thing")) == 1


# ── EDIT PROCESS and EDIT FLOW ───────────────────────────────

def test_edit_process_update_amount_and_add_input(run, client):
    run(WIDGET)
    out = run(f'''
EDIT PROCESS "Widget"
  UPDATE INPUT "{B_STEEL}", 1.5, kg
  ADD INPUT USE PROCESS "{B_WATER}", 10, kg
  SET DESCRIPTION "Edited"
END EDIT''')
    assert "Edited process: Widget" in out
    assert "keep their old links" in out
    proc = process(client, "Widget")
    steel = next(e for e in proc.exchanges
                 if client._flow_name(e.flow.id) == B_STEEL)
    assert steel.amount == 1.5 and steel.amount_formula is None
    assert len(proc.exchanges) == 5 and proc.description == "Edited"


def test_edit_process_remove_input(run, client):
    run(WIDGET)
    run(f'EDIT PROCESS "Widget"\n  REMOVE INPUT "{B_STEEL}"\nEND EDIT')
    assert len(process(client, "Widget").exchanges) == 3


def test_edit_process_cannot_remove_the_reference_product(run, interp):
    run(WIDGET)
    with pytest.raises(BasicError) as e:
        interp.run_program('EDIT PROCESS "Widget"\n  REMOVE OUTPUT "Widget"\nEND EDIT')
    assert "is the reference product" in str(e.value)


def test_edit_process_unknown_exchange_lists_what_exists(run, interp):
    run(WIDGET)
    with pytest.raises(BasicError) as e:
        interp.run_program('EDIT PROCESS "Widget"\n  REMOVE INPUT "nothing"\nEND EDIT')
    assert "has no input called 'nothing'" in str(e.value)
    assert B_STEEL in str(e.value)


def test_edit_process_relink_by_location(run, client):
    run(WIDGET)
    # the choice of background process sits in the bridge, so that is
    # what is relinked: one edit, and every process that uses the bridge
    # follows
    run(f'EDIT PROCESS "{B_ELEC}"\n  UPDATE INPUT "test electricity, medium '
        f'voltage" LOCATION "DE"\nEND EDIT')
    behind = next(e for e in process(client, B_ELEC).exchanges if e.is_input)
    provider = client.store["Process"][behind.default_provider.id]
    assert client._location_code(provider.location) == "DE"
    ex = next(e for e in process(client, "Widget").exchanges
              if e.amount_formula == "elec")
    assert client.store["Process"][ex.default_provider.id].name == B_ELEC


def test_edit_process_set_folder_and_parameter(run, client):
    run(WIDGET)
    run('EDIT PROCESS "Widget"\n  ADD PARAM extra = 4\n  SET FOLDER "00: Moved"\nEND EDIT')
    proc = process(client, "Widget")
    assert proc.category == "00: Moved"
    assert any(p.name == "extra" and p.value == 4.0 for p in proc.parameters)


def test_edit_unknown_process(interp):
    with pytest.raises(BasicError) as e:
        interp.run_program('EDIT PROCESS "Nope"\n  SET DESCRIPTION "x"\nEND EDIT')
    assert "Process not found: 'Nope'" in str(e.value)


def test_edit_flow_adds_a_property(run, client):
    run(SETUP + 'MAKE FLOW "Concrete", m3, PRODUCT')
    out = run('EDIT FLOW "Concrete"\n  ADD PROPERTY "Mass" AS 2400 kg PER m3\nEND EDIT')
    assert "Edited flow: Concrete" in out
    flow = client.by_name(o.Flow, "Concrete")[0]
    assert sorted(f.flow_property.name for f in flow.flow_properties) == ["Mass", "Volume"]
    mass = next(f for f in flow.flow_properties if f.flow_property.name == "Mass")
    assert mass.conversion_factor == pytest.approx(2400.0)


def test_edit_flow_outside_build_folders_notes_the_reach(run):
    out = run('SET FLOW FOLDER "00: Mine"\nEDIT FLOW "test water"\n'
              '  ADD PROPERTY "Volume" AS 1 m3 PER 1000 kg\nEND EDIT')
    assert "isn't in your build folders" in out


def test_edit_unknown_flow(interp):
    with pytest.raises(BasicError) as e:
        interp.run_program('EDIT FLOW "Nope"\n  SET REFERENCE "Mass"\nEND EDIT')
    assert "Flow not found: 'Nope'" in str(e.value)


# ── parameters ───────────────────────────────────────────────

def test_update_parameter_writes_the_global_now(run, client):
    out = run("LET rate = 3\nUPDATE PARAMETER rate = 4")
    assert "Global parameter rate = 4 (was 3)" in out
    assert client.by_name(o.Parameter, "rate")[0].value == 4.0


def test_overwriting_someone_elses_global_is_noted(run, client, engine):
    engine.create_global_parameter("shared_rate", value=1.0)
    out = run("UPDATE PARAMETER shared_rate = 2")
    assert "already existed (was 1.0) and has been updated" in out


def test_show_parameter(run):
    out = run("LET rate = 3\nUPDATE PARAMETER rate = 4\nSHOW PARAMETER \"rate\"")
    assert "rate = 4" in out.splitlines()[-1]


# ── systems and calculations ─────────────────────────────────

def test_system_is_created_once(run, client):
    out = run(WIDGET)
    assert "System created: Widget" in out
    out = run('SYSTEM "Widget"')
    assert "already exists and was reused" in out
    assert len(client.by_name(o.ProductSystem, "Widget")) == 1


def test_calculate(run, interp, client):
    out = run(WIDGET + 'CALCULATE "Widget" USING "EF v3.1"')
    assert "Calculating: Widget using EF v3.1" in out
    assert impact(interp, "Climate change: fossil") == pytest.approx(WIDGET_FOSSIL)
    assert interp.runtime.last_results_type == "calculate"
    assert client.undisposed() == 0


def test_calculate_unknown_system_and_method(run, interp):
    run(WIDGET)
    with pytest.raises(BasicError) as e:
        interp.run_program('CALCULATE "Nope" USING "EF v3.1"')
    assert "Product system not found: Nope" in str(e.value)
    with pytest.raises(BasicError) as e:
        interp.run_program('CALCULATE "Widget" USING "ReCiPe"')
    # wording changed in 0.4.0: method names must match in full
    assert "No impact method is called 'ReCiPe'" in str(e.value)


def test_contribution(run, interp):
    run(WIDGET + 'CONTRIBUTION "Widget" USING "IPCC 2021" TOP 2\n'
        '  CATEGORIES "fossil"\nEND CONTRIBUTION')
    cats = interp.runtime.last_results["categories"]
    assert list(cats) == ["Climate change: fossil - Global warming potential (GWP100)"]
    rows = next(iter(cats.values()))["contributors"]
    assert len(rows) == 2 and rows[0]["process"] == "Widget"
    assert rows[1]["amount"] == pytest.approx(1.6)


def test_scenarios(run, interp):
    run(WIDGET + '''
SCENARIO "Low"
  LET elec = 1
END SCENARIO
SCENARIO "High"
  LET elec = 5
END SCENARIO
RUN SCENARIOS ON "Widget" USING "IPCC 2021"''')
    res = interp.runtime.last_results["results"]
    name = "Climate change: fossil - Global warming potential (GWP100)"
    low = next(i["amount"] for i in res["Low"] if i["category"] == name)
    high = next(i["amount"] for i in res["High"] if i["category"] == name)
    assert low == pytest.approx(1 * 0.25 + 1.6 + 0.5)
    assert high == pytest.approx(5 * 0.25 + 1.6 + 0.5)
    assert interp.runtime.scenarios == {}


def test_run_scenarios_without_any_is_an_error(run, interp):
    run(WIDGET)
    with pytest.raises(BasicError) as e:
        interp.run_program('RUN SCENARIOS ON "Widget" USING "IPCC 2021"')
    assert "No scenarios defined" in str(e.value)


def test_scenario_cannot_set_a_derived_variable(interp):
    with pytest.raises(BasicError) as e:
        interp.run_program('LET a = 1\nLET b = a * 2\nSCENARIO "S"\n  LET b = 5\nEND SCENARIO')
    assert "'b' is calculated from a" in str(e.value)


def test_sensitivity(run, interp):
    run(WIDGET + '''
SENSITIVITY ON "Widget" USING "IPCC 2021" BY 10%
  VARY elec
  VARY p02_Widget__BRIDGE_steel_kg_kg
END SENSITIVITY''')
    res = interp.runtime.last_results
    name = "Climate change: fossil - Global warming potential (GWP100)"
    assert res["tested"] == ["elec", "p02_Widget__BRIDGE_steel_kg_kg"]
    assert res["baseline"][name]["amount"] == pytest.approx(WIDGET_FOSSIL)
    assert res["sensitivity"]["elec"]["plus"][name] == pytest.approx(
        WIDGET_FOSSIL + 0.25 * 0.25)
    assert res["sensitivity"]["p02_Widget__BRIDGE_steel_kg_kg"]["minus"][name] \
        == pytest.approx(WIDGET_FOSSIL - 0.08 * 2.0)


def test_sensitivity_on_unknown_parameter(run, interp):
    run(WIDGET)
    with pytest.raises(BasicError) as e:
        interp.run_program('SENSITIVITY ON "Widget" USING "IPCC 2021" BY 10\n'
                           '  VARY nothing\nEND SENSITIVITY')
    assert "No matching input parameters found" in str(e.value)


def test_montecarlo_statistics_shape(run, interp):
    run(WIDGET + 'MONTECARLO "Widget" USING "IPCC 2021" RUNS 5')
    res = interp.runtime.last_results
    assert res["iterations"] == 5
    stats = next(iter(res["statistics"].values()))
    assert set(stats) == {"unit", "iterations", "mean", "std_dev", "cv_pct",
                          "min", "max", "median", "p5", "p95"}
    assert "zero variance" in res["warning"]


def test_inventory(run, interp):
    run(WIDGET + 'INVENTORY "Widget" USING "EF v3.1"')
    flows = interp.runtime.last_results["flows"]
    assert flows[0]["flow"] == "Carbon dioxide, fossil"
    assert flows[0]["amount"] == pytest.approx(0.5)


def test_tree(run):
    out = run(WIDGET + 'TREE "Widget" USING "EF v3.1" CATEGORY "Climate change" LEVELS 2')
    assert "Widget" in out and "100.0%" in out and "market for test steel" in out


def test_tree_without_category_lists_them(run, interp):
    run(WIDGET)
    with pytest.raises(BasicError) as e:
        interp.run_program('TREE "Widget" USING "EF v3.1"')
    assert "TREE needs CATEGORY" in str(e.value) and "Acidification" in str(e.value)


def test_validate(run):
    out = run(WIDGET + 'VALIDATE "Widget"')
    assert "valid: True" in out


def test_save_results_csv(run, tmp_path):
    target = tmp_path / "out.csv"
    out = run(WIDGET + f'CALCULATE "Widget" USING "EF v3.1"\nSAVE RESULTS "{target.as_posix()}"')
    assert "Results saved to" in out
    text = target.read_text(encoding="utf-8")
    assert "Climate change" in text and "kg CO2-Eq" in text


def test_print_results_without_any(run):
    assert "No results to display" in run("PRINT RESULTS")


# ── DELETE ───────────────────────────────────────────────────

def test_delete_with_confirm_on(run, client):
    out = run(WIDGET + 'DELETE SYSTEM "Widget"\nDELETE PROCESS "Widget"')
    assert "Deleted: Widget" in out
    assert client.by_name(o.ProductSystem, "Widget") == []
    assert client.by_name(o.Process, "Widget") == []


def test_delete_missing_thing_is_not_an_error(run):
    out = run('CONFIRM DELETE ON\nDELETE PROCESS "Never existed"')
    assert "Not found: Never existed (nothing to delete)" in out


def test_delete_asks_when_confirm_is_off(run, client, monkeypatch):
    run(WIDGET + "CONFIRM DELETE OFF")
    monkeypatch.setattr("builtins.input", lambda prompt="": "no")
    out = run('DELETE PROCESS "Widget"')
    assert "Cancelled." in out
    assert len(client.by_name(o.Process, "Widget")) == 1
    monkeypatch.setattr("builtins.input", lambda prompt="": "yes")
    run('DELETE PROCESS "Widget"')
    assert client.by_name(o.Process, "Widget") == []


def test_delete_ambiguous_name_is_refused(interp):
    with pytest.raises(BasicError) as e:
        interp.run_program(f'CONFIRM DELETE ON\nDELETE PROCESS "{ELECTRICITY}"')
    assert "3 processs are called" in str(e.value) and "Nothing was deleted" in str(e.value)


# ── SHOW, LINK, MOVE, navigation ─────────────────────────────

def test_show_process_and_inputs(run):
    out = run(WIDGET + 'SHOW PROCESS "Widget"\nSHOW PROCESS "Widget" INPUTS')
    assert "Exchanges (4):" in out and "Widget: 2 inputs" in out


def test_show_flow_units(run):
    out = run('SHOW FLOW "test water" UNITS')
    assert "kg" in out


def test_link_adds_an_input(run, client):
    run(WIDGET + SETUP + '''
MAKE PROCESS "Assembly"
  OUTPUT MAKE FLOW "Assembly", 1, kg, PRODUCT
END PROCESS
LINK PROCESS "Widget" TO PROCESS "Assembly" WITH 3, kg''')
    proc = process(client, "Assembly")
    widget = process(client, "Widget")
    ex = [e for e in proc.exchanges if e.is_input][0]
    assert ex.default_provider.id == widget.id


def test_move_process(run, client):
    out = run(WIDGET + 'MOVE PROCESS "Widget" TO "00: Elsewhere"')
    assert "Moved process 'Widget' to '00: Elsewhere'" in out
    assert process(client, "Widget").category == "00: Elsewhere"


def test_move_flow_and_system(run, client):
    """Added in 0.4.0 (design section 9): MOVE handled processes only."""
    out = run(WIDGET + 'MOVE FLOW "Widget" TO "00: Elsewhere/Flows"\n'
              'MOVE SYSTEM "Widget" TO "00: Elsewhere"')
    assert "Moved flow 'Widget' to '00: Elsewhere/Flows'" in out
    assert client.by_name(o.Flow, "Widget")[0].category == "00: Elsewhere/Flows"
    assert client.by_name(o.ProductSystem, "Widget")[0].category == "00: Elsewhere"


def test_cat_and_ls_print_the_same(run):
    assert run("CAT") == run("LS")
    assert "[DIR]  C:Test manufacturing/" in run("CAT")


def test_dir_and_cd_move_the_same_way(run, interp):
    a = run('DIR "C:Test manufacturing"\nPWD')
    interp.runtime.reset()
    b = run('CD "C:Test manufacturing"\nPWD')
    assert a == b and "C:Test manufacturing" in a


def test_dir_unknown_folder(interp):
    with pytest.raises(BasicError) as e:
        interp.run_program('DIR "No such folder"')
    assert "Folder not found" in str(e.value) and "CDIR" in str(e.value)


def test_up_and_cd_dotdot(run, interp):
    run('DIR "D:Test supply"\nDIR "35:Test supply"')
    assert run("UP").strip() == "D:Test supply"
    run('DIR "35:Test supply"')
    assert run("CD ..").strip() == "D:Test supply"


def test_back_toggles(run):
    run('DIR "C:Test manufacturing"\nDIR "/"')
    assert run("BACK").strip() == "C:Test manufacturing"
    assert run("BACK").strip() == "(root)"


def test_cdir_creates_and_enters(run, interp):
    out = run('CDIR "00: New model"')
    assert "Created and moved to: 00: New model" in out
    assert interp.runtime.process_folder == "00: New model"


def test_database_info_and_family(run):
    out = run("PRINT DATABASE")
    assert "Family:          ecoinvent" in out
    out = run('DATABASE FAMILY "flcac"')
    assert "database_family: flcac" in out


def test_refresh_clears_caches(run, engine):
    run("PRINT DATABASE")
    assert engine._cache
    assert "Caches cleared." in run("REFRESH")
    assert not engine._cache
