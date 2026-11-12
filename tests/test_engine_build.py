"""Engine tests against the fake client: build, edit, delete."""

import pytest
import olca_schema as o

from fake_client import ELECTRICITY, STEEL, WATER


@pytest.fixture
def steel_id(client):
    return client.by_name(o.Process, STEEL)[0].id


@pytest.fixture
def widget(engine, client, steel_id):
    """A small process: 1 kg Widget from 2 kg steel."""
    flow = engine.create_flow("Widget", "kg", "00: Test")
    steel_flow = client.by_name(o.Flow, "test steel, low-alloyed")[0]
    result = engine.create_process("Widget", "00: Test", [
        {"flow_id": flow["flow_id"], "unit": "kg", "amount": 1.0,
         "is_input": False, "is_qref": True},
        {"flow_id": steel_flow.id, "unit": "kg", "amount": 2.0,
         "is_input": True, "provider_id": steel_id},
    ])
    assert "error" not in result, result
    return result


# ── create_flow ──────────────────────────────────────────────

def test_create_flow(engine, client):
    r = engine.create_flow("Gadget", "kg", "00: Test", "product")
    assert r["flow_property"] == "Mass" and r["category"] == "00: Test"
    flow = client.store["Flow"][r["flow_id"]]
    assert flow.flow_type == o.FlowType.PRODUCT_FLOW
    assert flow.flow_properties[0].is_ref_flow_property


def test_create_flow_is_idempotent(engine, client):
    a = engine.create_flow("Gadget", "kg", "00: Test")
    b = engine.create_flow("Gadget", "kg", "00: Test")
    assert b["already_existed"] and b["flow_id"] == a["flow_id"]
    assert len(client.by_name(o.Flow, "Gadget")) == 1


@pytest.mark.parametrize("unit,prop", [
    ("kWh", "Energy"), ("m3", "Volume"), ("t*km", "Mass transport"), ("h", "Time"),
])
def test_create_flow_picks_the_flow_property_from_the_unit(engine, unit, prop):
    assert engine.create_flow(f"Flow in {unit}", unit)["flow_property"] == prop


@pytest.mark.parametrize("kwargs,needle", [
    (dict(name="", unit_name="kg"), "cannot be empty"),
    (dict(name="   ", unit_name="kg"), "cannot be empty"),
    (dict(name="x", unit_name="kg", category="a/../b"), "path traversal"),
    (dict(name="x" * 251, unit_name="kg"), "max 250"),
    (dict(name="x", unit_name="furlong"), "No flow property mapping"),
    (dict(name="x", unit_name="kg", flow_type="gas"), "Invalid flow_type"),
])
def test_create_flow_refusals(engine, kwargs, needle):
    assert needle in engine.create_flow(**kwargs)["error"]


def test_create_waste_and_elementary_flows(engine, client):
    w = engine.create_flow("Scrap", "kg", "00: Test", "waste")
    e = engine.create_flow("New gas", "kg", "Elementary flows/Emission to air", "elementary")
    assert client.store["Flow"][w["flow_id"]].flow_type == o.FlowType.WASTE_FLOW
    assert client.store["Flow"][e["flow_id"]].flow_type == o.FlowType.ELEMENTARY_FLOW


# ── create_process ───────────────────────────────────────────

def test_create_process_shape(widget, client):
    assert widget["exchange_count"] == 2 and widget["parameter_count"] == 2
    assert widget["auto_parametrised"] == 2
    proc = client.store["Process"][widget["process_id"]]
    assert proc.process_type == o.ProcessType.UNIT_PROCESS
    assert [ex.internal_id for ex in proc.exchanges] == [1, 2]


def test_create_process_auto_parameters(widget, client):
    proc = client.store["Process"][widget["process_id"]]
    assert all(ex.amount == 0.0 and ex.amount_formula for ex in proc.exchanges)
    values = {p.name: p.value for p in proc.parameters}
    assert values == {"p00_Widget__Widget_kg": 1.0,
                      "p01_Widget__test_steel_low_alloy_kg": 2.0}


