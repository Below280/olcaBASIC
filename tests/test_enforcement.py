"""Phase 5: the rules the language enforces, and the gaps it closed."""

import pytest
import olca_schema as o

from fake_client import (ELECTRICITY, PLASTIC, STEEL, WATER, FakeClient,
                         seed_ecoinvent_like)
from olcabasic import Session
from olcabasic.enforce import TIER_1_CAVEAT
from test_interpreter_lca import SETUP, WIDGET, WIDGET_FOSSIL


@pytest.fixture
def session(client):
    return Session(client=client)


def err(result):
    assert not result.ok, result.text
    return result.errors[0]


# ── ambiguous USE PROCESS ────────────────────────────────────

def test_ambiguous_name_lists_name_location_and_uuid(session, client):
    e = err(session.run(SETUP + f'''MAKE PROCESS "A"
  OUTPUT MAKE FLOW "A", 1, kg, PRODUCT
  INPUT USE PROCESS "{ELECTRICITY}", 1, kWh
END PROCESS'''))
    assert e["line"] == 7
    assert ELECTRICITY in e["message"] and "matches 3 processes" in e["message"]
    for row in client.by_name(o.Process, ELECTRICITY):
        assert row.id in e["message"]
        assert client._location_code(row.location) in e["message"]
    assert "LOCATION" in e["hint"] and "PROVIDER" in e["hint"]


def test_location_resolves_the_ambiguity(session, client):
    # 0.4.0: a background process is named in a bridge, so that is where
    # the ambiguity is resolved.
    r = session.run(SETUP + f'''BRIDGE "power", kWh
  PROVIDER "{ELECTRICITY}" LOCATION "DE"
END BRIDGE''')
    assert r.ok and not any(w["level"] == "warning" for w in r.warnings)
    ex = [e for e in client.by_name(o.Process, "BRIDGE | power | kWh")[0].exchanges
          if e.is_input][0]
    assert client._location_code(
        client.get(o.Process, ex.default_provider.id).location) == "DE"


def test_an_ambiguous_bridge_provider_is_refused(session):
    e = err(session.run(SETUP + f'''BRIDGE "power", kWh
  PROVIDER "{ELECTRICITY}"
END BRIDGE'''))
    assert "matches 3 processes" in e["message"]
    assert "LOCATION" in e["hint"]


def test_provider_resolves_the_ambiguity(session, client):
    row = client.by_name(o.Process, ELECTRICITY)[1]
    r = session.run(SETUP + f'''BRIDGE "power", kWh
  PROVIDER "{row.id}"
END BRIDGE''')
    assert r.ok, r.errors
    ex = [e for e in client.by_name(o.Process, "BRIDGE | power | kWh")[0].exchanges
          if e.is_input][0]
    assert ex.default_provider.id == row.id


def test_same_name_and_location_needs_a_provider(session, client):
    twin = client.by_name(o.Process, ELECTRICITY)[0]
    copy = client.get(o.Process, twin.id)
    copy.id = "11111111-2222-3333-4444-555555555555"
    client.put(copy)
    code = client._location_code(twin.location)
    e = err(session.run(SETUP + f'''MAKE PROCESS "A"
  OUTPUT MAKE FLOW "A", 1, kg, PRODUCT
  INPUT USE PROCESS "{ELECTRICITY}", 1, kWh LOCATION "{code}"
END PROCESS'''))
    assert f'matches 2 processes at LOCATION "{code}"' in e["message"]
    assert e["hint"].startswith('Add PROVIDER "uuid"')


def test_ambiguity_in_edit_process_is_an_error_too(session):
    session.run(WIDGET)
    e = err(session.run(f'''EDIT PROCESS "Widget"
  ADD INPUT USE PROCESS "{WATER}", 1, kg
END EDIT'''))
    assert e["line"] == 2 and "matches 2 processes" in e["message"]


def test_plain_input_name_is_strict_as_well(session):
    e = err(session.run(SETUP + f'''PROCESS "A"
  OUTPUT MAKE FLOW "A", 1, kg, PRODUCT
  INPUT "{PLASTIC}", 1, kg
END PROCESS'''))
    assert "matches 2 processes" in e["message"]


def test_find_process_shows_location_and_uuid(session, client):
    r = session.run('FIND PROCESS "test electricity"')
    assert "Location" in r.text
    for row in client.by_name(o.Process, ELECTRICITY):
        assert row.id in r.text
    rows = r.data[0]["result"]["processes"]
    assert sorted(p["location"] for p in rows) == ["DE", "GB", "RoW"]