def test_create_process_already_exists(engine, widget):
    again = engine.create_process("Widget", "00: Test", [
        {"flow_id": "x", "unit": "kg", "is_input": False, "is_qref": True}])
    assert again["already_existed"] and again["process_id"] == widget["process_id"]


def test_create_process_explicit_formula_is_kept(engine, client, steel_id):
    flow = engine.create_flow("Formula product", "kg", "00: Test")
    steel_flow = client.by_name(o.Flow, "test steel, low-alloyed")[0]
    r = engine.create_process("Formula product", "00: Test", [
        {"flow_id": flow["flow_id"], "unit": "kg", "amount": 1, "is_input": False,
         "is_qref": True},
        {"flow_id": steel_flow.id, "unit": "kg", "formula": "mass * 2",
         "is_input": True},
    ], parameters=[{"name": "mass", "value": 3.0},
                   {"name": "double", "formula": "mass * 2"}])
    proc = client.store["Process"][r["process_id"]]
    assert proc.exchanges[1].amount_formula == "mass * 2"
    by_name = {p.name: p for p in proc.parameters}
    assert by_name["mass"].is_input_parameter and by_name["mass"].value == 3.0
    assert by_name["double"].formula == "mass * 2"
    assert not by_name["double"].is_input_parameter


def test_create_process_location(engine, client):
    flow = engine.create_flow("Located", "kg", "00: Test")
    r = engine.create_process("Located", "00: Test", [
        {"flow_id": flow["flow_id"], "unit": "kg", "amount": 1, "is_input": False,
         "is_qref": True}], location="United Kingdom")
    proc = client.store["Process"][r["process_id"]]
    assert proc.location.name == "United Kingdom"


@pytest.mark.parametrize("exchanges,needle", [
    ([], "At least one exchange is required"),
    ([{"flow_id": "FLOW", "unit": "kg", "is_input": True}],
     "No quantitative reference found"),
    ([{"flow_id": "FLOW", "unit": "kg", "is_input": False, "is_qref": True},
      {"flow_id": "FLOW", "unit": "kg", "is_input": False, "is_qref": True}],
     "Found 2 quantitative references"),
    ([{"flow_id": "FLOW", "unit": "kg", "amount": -1, "is_input": False,
       "is_qref": True}], "cannot be negative"),
    ([{"flow_id": "00000000-0000-0000-0000-000000000000", "unit": "kg",
       "is_input": False, "is_qref": True}], "not found in connected database"),
    ([{"flow_id": "FLOW", "unit": "kWh", "is_input": False, "is_qref": True}],
     "unit 'kWh' isn't available for flow"),
    ([{"flow_id": "FLOW", "unit": "kg", "formula": "__import__('os')",
       "is_input": False, "is_qref": True}], "disallowed pattern"),
    ([{"flow_id": "FLOW", "unit": "kg", "is_input": False, "is_qref": True,
       "provider_id": "00000000-0000-0000-0000-000000000001"}],
     "provider_id"),
])
def test_create_process_refusals(engine, exchanges, needle):
    flow = engine.create_flow("Refusal flow", "kg", "00: Test")
    for ex in exchanges:
        if ex["flow_id"] == "FLOW":
            ex["flow_id"] = flow["flow_id"]
    r = engine.create_process("Refused", "00: Test", exchanges)
    assert needle in r["error"]


def test_create_process_name_and_category_checks(engine):
    assert "cannot be empty" in engine.create_process("", "c", [{}])["error"]
    assert "path traversal" in engine.create_process("x", "../c", [{}])["error"]
    assert "max 7" in engine.create_process("x", "a/b/c/d/e/f/g/h", [{}])["error"]


def test_create_process_bad_parameter_name(engine):
    flow = engine.create_flow("Param flow", "kg", "00: Test")
    r = engine.create_process("Param test", "00: Test", [
        {"flow_id": flow["flow_id"], "unit": "kg", "is_input": False,
         "is_qref": True}], parameters=[{"name": "2fast", "value": 1}])
    assert "name '2fast' is invalid" in r["error"]