def test_find_process_at_location(session):
    r = session.run('FIND PROCESS "test electricity" AT "GB"')
    assert r.data[0]["result"]["total_matches"] == 1


# ── database family ──────────────────────────────────────────

@pytest.fixture
def unknown_family():
    """A database whose flow properties match neither family."""
    client = FakeClient()
    ug = client.add_unit_group("Units of mass", {"kg": 1.0}, "kg")
    client.add_flow_property("Mass", ug)
    return Session(client=client)


@pytest.mark.parametrize("code,what", [
    ('MAKE FLOW "X", kg, PRODUCT', "MAKE FLOW"),
    ('BRIDGE "X", kg', "BRIDGE"),
    ('MAKE PROCESS "P"\n  OUTPUT MAKE FLOW "P", 1, kg, PRODUCT\nEND PROCESS',
     "MAKE FLOW"),
])
def test_building_is_refused_while_the_family_is_unknown(unknown_family, code, what):
    assert unknown_family.engine.database_family == "unknown"
    e = err(unknown_family.run(code))
    assert "The database family is not known" in e["message"] and what in e["message"]
    assert 'DATABASE FAMILY "ecoinvent"' in e["hint"]
    assert 'DATABASE FAMILY "flcac"' in e["hint"]
    assert unknown_family.client.store["Flow"] == {}


def test_setting_the_family_unblocks_building(unknown_family):
    r = unknown_family.run('DATABASE FAMILY "ecoinvent"\nMAKE FLOW "X", kg, PRODUCT')
    assert r.ok, r.errors
    assert len(unknown_family.client.by_name(o.Flow, "X")) == 1


def test_family_is_detected_on_connect(session):
    assert session.engine.database_family == "ecoinvent"
    assert session.run('MAKE FLOW "Y", kg, PRODUCT').ok


def test_exploring_does_not_need_the_family(unknown_family):
    assert unknown_family.run("DATABASE INFO\nCAT").ok


# ── VALIDATE gates calculations ──────────────────────────────

def break_system(client, name="Widget"):
    """Take the reference product away, so VALIDATE fails."""
    proc = client.by_name(o.Process, name)[0]
    for ex in proc.exchanges:
        ex.is_quantitative_reference = False


@pytest.mark.parametrize("command", [
    'CALCULATE "Widget" USING "EF v3.1"',
    'CONTRIBUTION "Widget" USING "EF v3.1"',
    'MONTECARLO "Widget" USING "EF v3.1" RUNS 3',
    'INVENTORY "Widget" USING "EF v3.1"',
    'TREE "Widget" USING "EF v3.1" CATEGORY "Climate change"',
    'SCENARIO "S"\n  LET elec = 1\nEND SCENARIO\nRUN SCENARIOS ON "Widget" USING "EF v3.1"',
    'SENSITIVITY ON "Widget" USING "EF v3.1" BY 10%\n  VARY elec\nEND SENSITIVITY',
])
def test_calculation_refused_after_a_failed_validate(session, client, command):
    session.run(WIDGET)
    break_system(client)
    v = session.run('VALIDATE "Widget"')
    assert v.ok and "valid: False" in v.text
    assert any("did not pass" in w["message"] for w in v.warnings)
    calls = len(client.results)
    e = err(session.run(command))
    assert "refused: 'Widget' failed VALIDATE earlier in this session" in e["message"]
    assert "has no quantitative reference" in e["message"]
    assert 'DELETE SYSTEM "Widget"' in e["hint"] and "VALIDATE" in e["hint"]
    assert len(client.results) == calls          # nothing was calculated


def test_calculation_allowed_again_once_validate_passes(session, client):
    session.run(WIDGET)
    break_system(client)
    session.run('VALIDATE "Widget"')
    proc = client.by_name(o.Process, "Widget")[0]
    proc.exchanges[0].is_quantitative_reference = True
    assert session.run('VALIDATE "Widget"').ok
    assert session.run('CALCULATE "Widget" USING "EF v3.1"').ok


def test_unvalidated_system_can_be_calculated(session):
    assert session.run(WIDGET + 'CALCULATE "Widget" USING "EF v3.1"').ok


def test_rebuilding_the_system_clears_the_failed_validation(session, client):
    session.run(WIDGET)
    break_system(client)
    session.run('VALIDATE "Widget"')
    proc = client.by_name(o.Process, "Widget")[0]
    proc.exchanges[0].is_quantitative_reference = True
    r = session.run('DELETE SYSTEM "Widget"\nSYSTEM "Widget"\n'
                    'CALCULATE "Widget" USING "EF v3.1"')
    assert r.ok, r.errors