def test_pedigree_needs_a_flow_schema(engine):
    flow = engine.create_flow("DQ flow", "kg", "00: Test")
    ex = [{"flow_id": flow["flow_id"], "unit": "kg", "amount": 1, "is_input": False,
           "is_qref": True, "dq_entry": "(1;2;3;4;5)"}]
    assert "Set flow_schema" in engine.create_process("DQ a", "00: Test", ex)["error"]
    r = engine.create_process("DQ b", "00: Test", ex, flow_schema="Test Pedigree Matrix")
    assert r["flow_schema"] == "Test Pedigree Matrix"
    ex[0]["dq_entry"] = "(1;2;3)"
    r = engine.create_process("DQ c", "00: Test", ex, flow_schema="Test Pedigree Matrix")
    assert "has 3 pedigree scores" in r["error"]


# ── create_bridge ────────────────────────────────────────────

def test_create_bridge(engine, client, steel_id):
    r = engine.create_bridge("BRIDGE | Steel | kg", "kg", "00: Test/Bridges", steel_id)
    assert r["exchange_count"] == 2
    assert r["background_flow"] == "test steel, low-alloyed"
    proc = client.store["Process"][r["process_id"]]
    assert proc.exchanges[1].default_provider.id == steel_id
    again = engine.create_bridge("BRIDGE | Steel | kg", "kg", "00: Test/Bridges", steel_id)
    assert again["already_existed"] and again["flow_id"] == r["flow_id"]


def test_create_bridge_without_provider_says_so(engine):
    r = engine.create_bridge("BRIDGE | Loose | kg", "kg", "00: Test/Bridges")
    assert r["exchange_count"] == 1 and "No provider set" in r["note"]


def test_create_bridge_rejects_a_bad_provider_id(engine):
    r = engine.create_bridge("BRIDGE | Bad | kg", "kg", "", "not-a-uuid")
    assert "is not a valid UUID" in r["error"]


def test_create_waste_bridge(engine, client):
    from fake_client import LANDFILL
    landfill = client.by_name(o.Process, LANDFILL)[0]
    r = engine.create_bridge("BRIDGE | Landfill | kg", "kg", "00: Test/Bridges",
                             landfill.id, waste=True)
    proc = client.store["Process"][r["process_id"]]
    assert proc.exchanges[0].is_input and proc.exchanges[0].is_quantitative_reference
    assert not proc.exchanges[1].is_input


# ── edit_process ─────────────────────────────────────────────

def test_edit_process_description_category_location(engine, client, widget):
    r = engine.edit_process(widget["process_id"], description="d",
                            category="00: Other", location="Germany")
    assert r["changes"] == ["description updated", "category set to '00: Other'",
                            "location set to 'Germany'"]
    proc = client.store["Process"][widget["process_id"]]
    assert (proc.description, proc.category, proc.location.name) == (
        "d", "00: Other", "Germany")


def test_edit_process_update_and_remove_exchange(engine, client, widget):
    steel_flow = client.by_name(o.Flow, "test steel, low-alloyed")[0]
    r = engine.edit_process(widget["process_id"], update_exchanges=[
        {"flow_id": steel_flow.id, "amount": 5.0, "unit": "t"}])
    assert "amount set to 5.0" in r["changes"][0]
    ex = client.store["Process"][widget["process_id"]].exchanges[1]
    assert ex.amount == 5.0 and ex.unit.name == "t"
    r = engine.edit_process(widget["process_id"], remove_exchanges=[steel_flow.id])
    assert r["changes"] == ["1 exchange(s) removed"] and r["exchange_count"] == 1