def test_a_failed_validate_holds_in_a_new_session(client):
    """Changed on purpose (12/11/2026): a new session used to start with
    no record, so a system that failed VALIDATE could be calculated
    there. A session with no record now runs VALIDATE itself first."""
    a, b = Session(client=client), Session(client=client)
    a.run(WIDGET)
    break_system(client)
    a.run('VALIDATE "Widget"')
    assert not a.run('CALCULATE "Widget" USING "EF v3.1"').ok
    calls = len(client.results)
    r = b.run('CALCULATE "Widget" USING "EF v3.1"')
    e = err(r)
    assert "failed VALIDATE just now" in e["message"]
    assert len(client.results) == calls


def test_a_failed_validate_holds_after_reset(session, client):
    session.run(WIDGET)
    break_system(client)
    session.run('VALIDATE "Widget"')
    session.reset()
    e = err(session.run('CALCULATE "Widget" USING "EF v3.1"'))
    assert "failed VALIDATE just now" in e["message"]


def test_a_session_with_no_record_validates_first_and_says_so(client):
    Session(client=client).run(WIDGET)
    r = Session(client=client).run('CALCULATE "Widget" USING "EF v3.1"')
    assert r.ok, r.errors
    assert "VALIDATE ran first: passed" in r.text


# ── method names ─────────────────────────────────────────────

@pytest.mark.parametrize("wrong", ["EF 3.1", "ef v3.1", "EF v3", "IPCC"])
def test_near_miss_method_names_fail_with_candidates(session, wrong):
    session.run(WIDGET)
    e = err(session.run(f'CALCULATE "Widget" USING "{wrong}"'))
    assert e["message"] == f"No impact method is called '{wrong}'."
    assert "Close matches:" in e["hint"] and "FIND METHOD" in e["hint"]


def test_ef_31_offers_ef_v31(session):
    session.run(WIDGET)
    e = err(session.run('CALCULATE "Widget" USING "EF 3.1"'))
    assert '"EF v3.1"' in e["hint"] and '"EF v3.1 no LT"' in e["hint"]


def test_exact_method_name_and_uuid_work(session, client):
    session.run(WIDGET)
    assert session.run('CALCULATE "Widget" USING "EF v3.1"').ok
    method = client.by_name(o.ImpactMethod, "IPCC 2021")[0]
    r = session.run(f'CALCULATE "Widget" USING "{method.id}"')
    assert r.ok and r.data[-1]["result"]["method"] == "IPCC 2021"


@pytest.mark.parametrize("command", [
    'CONTRIBUTION "Widget" USING "EF"',
    'INVENTORY "Widget" USING "EF"',
    'MONTECARLO "Widget" USING "EF" RUNS 2',
    'TREE "Widget" USING "EF" CATEGORY "Climate change"',
    'SENSITIVITY ON "Widget" USING "EF" BY 5%\n  VARY elec\nEND SENSITIVITY',
    'SCENARIO "S"\n  LET elec = 1\nEND SCENARIO\nRUN SCENARIOS ON "Widget" USING "EF"',
])
def test_every_analysis_wants_the_full_method_name(session, command):
    session.run(WIDGET)
    e = err(session.run(command))
    assert "No impact method is called 'EF'" in e["message"]


def test_engine_method_lookup_is_unchanged(engine):
    """The engine still accepts a unique part of a name, as the v1 MCP
    tools did. The strictness is the language's."""
    assert engine.find_method("IPCC 2013").name == "IPCC 2013"
    strict = engine.find_method_strict("IPCC 2")
    assert "error" in strict and "IPCC 2021" in strict["candidates"]


# ── CHECK ────────────────────────────────────────────────────

def test_check_tier_1_ends_with_the_fixed_caveat(session):
    session.run(WIDGET)
    r = session.run('CHECK "Widget" TIER 1')
    assert r.ok
    assert r.text.endswith(TIER_1_CAVEAT.format(system="Widget"))
    assert "structure only" in r.text and "TIER 2" in r.text and "TIER 3" in r.text


def test_check_without_tier_is_tier_1_and_says_so(session):
    session.run(WIDGET)
    r = session.run('CHECK "Widget"')
    assert r.text.endswith(TIER_1_CAVEAT.format(system="Widget"))
    assert any("TIER 1" in w["message"] for w in r.warnings)


def test_check_tier_1_counts_as_a_validation(session, client):
    session.run(WIDGET)
    break_system(client)
    session.run('CHECK "Widget" TIER 1')
    assert not session.run('CALCULATE "Widget" USING "EF v3.1"').ok


def test_check_tier_2_and_3(session):
    session.run(WIDGET)
    r2 = session.run('CHECK "Widget" TIER 2 AGAINST "lci.xlsx"')
    assert r2.ok and 'against "lci.xlsx"' in r2.text
    assert r2.data[-1]["call"] == "extract_model"
    r3 = session.run('CHECK "Widget" TIER 3')
    assert r3.ok and "plausible" in r3.text
    assert "no tier 4" in err(session.run('CHECK "Widget" TIER 4'))["message"].lower()


# ── defaults are stated once ─────────────────────────────────

def defaults(result):
    return [w["message"] for w in result.warnings
            if w["message"].startswith("default used:")]


def test_defaults_are_stated(session):
    r = session.run(WIDGET + '''CALCULATE "Widget" USING "EF v3.1"
CONTRIBUTION "Widget" USING "EF v3.1"
MONTECARLO "Widget" USING "EF v3.1"
INVENTORY "Widget" USING "EF v3.1"
TREE "Widget" USING "EF v3.1" CATEGORY "Climate change"''')
    assert r.ok, r.errors
    text = " | ".join(defaults(r))
    for needle in ("LINKING PREFER_DEFAULTS", "TARGET 1", "ALLOCATE AS_DEFINED",
                   "TOP 10", "RUNS 1000", "MAX 50", "LEVELS 3"):
        assert needle in text, needle


def test_each_default_is_stated_once_per_session(session):
    r = session.run(WIDGET + 'CALCULATE "Widget" USING "EF v3.1"\n'
                    'CALCULATE "Widget" USING "IPCC 2021"')
    assert sum("ALLOCATE AS_DEFINED" in d for d in defaults(r)) == 1
    again = session.run('CALCULATE "Widget" USING "EF v3.1"')
    assert defaults(again) == []
    session.reset()
    session.run("LET elec = 2.5")
    assert defaults(session.run('CALCULATE "Widget" USING "EF v3.1"'))


def test_no_default_note_when_the_argument_is_given(session):
    session.run(WIDGET)
    session.reset()
    session.run("LET elec = 2.5")
    r = session.run('CONTRIBUTION "Widget" USING "EF v3.1" TOP 3 ALLOCATE AS_DEFINED\n'
                    'MONTECARLO "Widget" USING "EF v3.1" RUNS 4 ALLOCATE NONE')
    assert r.ok and defaults(r) == []


# ── product system messages ──────────────────────────────────

def test_partial_system_creation_names_the_next_command(session, client):
    session.run(WIDGET.replace('SYSTEM "Widget"', ""))
    original = client.put

    def failing_put(entity):
        if isinstance(entity, o.ProductSystem):
            raise RuntimeError("connection timed out")
        return original(entity)

    client.put = failing_put
    e = err(session.run('SYSTEM "Widget"'))
    assert "was created, but setting it up did not finish" in e["message"]
    assert 'VALIDATE "Widget"' in e["hint"] and 'DELETE SYSTEM "Widget"' in e["hint"]


def test_existing_system_message_names_the_next_command(session):
    session.run(WIDGET)
    r = session.run('SYSTEM "Widget"')
    msg = next(w["message"] for w in r.warnings if w["level"] == "warning")
    assert 'DELETE SYSTEM "Widget"' in msg and 'VALIDATE "Widget"' in msg