def test_edit_process_add_exchange_and_parameters(engine, client, widget):
    water = client.by_name(o.Process, WATER)[0]
    water_flow = client.by_name(o.Flow, "test water")[0]
    r = engine.edit_process(
        widget["process_id"],
        add_exchanges=[{"flow_id": water_flow.id, "unit": "kg", "amount": 7.0,
                        "is_input": True, "provider_id": water.id}],
        add_parameters=[{"name": "extra", "value": 1.0}],
        update_parameters={"p00_Widget__Widget_kg": 2.0})
    assert r["exchange_count"] == 3 and r["parameter_count"] == 4
    proc = client.store["Process"][widget["process_id"]]
    assert proc.exchanges[-1].internal_id == 3
    assert proc.exchanges[-1].amount_formula == "p03_Widget__test_water_kg"
    assert {p.name: p.value for p in proc.parameters}["p00_Widget__Widget_kg"] == 2.0


def test_edit_process_warns_about_what_it_could_not_find(engine, widget):
    r = engine.edit_process(
        widget["process_id"],
        remove_exchanges=["11111111-1111-1111-1111-111111111111"],
        update_exchanges=[{"flow_id": "22222222-2222-2222-2222-222222222222",
                           "amount": 1}],
        update_parameters={"missing": 1.0})
    assert sum(1 for c in r["changes"] if c.startswith("WARNING")) == 3


def test_edit_process_refusals(engine, widget):
    assert "Process not found" in engine.edit_process(
        "00000000-0000-0000-0000-000000000000", description="x")["error"]
    assert "path traversal" in engine.edit_process(
        widget["process_id"], category="../x")["error"]
    assert "is invalid" in engine.edit_process(
        widget["process_id"], add_parameters=[{"name": "bad name"}])["error"]


def test_edit_process_bad_unit_writes_nothing(engine, client, widget):
    steel_flow = client.by_name(o.Flow, "test steel, low-alloyed")[0]
    puts = sum(1 for c in client.calls if c[0] == "put")
    r = engine.edit_process(widget["process_id"], update_exchanges=[
        {"flow_id": steel_flow.id, "amount": 5.0, "unit": "kWh"}])
    assert "isn't available for flow" in r["error"]
    assert sum(1 for c in client.calls if c[0] == "put") == puts


# ── edit_flow ────────────────────────────────────────────────

def test_edit_flow_add_update_and_reference(engine, client):
    flow = engine.create_flow("Concrete", "m3", "00: Test")
    r = engine.edit_flow(flow["flow_id"], [
        {"op": "add", "property": "Mass", "amount": 2400.0, "unit": "kg",
         "per_unit": "m3"}])
    assert "error" not in r and r["flow_name"] == "Concrete"
    r = engine.edit_flow(flow["flow_id"], [
        {"op": "update", "property": "Mass", "amount": 2350.0, "unit": "kg",
         "per_unit": "m3"}])
    stored = client.store["Flow"][flow["flow_id"]]
    mass = next(f for f in stored.flow_properties if f.flow_property.name == "Mass")
    assert mass.conversion_factor == pytest.approx(2350.0)
    r = engine.edit_flow(flow["flow_id"], [{"op": "reference", "property": "Mass"}])
    assert "error" not in r


def test_edit_flow_refusals(engine):
    flow = engine.create_flow("Concrete", "m3", "00: Test")
    assert "error" in engine.edit_flow("00000000-0000-0000-0000-000000000000", [
        {"op": "reference", "property": "Mass"}])
    assert "error" in engine.edit_flow(flow["flow_id"], [
        {"op": "add", "property": "No such property", "amount": 1.0,
         "unit": "kg", "per_unit": "m3"}])


# ── create_global_parameter ──────────────────────────────────

def test_create_global_parameter_value_then_update(engine, client):
    a = engine.create_global_parameter("rate", value=2.0)
    assert a["is_input"] and not a["already_existed"]
    b = engine.create_global_parameter("rate", value=3.0)
    assert b["already_existed"] and b["changed"] and b["previous"]["value"] == 2.0
    assert b["parameter_id"] == a["parameter_id"]
    assert len(client.by_name(o.Parameter, "rate")) == 1