def test_session_lock_serialises_system_creation(client):
    import threading
    session = Session(client=client)
    session.run(WIDGET.replace('SYSTEM "Widget"', "")
                + WIDGET.replace("Widget", "Gadget").replace('SYSTEM "Gadget"', ""))
    original, active, peak = client.create_product_system, [0], [0]

    def slow(process, config=None):
        import time
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        try:
            return original(process, config)
        finally:
            active[0] -= 1

    client.create_product_system = slow
    threads = [threading.Thread(target=session.run, args=(f'SYSTEM "{n}"',))
               for n in ("Widget", "Gadget")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak[0] == 1
    assert len(client.store["ProductSystem"]) == 2


# ── bridges ──────────────────────────────────────────────────

def test_bridge_names_are_made_consistent(session, client):
    steel = client.by_name(o.Process, STEEL)[0]
    r = session.run(SETUP + f'''BRIDGE "Steel", kg
  PROVIDER "{steel.id}"
END BRIDGE
BRIDGE "BRIDGE | Water", kg
BRIDGE "BRIDGE | Polymer | kg", kg''')
    assert r.ok, r.errors
    names = {p.name for p in client.store["Process"].values()}
    assert {"BRIDGE | Steel | kg", "BRIDGE | Water | kg",
            "BRIDGE | Polymer | kg"} <= names
    assert "Bridge created: BRIDGE | Steel | kg (kg)" in r.text


def test_bridge_name_and_unit_must_agree(session):
    e = err(session.run('BRIDGE "BRIDGE | Steel | t", kg'))
    assert "ends with 't' but its unit is 'kg'" in e["message"]
    assert '"BRIDGE | Steel | kg"' in e["hint"]


def test_bridge_is_idempotent(session, client):
    code = SETUP + 'BRIDGE "Steel", kg'
    session.run(code)
    r = session.run(code)
    assert "Bridge exists: BRIDGE | Steel | kg" in r.text
    assert len(client.by_name(o.Process, "BRIDGE | Steel | kg")) == 1


def test_old_style_bridge_is_reused_not_duplicated(session, client, engine):
    engine.create_bridge("Legacy steel bridge", "kg", "00: Test")
    r = session.run(SETUP + 'BRIDGE "Legacy steel bridge", kg')
    assert r.ok and "already exists and is reused" in r.text
    assert client.by_name(o.Process, "BRIDGE | Legacy steel bridge | kg") == []


def test_bridge_without_provider_says_so(session):
    r = session.run(SETUP + 'BRIDGE "Loose", kg')
    assert any("no provider yet" in w["message"] for w in r.warnings)


def test_using_a_background_process_directly_is_an_error(session, client):
    # 0.4.0 (design 3.1, rule 1): this was a note; it is an error now, in
    # every program and with no way to switch it off.
    e = err(session.run(SETUP + f'''MAKE PROCESS "Direct"
  OUTPUT MAKE FLOW "Direct", 1, kg, PRODUCT
  INPUT USE PROCESS "{STEEL}", 0.8, kg
END PROCESS'''))
    assert e["line"] == 7
    assert "is a background process" in e["message"]
    assert STEEL in e["message"]
    assert 'BRIDGE "' in e["hint"] and "PROVIDER" in e["hint"]
    assert "END BRIDGE" in e["hint"]
    assert client.by_name(o.Process, "Direct") == []


def test_no_process_folder_does_not_switch_the_rule_off(session):
    e = err(session.run(f'''SET FLOW FOLDER "00: Test"
MAKE PROCESS "Direct"
  FOLDER "00: Test"
  OUTPUT MAKE FLOW "Direct", 1, kg, PRODUCT
  INPUT USE PROCESS "{STEEL}", 0.8, kg
END PROCESS'''))
    assert "is a background process" in e["message"]


def test_edit_cannot_add_a_background_process(session, client):
    session.run(WIDGET)
    e = err(session.run(f'''EDIT PROCESS "Widget"
  ADD INPUT USE PROCESS "{PLASTIC}", 1, kg LOCATION "RER"
END EDIT'''))
    assert e["line"] == 2 and "is a background process" in e["message"]
    widget = client.by_name(o.Process, "Widget")[0]
    assert not any("plastic" in client._flow_name(x.flow.id) for x in widget.exchanges)


def test_link_cannot_point_at_a_background_process(session):
    session.run(WIDGET)
    e = err(session.run(f'LINK PROCESS "{STEEL}" TO PROCESS "Widget" WITH 1, kg'))
    assert "is a background process" in e["message"]


def test_a_process_built_by_the_program_is_not_background(session):
    r = session.run(SETUP + '''MAKE PROCESS "Part"
  FOLDER "Somewhere else"
  OUTPUT MAKE FLOW "Part", 1, kg, PRODUCT
END PROCESS
MAKE PROCESS "Whole"
  OUTPUT MAKE FLOW "Whole", 1, kg, PRODUCT
  INPUT USE PROCESS "Part", 2, kg
END PROCESS''')
    assert r.ok, r.errors


def test_using_bridges_gives_no_lint_note(session, client):
    steel = client.by_name(o.Process, STEEL)[0]
    r = session.run(SETUP + f'''BRIDGE "Steel", kg
  FOLDER "00: Test/Bridges"
  PROVIDER "{steel.id}"
END BRIDGE
MAKE PROCESS "Bridged"
  OUTPUT MAKE FLOW "Bridged", 1, kg, PRODUCT
  INPUT USE PROCESS "BRIDGE | Steel | kg", 2, kg
END PROCESS''')
    assert r.ok, r.errors
    assert not any("background process" in w["message"] for w in r.warnings)


# ── FIND, SHOW ───────────────────────────────────────────────

def test_find_system(session):
    session.run(WIDGET)
    r = session.run('FIND SYSTEM "Wid"')
    assert r.ok and "Widget" in r.text
    assert r.data[0]["result"]["count"] == 1
    assert session.run('FIND SYSTEM "zzz"').data[0]["result"]["count"] == 0


def test_find_method_and_unit(session):
    assert "EF v3.1 no LT" in session.run('FIND METHOD "EF v3.1"').text
    r = session.run('FIND UNIT "t*km"')
    assert r.data[0]["result"]["flow_property_name"] == "Mass transport"


def test_show_system_forms(session):
    session.run(WIDGET)
    r = session.run('SHOW SYSTEM "Widget"')
    assert "not validated in this session" in r.text
    session.run('VALIDATE "Widget"')
    assert "passed VALIDATE" in session.run('SHOW SYSTEM "Widget"').text
    params = session.run('SHOW SYSTEM "Widget" PARAMS').data[0]["result"]
    assert {p["name"] for p in params["parameters"]} >= {"elec"}
    filtered = session.run('SHOW SYSTEM "Widget" PARAMS "elec"').data[0]["result"]
    assert filtered["count"] == 1
    links = session.run('SHOW SYSTEM "Widget" LINKS "steel"').data[0]["result"]
    # Widget to the steel bridge, and the bridge to its provider.
    assert links["total_matching"] == 2
    assert "Product system not found" in err(session.run('SHOW SYSTEM "zz"'))["message"]


def test_show_global_params(session):
    session.run("UPDATE PARAMETER alpha_rate = 1\nUPDATE PARAMETER beta_rate = 2")
    r = session.run("SHOW GLOBAL PARAMS")
    assert "alpha_rate" in r.text and "beta_rate" in r.text
    only = session.run('SHOW GLOBAL PARAMS "alpha"').data[0]["result"]
    assert [p["name"] for p in only["parameters"]] == ["alpha_rate"]


def test_show_process_quality(session):
    session.run(WIDGET)
    r = session.run('SHOW PROCESS "Widget" QUALITY')
    assert r.ok and r.data[0]["call"] == "get_data_quality"


def test_show_flow_usage(session):
    session.run(WIDGET)
    r = session.run('SHOW FLOW "test steel, low-alloyed" USAGE')
    usage = r.data[0]["result"]
    assert r.ok and usage["in_use"]
    assert "[P]    BRIDGE | steel | kg" in r.text and "use(s) found" in r.text
    assert any("LIMIT 10" in w["message"] for w in r.warnings)


def test_show_flow_usage_limit_and_unused(session):
    session.run(WIDGET + 'MAKE FLOW "Orphan", kg, PRODUCT')
    r = session.run('SHOW FLOW "test steel, low-alloyed" USAGE LIMIT 1')
    assert "stopped at LIMIT 1" in r.text
    assert "Not used anywhere" in session.run('SHOW FLOW "Orphan" USAGE').text


def test_show_rejects_a_sub_command_that_does_not_fit(session):
    e = err(session.run('SHOW FLOW "x" INPUTS'))
    assert "SHOW FLOW doesn't take 'INPUTS'" in e["message"] and "USAGE" in e["hint"]


# ── DELETE FLOW ──────────────────────────────────────────────

def test_delete_flow_in_use_is_refused_and_names_the_user(session, client):
    session.run(WIDGET)
    e = err(session.run('DELETE FLOW "Widget"'))
    assert "Flow 'Widget' is still used by Widget" in e["message"]
    assert 'SHOW FLOW "Widget" USAGE' in e["hint"]
    assert len(client.by_name(o.Flow, "Widget")) == 1


def test_delete_flow_after_its_process(session, client):
    session.run(WIDGET)
    r = session.run('DELETE SYSTEM "Widget"\nDELETE PROCESS "Widget"\n'
                    'DELETE FLOW "Widget"')
    assert r.ok, r.errors
    assert client.by_name(o.Flow, "Widget") == []
    assert "Checking where 'Widget' is used" in r.text


def test_delete_flow_reads_every_process(session, client):
    session.run(SETUP + 'MAKE FLOW "Orphan", kg, PRODUCT')
    client.calls.clear()
    assert session.run('DELETE FLOW "Orphan"').ok
    read = {c[2] for c in client.calls if c[:2] == ("get", "Process")}
    assert read >= set(client.store["Process"])


def test_delete_flow_refused_if_a_process_cannot_be_read(session, client):
    session.run(SETUP + 'MAKE FLOW "Orphan", kg, PRODUCT')
    original = client.get
    victim = next(iter(client.store["Process"]))

    def flaky(model_type, uid=None, name=None):
        if model_type is o.Process and uid == victim:
            return None
        return original(model_type, uid, name)

    client.get = flaky
    e = err(session.run('DELETE FLOW "Orphan"'))
    assert "Could not check where 'Orphan' is used" in e["message"]
    assert "search for uses of the flow is incomplete" in e["message"]
    client.get = original
    assert len(client.by_name(o.Flow, "Orphan")) == 1


def test_delete_flow_with_a_characterisation_factor_is_refused(session, client):
    e = err(session.run('CONFIRM DELETE ON\nDELETE FLOW "Methane, fossil"'))
    assert "(impact category)" in e["message"]


def test_delete_flow_used_by_an_epd_dataset_is_refused(session, client):
    session.run(SETUP + 'MAKE FLOW "Declared product", kg, PRODUCT')
    flow = client.by_name(o.Flow, "Declared product")[0]
    client.put(o.Epd(id="epd-1", name="Stored EPD", product=o.EpdProduct(
        flow=o.Ref(id=flow.id), amount=1.0)))
    e = err(session.run('DELETE FLOW "Declared product"'))
    assert "Stored EPD (EPD)" in e["message"]


def test_delete_flow_needs_confirmation(session):
    session.run('SET FLOW FOLDER "00: T"\nMAKE FLOW "Orphan", kg, PRODUCT')
    e = err(session.run('DELETE FLOW "Orphan"'))
    assert "nobody is there to give one" in e["message"]


def test_delete_flow_with_a_shared_name_is_refused(session):
    e = err(session.run('CONFIRM DELETE ON\nDELETE FLOW "Carbon dioxide, fossil"'))
    assert "2 flows are called" in e["message"]


# ── EDIT PROCESS with repeated flows ─────────────────────────

# 0.4.0: the two background processes sit in a bridge, the one place a
# program may name them; the selectors are tested there.
MIX = "BRIDGE | mix | kg"
TWO_WATERS = WIDGET + f'''
BRIDGE "mix", kg
EDIT PROCESS "{MIX}"
  ADD INPUT USE PROCESS "{WATER}", 3, kg LOCATION "RER"
  ADD INPUT USE PROCESS "{WATER}", 7, kg LOCATION "RoW"
END EDIT
'''


def waters(client):
    proc = client.by_name(o.Process, MIX)[0]
    values = {p.name: p.value for p in proc.parameters}
    return sorted(values[ex.amount_formula] for ex in proc.exchanges
                  if client._flow_name(ex.flow.id) == "test water")


def test_removing_a_repeated_flow_needs_a_selector(session, client):
    session.run(TWO_WATERS)
    e = err(session.run(f'EDIT PROCESS "{MIX}"\n  REMOVE INPUT "test water"\nEND EDIT'))
    assert f"'test water' appears 2 times in '{MIX}'" in e["message"]
    assert "INDEX 1" in e["message"] and "INDEX 2" in e["message"]
    assert "[RER]" in e["message"] and "[RoW]" in e["message"]
    assert "INDEX n" in e["hint"] and "PROVIDER, LOCATION or AMOUNT" in e["hint"]
    assert waters(client) == [3.0, 7.0]


@pytest.mark.parametrize("selector,left", [
    ("INDEX 1", [7.0]), ("INDEX 2", [3.0]),
    ('LOCATION "RoW"', [3.0]), ('LOCATION "RER"', [7.0]),
    ("AMOUNT 3", [7.0]), ("AMOUNT 7", [3.0]),
])
def test_remove_one_of_several_same_flow_exchanges(session, client, selector, left):
    session.run(TWO_WATERS)
    r = session.run(f'EDIT PROCESS "{MIX}"\n  REMOVE INPUT "test water" '
                    f'{selector}\nEND EDIT')
    assert r.ok, r.errors
    assert waters(client) == left
    assert "1 exchange(s) removed" in r.text


def test_remove_by_provider_uuid(session, client):
    session.run(TWO_WATERS)
    row = next(p for p in client.by_name(o.Process, WATER)
               if client._location_code(p.location) == "RoW")
    r = session.run(f'EDIT PROCESS "{MIX}"\n  REMOVE INPUT "test water" '
                    f'PROVIDER "{row.id}"\nEND EDIT')
    assert r.ok and waters(client) == [3.0]


def test_selector_that_matches_nothing_lists_the_choices(session):
    session.run(TWO_WATERS)
    e = err(session.run(f'EDIT PROCESS "{MIX}"\n  REMOVE INPUT "test water" '
                        'AMOUNT 99\nEND EDIT'))
    assert "None of the 2 exchanges called 'test water'" in e["message"]
    e = err(session.run(f'EDIT PROCESS "{MIX}"\n  REMOVE INPUT "test water" '
                        'INDEX 5\nEND EDIT'))
    assert "INDEX 5 is out of range" in e["message"]


def test_update_one_of_several_same_flow_exchanges(session, client):
    session.run(TWO_WATERS)
    e = err(session.run(f'EDIT PROCESS "{MIX}"\n  UPDATE INPUT "test water", 9, kg\n'
                        'END EDIT'))
    assert "appears 2 times" in e["message"]
    r = session.run(f'EDIT PROCESS "{MIX}"\n  UPDATE INPUT "test water" INDEX 2, 9, kg\n'
                    'END EDIT')
    assert r.ok, r.errors
    proc = client.by_name(o.Process, MIX)[0]
    amounts = [ex.amount for ex in proc.exchanges
               if client._flow_name(ex.flow.id) == "test water"]
    assert amounts == [0.0, 9.0]


def test_engine_remove_by_flow_id_still_removes_every_copy(engine, client):
    """v1 behaviour of the engine (and the legacy MCP tool) is kept."""
    session = Session(engine=engine)
    session.run(TWO_WATERS)
    proc = client.by_name(o.Process, MIX)[0]
    water = client.by_name(o.Flow, "test water")[0]
    r = engine.edit_process(proc.id, remove_exchanges=[water.id])
    assert r["changes"] == ["2 exchange(s) removed"]


# ── MOVE ─────────────────────────────────────────────────────

def test_move_refuses_a_shared_name(session):
    e = err(session.run('MOVE FLOW "Carbon dioxide, fossil" TO "00: Mine"'))
    assert "2 flows are called" in e["message"] and "Nothing was moved" in e["message"]


def test_move_unknown_thing(session):
    e = err(session.run('MOVE SYSTEM "zzz" TO "00: Mine"'))
    assert "No system is called 'zzz'" in e["message"] and "FIND SYSTEM" in e["hint"]


def test_move_entity_engine(engine, client):
    flow = engine.create_flow("Movable", "kg", "00: A")
    r = engine.move_entity("flow", flow["flow_id"], "00: B")
    assert r == {"moved": True, "entity_type": "flow",
                 "entity_id": flow["flow_id"], "name": "Movable",
                 "from": "00: A", "to": "00: B"}
    assert "Unknown entity type" in engine.move_entity("method", "x", "y")["error"]
    assert "path traversal" in engine.move_entity("flow", flow["flow_id"], "../x")["error"]
    assert "not found" in engine.move_entity("flow", "nope", "00: B")["error"]


# ── small gaps ───────────────────────────────────────────────

def test_max_is_usable_as_a_function(session):
    assert session.run("PRINT MAX(2, 5)\nPRINT MIN(2, 5)").text == "  5\n  2"


def test_sensitivity_needs_by(session):
    e = err(session.run('SENSITIVITY ON "W" USING "EF v3.1"\n  VARY a\nEND SENSITIVITY'))
    assert "SENSITIVITY needs BY" in e["message"]


def test_unknown_allocation_is_a_parse_error(session):
    e = err(session.run('CALCULATE "W" USING "EF v3.1" ALLOCATE MAGIC'))
    assert "Unknown allocation method 'MAGIC'" in e["message"]
    assert "AS_DEFINED" in e["hint"]


def test_save_program_writes_what_ran(session, tmp_path):
    target = tmp_path / "work.baslca"
    session.run("LET a = 1")
    session.run("PRINT missing_variable")            # failed: not saved
    session.run('LET b = a + 1\nPRINT b')
    r = session.run(f'SAVE PROGRAM "{target.as_posix()}"')
    assert r.ok and "Program saved to" in r.text
    assert target.read_text(encoding="utf-8") == "LET a = 1\nLET b = a + 1\nPRINT b\n"
    replay = Session(offline=True).run(f'RUN "{target.as_posix()}"')
    assert replay.ok and replay.text.strip() == "2"


def test_save_with_baslca_name_saves_the_program(session, tmp_path):
    target = tmp_path / "x.baslca"
    session.run("LET a = 1")
    assert session.run(f'SAVE "{target.as_posix()}"').ok
    assert "LET a = 1" in target.read_text(encoding="utf-8")


def test_save_program_with_nothing_to_save(session):
    e = err(session.run('SAVE PROGRAM "x.baslca"'))
    assert "nothing to save yet" in e["message"]


def test_save_csv_still_saves_results(session, tmp_path):
    target = tmp_path / "r.csv"
    r = session.run(WIDGET + f'CALCULATE "Widget" USING "EF v3.1"\n'
                    f'SAVE "{target.as_posix()}"')
    assert r.ok and "Climate change" in target.read_text(encoding="utf-8")