def test_create_global_parameter_formula(engine, client):
    engine.create_global_parameter("base", value=2.0)
    r = engine.create_global_parameter("double", formula="base * 2")
    assert not r["is_input"] and r["formula"] == "base * 2"
    stored = client.by_name(o.Parameter, "double")[0]
    assert stored.value is None and not stored.is_input_parameter


def test_same_value_is_not_reported_as_changed(engine):
    engine.create_global_parameter("rate", value=2.0)
    assert "changed" not in engine.create_global_parameter("rate", value=2.0)


@pytest.mark.parametrize("kwargs,needle", [
    (dict(name="2x", value=1.0), "is invalid"),
    (dict(name="x"), "Give exactly one of value"),
    (dict(name="x", value=1.0, formula="y"), "Give exactly one of value"),
    (dict(name="x", formula="x * 2"), "refers to itself"),
    (dict(name="x", formula="eval(1)"), "disallowed pattern"),
])
def test_create_global_parameter_refusals(engine, kwargs, needle):
    assert needle in engine.create_global_parameter(**kwargs)["error"]


# ── delete_entity ────────────────────────────────────────────

def test_delete_process_and_system(engine, client, widget):
    system = engine.create_product_system("Widget")
    r = engine.delete_entity("product_system", system["system_id"])
    assert r == {"deleted": True, "entity_type": "product_system",
                 "entity_id": system["system_id"], "name": "Widget"}
    assert engine.delete_entity("process", widget["process_id"])["deleted"]
    assert client.by_name(o.Process, "Widget") == []


def test_delete_refusals(engine):
    assert "Unknown entity type" in engine.delete_entity("method", "x")["error"]
    assert "not found" in engine.delete_entity(
        "process", "00000000-0000-0000-0000-000000000000")["error"]


def test_delete_flow_in_use_is_refused(engine, client, widget):
    steel_flow = client.by_name(o.Flow, "test steel, low-alloyed")[0]
    r = engine.delete_entity("flow", steel_flow.id)
    assert r["in_use"] and "is still used by" in r["error"]
    assert steel_flow.id in client.store["Flow"]


def test_delete_unused_flow(engine, client):
    flow = engine.create_flow("Orphan", "kg", "00: Test")
    assert engine.delete_entity("flow", flow["flow_id"])["deleted"]
    assert flow["flow_id"] not in client.store["Flow"]


def test_delete_elementary_flow_with_a_factor_is_refused(engine, client):
    co2 = client.by_name(o.Flow, "Carbon dioxide, fossil")[0]
    r = engine.delete_entity("flow", co2.id)
    assert r["in_use"] and "(impact category)" in r["error"]


def test_find_flow_usage(engine, client, widget):
    steel_flow = client.by_name(o.Flow, "test steel, low-alloyed")[0]
    r = engine.find_flow_usage(steel_flow.id)
    assert r["in_use"] and r["complete"]
    assert "Widget" in r["used_by_processes"]
    assert r["processes_checked"] == r["processes_total"]


# ── systems, search, misc ────────────────────────────────────

def test_create_product_system(engine, widget):
    r = engine.create_product_system("Widget")
    assert r["system_name"] == "Widget" and r["linking"] == "prefer_defaults"
    assert len(r["linked_providers"]) == 1
    again = engine.create_product_system("Widget")
    assert again["already_existed"] and again["system_id"] == r["system_id"]


def test_create_product_system_refusals(engine, widget):
    assert "Process not found" in engine.create_product_system("Nope")["error"]
    assert "must be positive" in engine.create_product_system(
        "Widget", target_amount=-1)["error"]
    assert "not found" in engine.create_product_system(
        "Widget", target_unit="furlong")["error"]


def test_create_product_system_target(engine, client, widget):
    r = engine.create_product_system("Widget", target_amount=3.0, target_unit="t",
                                     category="00: Test")
    system = client.store["ProductSystem"][r["system_id"]]
    assert system.target_amount == 3.0 and system.target_unit.name == "t"
    calc = engine.calculate_impacts("Widget", "EF v3.1")
    fossil = next(i for i in calc["impacts"] if i["category"] == "Climate change: fossil")
    assert fossil["amount"] == pytest.approx(3000 * 2 * 2.0)


def test_search_processes(engine):
    r = engine.search_processes("test electricity")
    assert r["total_matches"] == 3 and not r["truncated"]
    assert set(r["processes"][0]) == {"id", "name", "category"}
    assert "limit must be a positive integer" in engine.search_processes("x", limit=0)["error"]


def test_search_flows_by_category(engine):
    r = engine.search_flows(category_filter="Elementary flows/Emission to air")
    assert r["count"] == 3


def test_database_info_and_family(engine):
    info = engine.get_database_info()
    assert info["status"] == "connected" and info["database_family"] == "ecoinvent"
    assert engine.set_database_family("flcac")["database_family"] == "flcac"
    assert "Unknown family" in engine.set_database_family("simapro")["error"]


def test_find_unit(engine):
    r = engine.find_unit("kWh")
    assert r["unit_name"] == "kWh" and r["flow_property_name"] == "Energy"
    assert "not found" in engine.find_unit("furlong")["error"]


def test_list_methods_and_dq_systems(engine):
    assert engine.list_impact_methods("IPCC")["count"] == 3
    dq = engine.list_dq_systems()
    assert dq["count"] == 2 and dq["dq_systems"][0]["indicator_count"] in (4, 5)


def test_process_details_shape(engine, widget):
    d = engine.get_process_details(widget["process_id"])
    assert set(d) == {"id", "name", "category", "location", "description",
                      "exchanges", "parameters"}
    assert set(d["exchanges"][0]) == {"flow", "amount", "formula", "unit",
                                      "is_input", "is_qref", "provider"}


def test_scenarios_and_sensitivity_shapes(engine, widget):
    engine.create_product_system("Widget")
    name = "p01_Widget__test_steel_low_alloy_kg"
    s = engine.run_scenarios("Widget", "IPCC 2021", {"More": {name: 4.0, "nope": 1}})
    assert set(s) >= {"system", "method", "scenario_count", "results", "missing"}
    assert s["missing"] == ["nope"]
    v = engine.run_sensitivity("Widget", "IPCC 2021", [name], 20.0)
    assert set(v) == {"system", "method", "variation_pct", "baseline",
                      "sensitivity", "tested", "missing"}
    assert set(v["sensitivity"][name]) == {"baseline_value", "minus", "plus"}
    assert "variation_pct must be positive" in engine.run_sensitivity(
        "Widget", "IPCC 2021", [name], 0)["error"]


def test_validate_system_shape(engine, widget):
    engine.create_product_system("Widget")
    v = engine.validate_system("Widget")
    assert v["valid"] and set(v) == {"system", "system_id", "valid", "summary",
                                     "findings"}
    assert "error" in engine.validate_system("Nope")


def test_audit_and_extract_run(engine, widget):
    assert "error" not in engine.extract_model("00: Test")
    assert "error" not in engine.audit_model("00: Test")


def test_allocation_names(engine):
    assert engine._resolve_allocation(None) == o.AllocationType.USE_DEFAULT_ALLOCATION
    assert engine._resolve_allocation("Economic") == o.AllocationType.ECONOMIC_ALLOCATION
    with pytest.raises(ValueError):
        engine._resolve_allocation("magic")


def test_every_calculation_result_is_disposed(engine, client, widget):
    engine.create_product_system("Widget")
    engine.calculate_impacts("Widget", "EF v3.1")
    engine.contribution_analysis("Widget", "EF v3.1")
    engine.inventory_flows("Widget", "EF v3.1")
    engine.monte_carlo("Widget", "EF v3.1", 3)
    engine.upstream_tree("Widget", "EF v3.1", "Climate change")
    assert len(client.results) >= 5 and client.undisposed() == 0
