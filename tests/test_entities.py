"""Every entity type: the generic FIND, SHOW, DELETE, MOVE and EXPORT,
the MAKE and EDIT blocks, impact methods, projects, stored results.

All data here is synthetic.
"""

import json

import pytest
import olca_schema as o

from olcabasic import Session
from olcabasic.engine.entities import ENTITY_TYPES, OWN_TAG
from olcabasic.errors import BasicError
from olcabasic.parser import ParseError, parse
from test_interpreter_lca import SETUP, WIDGET

EF = "EF v3.1"
FOLDER = "00: Test"


@pytest.fixture
def session(client):
    s = Session(client=client)
    assert s.run(SETUP).ok
    return s


def ok(session, code):
    r = session.run(code)
    assert r.ok, f"{r.errors}\n{r.text}"
    return r


def err(session, code):
    r = session.run(code)
    assert not r.ok, r.text
    return r.errors[0]


def one(client, cls, name):
    found = client.by_name(cls, name)
    assert len(found) == 1, f"{len(found)} {cls.__name__} called {name}"
    return found[0]


def _answers(monkeypatch, *replies):
    asked, it = [], iter(replies)

    def fake_input(prompt=""):
        asked.append(prompt)
        return next(it)
    monkeypatch.setattr("builtins.input", fake_input)
    return asked


METHOD = '''
MAKE METHOD "Test method"
    DESCRIPTION "A synthetic method"
    CATEGORY "Test climate" UNIT "kg CO2 eq" CODE "GWP"
        PARAM gwp_ch4 = 29.8
        FACTOR "Carbon dioxide, fossil" IN "unspecified", 1
        FACTOR "Methane, fossil", 29.8
    END CATEGORY
    CATEGORY "Test water" UNIT "m3" INPUT
        FACTOR "Water, river", 1 PER m3
    END CATEGORY
    NW SET "Test world" UNIT "pt"
        "Test climate", 8000, 0.25
        "Test water", 100, 0.75
    END NW SET
END METHOD
'''


# ── the type words ───────────────────────────────────────────

def test_there_are_eighteen_types():
    assert len(ENTITY_TYPES) == 18
    assert sum(1 for cls, _ in ENTITY_TYPES.values() if cls is None) == 1


@pytest.mark.parametrize("word", [w for w in ENTITY_TYPES
                                  if w not in ("PROCESS", "FLOW", "SYSTEM",
                                               "METHOD", "FLOW MAP")])
def test_find_works_for_every_type(session, word):
    r = ok(session, f"FIND {word}")
    assert r.data[-1]["call"] == "find_entities"
    assert r.data[-1]["result"]["type"] == word


@pytest.mark.parametrize("line,word", [
    ('FIND FLOW PROPERTY "Mass"', "PROPERTY"),
    ('FIND UNIT GROUP "mass"', "UNITS"),
    ('FIND IMPACT CATEGORY "Climate"', "CATEGORY"),
    ('FIND STORED RESULT', "RESULT")])
def test_longer_ways_of_saying_a_type(session, line, word):
    r = ok(session, line)
    assert r.data[-1]["result"]["type"] == word


def test_the_old_find_commands_are_unchanged(session):
    assert ok(session, 'FIND METHOD "EF"').data[-1]["call"] == "list_methods"
    assert ok(session, 'FIND UNIT "kg"').data[-1]["call"] == "find_unit"
    assert ok(session, 'FIND FLOW "steel"').data[-1]["call"] == "search_flows"


def test_find_by_part_of_a_name_and_folder(session):
    r = ok(session, 'FIND PROPERTY "mass"')
    names = [e["name"] for e in r.data[-1]["result"]["entities"]]
    assert names == ["Mass", "Mass transport"]
    ok(session, 'MAKE ACTOR "Synthetic Ltd"\nEND ACTOR')
    ok(session, 'MAKE ACTOR "Other Ltd" FOLDER "elsewhere"\nEND ACTOR')
    r = ok(session, f'FIND ACTOR IN "{FOLDER}"')
    assert [e["name"] for e in r.data[-1]["result"]["entities"]] == [
        "Synthetic Ltd"]
    assert "Synthetic Ltd" in r.text and "Other Ltd" not in r.text


def test_find_with_nothing_found_says_so(session):
    assert "This database has no projects" in ok(session, "FIND PROJECT").text
    assert "No actor matches 'zzz'" in ok(session, 'FIND ACTOR "zzz"').text


@pytest.mark.parametrize("line", [
    "FIND FLOW MAP", 'SHOW FLOW MAP "x"', 'DELETE FLOW MAP "x"',
    'MOVE FLOW MAP "x" TO "y"', 'MAKE FLOW MAP "x"'])
def test_flow_maps_are_refused_plainly(session, line):
    e = err(session, "CONFIRM DELETE ON\n" + line)
    text = e["message"] + " " + e["hint"]
    assert "flow map" in text and "IPC" in text
    assert "import" in text


def test_a_word_that_is_no_type_is_refused(session):
    e = err(session, 'DELETE WIDGET "x"')
    assert "Say what to delete" in e["message"]
    e = err(session, 'MAKE WIDGET "x"')
    assert "MAKE cannot make 'WIDGET'" in e["message"]
    assert "ACTOR" in e["hint"]
    e = err(session, 'EDIT WIDGET "x"')
    assert "EDIT cannot change 'WIDGET'" in e["message"]


@pytest.mark.parametrize("line,hint", [
    ('MAKE PARAMETER "x"', "LET name = value"),
    ('MAKE CATEGORY "x"', "MAKE METHOD"),
    ('MAKE RESULT "x"', "SAVE RESULT AS"),
    ('MAKE EPD "x"', "EPD SAVE")])
def test_make_says_how_the_other_types_are_made(session, line, hint):
    assert hint in err(session, line)["hint"]


# ── SHOW ─────────────────────────────────────────────────────

def test_show_json_is_the_entity_as_openlca_stores_it(session, client):
    r = ok(session, 'SHOW LOCATION "Germany" JSON')
    data = json.loads(r.text[r.text.index("{"):])
    assert data["@type"] == "Location" and data["code"] == "DE"
    assert r.data[-1]["result"]["json"] == data
    assert not [c for c in client.calls if c[0] == "put"]


@pytest.mark.parametrize("line,kind", [
    ('SHOW FLOW "test steel, low-alloyed" JSON', "Flow"),
    ('SHOW METHOD "EF v3.1" JSON', "ImpactMethod"),
    ('SHOW DQ SYSTEM "Test Pedigree Matrix" JSON', "DQSystem"),
    ('SHOW UNITS "Units of mass" JSON', "UnitGroup"),
    ('SHOW PROPERTY "Mass" JSON', "FlowProperty")])
def test_show_json_for_other_types(session, line, kind):
    r = ok(session, line)
    assert json.loads(r.text[r.text.index("{"):])["@type"] == kind


def test_show_json_for_a_process_and_a_system(session):
    ok(session, WIDGET)
    for line in ('SHOW PROCESS "Widget" JSON', 'SHOW SYSTEM "Widget" JSON'):
        r = ok(session, line)
        assert json.loads(r.text[r.text.index("{"):])["name"] == "Widget"


def test_there_is_no_command_that_writes_json(session):
    for line in ('MAKE ACTOR "x" JSON "{}"', 'PUT JSON "{}"',
                 'EDIT ACTOR "x" JSON "{}"'):
        assert not session.run(line).ok


def test_show_takes_json_or_usage_and_nothing_else(session):
    e = err(session, 'SHOW ACTOR "x" RAW')
    assert "doesn't take 'RAW'" in e["message"]
    assert "JSON" in e["hint"] and "USAGE" in e["hint"]


def test_show_of_a_missing_entity(session):
    e = err(session, 'SHOW ACTOR "Nobody"')
    assert e["message"] == "No actor is called 'Nobody'."
    assert 'FIND ACTOR "Nobody"' in e["hint"]


def test_show_of_an_ambiguous_name_lists_the_uuids(session, client):
    for i in (1, 2):
        client.store["Actor"][f"a{i}"] = o.Actor(id=f"a{i}", name="Twin",
                                                 category=f"folder {i}")
    e = err(session, 'SHOW ACTOR "Twin"')
    assert "matches 2 actors" in e["message"]
    assert "a1" in e["message"] and "folder 2" in e["message"]
    assert "UUID" in e["hint"]
    assert "Twin" in ok(session, 'SHOW ACTOR "a2"').text


def test_show_method_and_category(session):
    text = ok(session, f'SHOW METHOD "{EF}"').text
    assert "Made by olcaBASIC: NO" in text
    assert "Climate change: fossil" in text
    text = ok(session, 'SHOW CATEGORY "ef-climate"' if False else
              'FIND CATEGORY "Climate change: fossil"').text
    assert "Climate change: fossil" in text


# ── actors, sources ──────────────────────────────────────────

def test_make_actor(session, client):
    r = ok(session, '''
MAKE ACTOR "Synthetic Ltd"
    ADDRESS "1 Test Street"
    CITY "Leeds"
    POSTCODE "LS1 1AA"
    COUNTRY "United Kingdom"
    EMAIL "lca@example.org"
    PHONE "0113 000 0000"
    WEBSITE "https://example.org"
    DESCRIPTION "A synthetic company"
END ACTOR''')
    a = one(client, o.Actor, "Synthetic Ltd")
    assert (a.address, a.city, a.zip_code, a.country, a.email, a.telephone,
            a.website, a.description, a.category) == (
        "1 Test Street", "Leeds", "LS1 1AA", "United Kingdom",
        "lca@example.org", "0113 000 0000", "https://example.org",
        "A synthetic company", FOLDER)
    assert "Created actor: Synthetic Ltd in 00: Test" in r.text
    text = ok(session, 'SHOW ACTOR "Synthetic Ltd"').text
    assert "City: Leeds" in text and "Postcode: LS1 1AA" in text


def test_the_folder_default_is_said_once(session):
    r = ok(session, 'MAKE ACTOR "A"\nEND ACTOR\nMAKE ACTOR "B"\nEND ACTOR')
    assert r.text.count("default used: FOLDER") == 1
    r = ok(session, 'MAKE ACTOR "C" FOLDER "elsewhere"\nEND ACTOR')
    assert "Created actor: C in elsewhere" in r.text


def test_make_is_idempotent(session, client):
    code = 'MAKE ACTOR "Synthetic Ltd"\n  CITY "Leeds"\nEND ACTOR'
    ok(session, code)
    r = ok(session, code.replace("Leeds", "York"))
    assert "exists already" in r.text and "EDIT ACTOR" in r.text
    assert one(client, o.Actor, "Synthetic Ltd").city == "Leeds"


def test_edit_actor_changes_only_what_is_given(session, client):
    ok(session, 'MAKE ACTOR "Synthetic Ltd"\n  CITY "Leeds"\n'
                '  EMAIL "a@example.org"\nEND ACTOR')
    ok(session, 'EDIT ACTOR "Synthetic Ltd"\n  CITY "York"\nEND EDIT')
    a = one(client, o.Actor, "Synthetic Ltd")
    assert (a.city, a.email) == ("York", "a@example.org")


def test_edit_of_something_missing(session):
    e = err(session, 'EDIT ACTOR "Nobody"\n  CITY "York"\nEND EDIT')
    assert "No actor is called 'Nobody'" in e["message"]


def test_block_errors_name_the_line(session):
    e = err(session, 'MAKE ACTOR "A"\n  COLOUR "red"\nEND ACTOR')
    assert e["line"] == 2
    assert "'COLOUR' is not a line of a ACTOR block" in e["message"]
    assert "ADDRESS" in e["hint"]
    e = err(session, 'MAKE ACTOR "A"\n  CITY "x"\n  CITY "y"\nEND ACTOR')
    assert e["line"] == 3 and "given twice" in e["message"]
    e = err(session, 'MAKE ACTOR "A"\n  CITY "x"\n')
    assert "missing END ACTOR" in e["message"]
    e = err(session, 'MAKE ACTOR "A"\n  CITY "x"\nEND SOURCE')
    assert "Expected END ACTOR, got END SOURCE" in e["message"]
    e = err(session, 'MAKE ACTOR\nEND ACTOR')
    assert "needs a name" in e["message"]
    e = err(session, 'EDIT ACTOR "A" FOLDER "x"\nEND EDIT')
    assert "MOVE ACTOR" in e["hint"]


def test_make_source(session, client):
    ok(session, '''
MAKE SOURCE "Synthetic report"
    REFERENCE "Author, A. (2024). A synthetic report."
    URL "https://example.org/report"
    YEAR 2024
END SOURCE''')
    s = one(client, o.Source, "Synthetic report")
    assert (s.text_reference, s.url, s.year) == (
        "Author, A. (2024). A synthetic report.",
        "https://example.org/report", 2024)


def test_source_year_must_be_a_year(session):
    e = err(session, 'MAKE SOURCE "S"\n  YEAR 0\nEND SOURCE')
    assert "not a year" in e["message"] and e["line"] == 2
    e = err(session, 'MAKE SOURCE "S"\n  YEAR "soon"\nEND SOURCE')
    assert "must be a number" in e["message"]


def test_attach_uploads_the_file(session, client, tmp_path):
    f = tmp_path / "report.pdf"
    f.write_bytes(b"%PDF-1.4 synthetic")
    r = ok(session, f'MAKE SOURCE "With file"\n  ATTACH "{f}"\nEND SOURCE'
                    .replace("\\", "/"))
    s = one(client, o.Source, "With file")
    data = client.source_files[s.id]
    assert data.name == "report.pdf"
    import base64
    assert base64.b64decode(data.content) == b"%PDF-1.4 synthetic"
    assert "attached file: report.pdf" in r.text
    assert s.external_file == "report.pdf"


def test_attach_of_a_missing_file_writes_nothing(session, client):
    e = err(session, 'MAKE SOURCE "S"\n  ATTACH "nowhere.pdf"\nEND SOURCE')
    assert "File not found: nowhere.pdf" in e["message"] and e["line"] == 2
    assert not client.by_name(o.Source, "S")


def test_attach_needs_openlca_2_6_2(session, client, tmp_path):
    client.server_version = "2.6.1"
    session.run("REFRESH")
    f = tmp_path / "report.pdf"
    f.write_bytes(b"x")
    s2 = Session(client=client)
    e = err(s2, f'MAKE SOURCE "S"\n  ATTACH "{f}"\nEND SOURCE'
                .replace("\\", "/"))
    # changed on purpose (12/11/2026): refused before anything is saved
    assert "needs openLCA 2.6.2 or later" in e["message"]
    assert "Nothing was saved" in e["message"] and e["line"] == 2
    assert not client.by_name(o.Source, "S")


# ── currencies ───────────────────────────────────────────────

def test_the_first_currency_is_the_reference(session, client):
    ok(session, 'MAKE CURRENCY "Test euro"\n  CODE "TEU"\nEND CURRENCY')
    eur = one(client, o.Currency, "Test euro")
    assert eur.ref_currency.id == eur.id and eur.conversion_factor == 1.0
    ok(session, 'MAKE CURRENCY "Test pound"\n  CODE "TGB"\n  FACTOR 1.2\n'
                'END CURRENCY')
    gbp = one(client, o.Currency, "Test pound")
    assert gbp.ref_currency.id == eur.id and gbp.conversion_factor == 1.2
    text = ok(session, 'SHOW CURRENCY "Test pound"').text
    assert "Reference currency: Test euro" in text
    assert "Conversion factor: 1.2" in text


def test_currency_refusals(session, client):
    e = err(session, 'MAKE CURRENCY "X"\nEND CURRENCY')
    assert "needs a code" in e["message"] and 'CODE "EUR"' in e["hint"]
    e = err(session, 'MAKE CURRENCY "X"\n  CODE "X"\n  FACTOR 2\n'
                     'END CURRENCY')
    assert "first currency" in e["message"] and e["line"] == 3
    ok(session, 'MAKE CURRENCY "Test euro"\n  CODE "TEU"\nEND CURRENCY')
    e = err(session, 'MAKE CURRENCY "X"\n  CODE "X"\nEND CURRENCY')
    assert "needs a conversion factor" in e["message"]
    e = err(session, 'MAKE CURRENCY "X"\n  CODE "X"\n  FACTOR 0\n'
                     'END CURRENCY')
    assert "above 0" in e["message"] and e["line"] == 3
    e = err(session, 'MAKE CURRENCY "X"\n  CODE "X"\n  FACTOR 2\n'
                     '  REFERENCE "Dollar"\nEND CURRENCY')
    assert "No currency is called 'Dollar'" in e["message"]
    assert e["line"] == 4
    assert not client.by_name(o.Currency, "X")


def test_the_reference_currency_cannot_be_deleted_while_used(session):
    ok(session, 'MAKE CURRENCY "Test euro"\n  CODE "TEU"\nEND CURRENCY')
    ok(session, 'MAKE CURRENCY "Test pound"\n  CODE "TGB"\n  FACTOR 1.2\n'
                'END CURRENCY')
    e = err(session, 'DELETE CURRENCY "Test euro"')
    assert "still used by Test pound (Currency)" in e["message"]
    assert "was not deleted" in e["message"]
    ok(session, 'DELETE CURRENCY "Test pound"')
    ok(session, 'DELETE CURRENCY "Test euro"')


# ── locations ────────────────────────────────────────────────

def test_make_location_with_geometry(session, client, tmp_path):
    geo = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {},
        "geometry": {"type": "Point", "coordinates": [-1.5, 53.8]}}]}
    f = tmp_path / "place.geojson"
    f.write_text(json.dumps(geo))
    ok(session, f'''
MAKE LOCATION "Testland"
    CODE "TL"
    LATITUDE 53.8
    LONGITUDE -1.5
    GEOMETRY "{f}"
END LOCATION'''.replace("\\", "/"))
    loc = one(client, o.Location, "Testland")
    assert (loc.code, loc.latitude, loc.longitude) == ("TL", 53.8, -1.5)
    assert loc.geometry == {"type": "Point", "coordinates": [-1.5, 53.8]}
    assert "Geometry: GeoJSON, type Point" in ok(
        session, 'SHOW LOCATION "Testland"').text


def test_location_refusals(session, client, tmp_path):
    e = err(session, 'MAKE LOCATION "X"\nEND LOCATION')
    assert "needs a code" in e["message"]
    e = err(session, 'MAKE LOCATION "X"\n  CODE "X"\n  LATITUDE 91\n'
                     'END LOCATION')
    assert "between -90 and 90" in e["message"] and e["line"] == 3
    e = err(session, 'MAKE LOCATION "X"\n  CODE "X"\n  LONGITUDE -181\n'
                     'END LOCATION')
    assert "between -180 and 180" in e["message"]
    bad = tmp_path / "bad.geojson"
    bad.write_text("not json")
    e = err(session, f'MAKE LOCATION "X"\n  CODE "X"\n  GEOMETRY "{bad}"\n'
                     f'END LOCATION'.replace("\\", "/"))
    assert "is not a JSON file" in e["message"] and e["line"] == 3
    two = tmp_path / "two.geojson"
    two.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point",
                                         "coordinates": [0, 0]}}] * 2}))
    e = err(session, f'MAKE LOCATION "X"\n  CODE "X"\n  GEOMETRY "{two}"\n'
                     f'END LOCATION'.replace("\\", "/"))
    assert "holds 2 features" in e["message"]
    assert not client.by_name(o.Location, "X")


def test_a_location_used_by_a_process_cannot_be_deleted(session, client):
    e = err(session, 'DELETE LOCATION "Germany"')
    assert "still used by" in e["message"] and "(Process)" in e["message"]
    assert client.by_name(o.Location, "Germany")


# ── unit groups and flow properties ──────────────────────────

UNITS = '''
MAKE UNITS "Units of test"
    UNIT "tu", 1 REFERENCE
    UNIT "ktu", 1000 SYNONYMS "kilotest; thousand tu"
    UNIT mtu, 0.001
END UNITS
MAKE PROPERTY "Test quantity"
    UNITS "Units of test"
END PROPERTY
'''


def test_make_units_and_property(session, client):
    ok(session, UNITS)
    group = one(client, o.UnitGroup, "Units of test")
    units = {u.name: u for u in group.units}
    assert {n: u.conversion_factor for n, u in units.items()} == {
        "tu": 1.0, "ktu": 1000.0, "mtu": 0.001}
    assert [u.name for u in group.units if u.is_ref_unit] == ["tu"]
    assert units["ktu"].synonyms == ["kilotest", "thousand tu"]
    prop = one(client, o.FlowProperty, "Test quantity")
    assert prop.unit_group.id == group.id
    assert prop.flow_property_type == o.FlowPropertyType.PHYSICAL_QUANTITY
    text = ok(session, 'SHOW UNITS "Units of test"').text
    assert "ktu" in text and "kilotest" in text


def test_a_new_unit_can_be_used_straight_away(session, client):
    ok(session, UNITS)
    ok(session, 'MAKE FLOW "Test thing", tu, PRODUCT')
    flow = one(client, o.Flow, "Test thing")
    prop = one(client, o.FlowProperty, "Test quantity")
    assert flow.flow_properties[0].flow_property.id == prop.id


def test_economic_property(session, client):
    ok(session, UNITS.replace('    UNITS "Units of test"\n',
                              '    UNITS "Units of test"\n'
                              '    TYPE ECONOMIC\n'))
    prop = one(client, o.FlowProperty, "Test quantity")
    assert prop.flow_property_type == o.FlowPropertyType.ECONOMIC_QUANTITY


def test_unit_group_refusals(session, client):
    e = err(session, 'MAKE UNITS "U"\nEND UNITS')
    assert "needs units" in e["message"]
    e = err(session, 'MAKE UNITS "U"\n  UNIT "xa", 1\n  UNIT "xb", 2\n'
                     'END UNITS')
    assert "exactly one reference unit; this one has 0" in e["message"]
    e = err(session, 'MAKE UNITS "U"\n  UNIT "xa", 1 REFERENCE\n'
                     '  UNIT "xb", 2 REFERENCE\nEND UNITS')
    assert "has 2" in e["message"] and e["line"] == 3
    e = err(session, 'MAKE UNITS "U"\n  UNIT "xa", 2 REFERENCE\nEND UNITS')
    assert "its factor is 1, not 2" in e["message"]
    e = err(session, 'MAKE UNITS "U"\n  UNIT "xa", 1 REFERENCE\n'
                     '  UNIT "xb", -1\nEND UNITS')
    assert "must be above 0" in e["message"] and e["line"] == 3
    e = err(session, 'MAKE UNITS "U"\n  UNIT "xa", 1 REFERENCE\n'
                     '  UNIT "xa", 2\nEND UNITS')
    assert "given twice" in e["message"]
    e = err(session, 'MAKE UNITS "U"\n  UNIT "xa"\nEND UNITS')
    assert "conversion factor" in e["message"]
    assert not client.by_name(o.UnitGroup, "U")


def test_a_unit_name_belongs_to_one_group_only(session, client):
    e = err(session, 'MAKE UNITS "U"\n  UNIT "x", 1 REFERENCE\n'
                     '  UNIT "kg", 5\nEND UNITS')
    assert "The unit 'kg' exists already, in the unit group 'Units of mass'" \
        in e["message"]
    assert e["line"] == 3
    assert not client.by_name(o.UnitGroup, "U")


def test_property_refusals(session, client):
    e = err(session, 'MAKE PROPERTY "P"\nEND PROPERTY')
    assert "needs a unit group" in e["message"]
    e = err(session, 'MAKE PROPERTY "P"\n  UNITS "Units of nothing"\n'
                     'END PROPERTY')
    assert "No unit group is called 'Units of nothing'" in e["message"]
    assert "MAKE UNITS" in e["hint"] and e["line"] == 2
    e = err(session, 'MAKE PROPERTY "P"\n  UNITS "Units of mass"\n'
                     '  TYPE SOCIAL\nEND PROPERTY')
    assert "TYPE PHYSICAL or TYPE ECONOMIC" in e["hint"]
    assert not client.by_name(o.FlowProperty, "P")


def test_units_and_properties_in_use_cannot_be_deleted(session, client):
    e = err(session, 'DELETE UNITS "Units of mass"')
    assert "still used by Mass (FlowProperty)" in e["message"]
    e = err(session, 'DELETE PROPERTY "Mass"')
    assert "still used by" in e["message"] and "(Flow)" in e["message"]
    ok(session, UNITS)
    ok(session, 'DELETE PROPERTY "Test quantity"')
    ok(session, 'DELETE UNITS "Units of test"')
    assert not client.by_name(o.UnitGroup, "Units of test")


def test_edit_units_keeps_the_ids_of_units_that_stay(session, client):
    ok(session, UNITS)
    before = {u.name: u.id for u in
              one(client, o.UnitGroup, "Units of test").units}
    ok(session, 'EDIT UNITS "Units of test"\n  UNIT "tu", 1 REFERENCE\n'
                '  UNIT "ktu", 1000\n  UNIT "Mtu", 1000000\nEND EDIT')
    after = {u.name: u.id for u in
             one(client, o.UnitGroup, "Units of test").units}
    assert set(after) == {"tu", "ktu", "Mtu"}
    assert after["tu"] == before["tu"] and after["ktu"] == before["ktu"]


# ── social indicators and data quality systems ───────────────

def test_make_social_indicator(session, client):
    ok(session, '''
MAKE SOCIAL INDICATOR "Test hours"
    ACTIVITY VARIABLE "Working hours"
    ACTIVITY QUANTITY "Time"
    ACTIVITY UNIT "h"
    MEASURED IN "h per week"
    EVALUATION "Lower is better"
END SOCIAL INDICATOR''')
    si = one(client, o.SocialIndicator, "Test hours")
    assert (si.activity_variable, si.activity_quantity.name,
            si.activity_unit.name, si.unit_of_measurement,
            si.evaluation_scheme) == (
        "Working hours", "Time", "h", "h per week", "Lower is better")


def test_social_indicator_refusals(session, client):
    e = err(session, 'MAKE SOCIAL INDICATOR "S"\n  ACTIVITY UNIT "zz"\n'
                     'END SOCIAL INDICATOR')
    assert "Unit 'zz' is not in this database" in e["message"]
    assert e["line"] == 2
    e = err(session, 'MAKE SOCIAL INDICATOR "S"\n  ACTIVITY QUANTITY "zz"\n'
                     'END SOCIAL INDICATOR')
    assert "No flow property is called 'zz'" in e["message"]
    assert not client.by_name(o.SocialIndicator, "S")


DQ = '''
MAKE DQ SYSTEM "Test quality"
    UNCERTAINTIES YES
    INDICATOR "Reliability"
    SCORE 1 "Verified" UNCERTAINTY 1.0
    SCORE 2 "Estimated" DESCRIPTION "A qualified estimate" UNCERTAINTY 1.2
    INDICATOR "Completeness"
    SCORE 1 "All sites"
    SCORE 2 "Some sites"
END DQ SYSTEM
'''


def test_make_dq_system(session, client):
    ok(session, DQ)
    dq = one(client, o.DQSystem, "Test quality")
    assert dq.has_uncertainties is True
    assert [(i.name, i.position) for i in dq.indicators] == [
        ("Reliability", 1), ("Completeness", 2)]
    scores = dq.indicators[0].scores
    assert [(s.position, s.label, s.uncertainty) for s in scores] == [
        (1, "Verified", 1.0), (2, "Estimated", 1.2)]
    assert scores[1].description == "A qualified estimate"
    assert "Reliability" in ok(session, 'SHOW DQ SYSTEM "Test quality"').text


def test_dq_system_refusals(session, client):
    e = err(session, 'MAKE DQ SYSTEM "Q"\nEND DQ SYSTEM')
    assert "needs indicators" in e["message"]
    e = err(session, 'MAKE DQ SYSTEM "Q"\n  SCORE 1 "x"\nEND DQ SYSTEM')
    assert "SCORE comes after an INDICATOR" in e["message"]
    e = err(session, 'MAKE DQ SYSTEM "Q"\n  INDICATOR "a"\nEND DQ SYSTEM')
    assert "has no scores" in e["message"] and e["line"] == 2
    e = err(session, 'MAKE DQ SYSTEM "Q"\n  INDICATOR "a"\n  SCORE 1 "x"\n'
                     '  INDICATOR "b"\n  SCORE 1 "x"\n  SCORE 2 "y"\n'
                     'END DQ SYSTEM')
    assert "same number of scores" in e["message"]
    e = err(session, 'MAKE DQ SYSTEM "Q"\n  INDICATOR "a"\n  SCORE 1 "x"\n'
                     '  SCORE 3 "y"\nEND DQ SYSTEM')
    assert "numbered 1 to 2" in e["message"]
    assert not client.by_name(o.DQSystem, "Q")


# ── MOVE and DELETE ──────────────────────────────────────────

def test_move_any_type(session, client):
    ok(session, 'MAKE ACTOR "Synthetic Ltd"\nEND ACTOR')
    r = ok(session, 'MOVE ACTOR "Synthetic Ltd" TO "00: Test/people"')
    assert one(client, o.Actor, "Synthetic Ltd").category == "00: Test/people"
    assert "Moved actor 'Synthetic Ltd' to '00: Test/people'" in r.text
    e = err(session, 'MOVE ACTOR "Nobody" TO "x"')
    assert "No actor is called 'Nobody'" in e["message"]
    e = err(session, 'MOVE ACTOR "Synthetic Ltd"')
    assert "MOVE needs TO" in e["message"]


def test_delete_asks_first_unless_confirm_delete_is_on(client):
    s = Session(client=client)
    ok(s, 'MAKE ACTOR "A" FOLDER "x"\nEND ACTOR')
    e = err(s, 'DELETE ACTOR "A"')
    assert "CONFIRM DELETE ON" in e["hint"]
    assert client.by_name(o.Actor, "A")
    ok(s, 'CONFIRM DELETE ON\nDELETE ACTOR "A"')
    assert not client.by_name(o.Actor, "A")


def test_delete_of_something_missing_is_quiet(session):
    assert "Not found: Nobody" in ok(session, 'DELETE ACTOR "Nobody"').text


def test_an_actor_in_use_cannot_be_deleted(session, client):
    ok(session, WIDGET)
    ok(session, 'MAKE ACTOR "Author"\nEND ACTOR')
    ok(session, 'EDIT PROCESS "Widget"\n  DOCUMENT\n    GENERATOR "Author"\n'
                '  END DOCUMENT\nEND EDIT')
    e = err(session, 'DELETE ACTOR "Author"')
    assert "still used by Widget (Process)" in e["message"]
    assert client.by_name(o.Actor, "Author")
    r = ok(session, 'SHOW ACTOR "Author" USAGE')
    assert "Widget (Process)" in r.text
    assert "reads every process" in r.text


def test_usage_is_asked_of_openlca_from_2_7(client):
    client.server_version = "2.7.0"
    s = Session(client=client)
    ok(s, SETUP + 'MAKE ACTOR "Author"\nEND ACTOR')
    client.calls.clear()
    r = ok(s, 'SHOW ACTOR "Author" USAGE')
    assert "Nothing uses the actor 'Author' (asked openLCA)" in r.text
    assert ("rpc_call", "data/get/usage") in client.calls
    assert not [c for c in client.calls if c[:2] == ("get", "Process")]
    ok(s, WIDGET)
    r = ok(s, 'SHOW PROCESS "Widget" USAGE')
    assert "Widget (ProductSystem)" in r.text


def test_process_usage_needs_2_7(session):
    ok(session, WIDGET)
    e = err(session, 'SHOW PROCESS "Widget" USAGE')
    assert "2.7" in e["hint"]


def test_delete_global_parameter_in_use_is_refused(session, client):
    ok(session, WIDGET)
    e = err(session, 'DELETE PARAMETER "elec"')
    assert "still used by Widget (Process)" in e["message"]
    ok(session, "LET spare = 3")
    ok(session, 'DELETE PARAMETER "spare"')
    assert not client.by_name(o.Parameter, "spare")


# ── EXPORT ───────────────────────────────────────────────────

def test_export_asks_openlca_for_json_ld(session, client):
    ok(session, WIDGET)
    r = ok(session, 'EXPORT PROCESS "Widget" TO "out/widget.zip"')
    assert len(client.exports) == 1
    sent = client.exports[0]
    assert sent["path"].replace("\\", "/").endswith("out/widget.zip")
    assert sent["models"] == [{"@type": "Process",
                               "@id": one(client, o.Process, "Widget").id}]
    assert "Exported 'Widget'" in r.text


def test_export_refusals(session):
    e = err(session, 'EXPORT ACTOR "Nobody" TO "x.zip"')
    assert "No actor is called 'Nobody'" in e["message"]
    ok(session, 'MAKE ACTOR "A"\nEND ACTOR')
    e = err(session, 'EXPORT ACTOR "A" TO "x.json"')
    assert "not a .zip file name" in e["message"]
    e = err(session, 'EXPORT ACTOR "A"')
    assert "EXPORT needs TO" in e["message"]


def test_export_results_still_works(session):
    ok(session, WIDGET)
    ok(session, f'CALCULATE "Widget" USING "{EF}"')
    assert parse('EXPORT RESULTS TO "x.csv"')[0].__class__.__name__ == (
        "ExportResultsStmt")
    assert parse('EXPORT "x.csv"')[0].__class__.__name__ == (
        "ExportResultsStmt")


# ── impact methods ───────────────────────────────────────────

def test_make_method(session, client):
    r = ok(session, METHOD)
    m = one(client, o.ImpactMethod, "Test method")
    assert m.tags == [OWN_TAG] and m.category == FOLDER
    assert m.description == "A synthetic method"
    assert [c.name for c in m.impact_categories] == ["Test climate",
                                                     "Test water"]
    climate = one(client, o.ImpactCategory, "Test climate")
    assert climate.ref_unit == "kg CO2 eq" and climate.code == "GWP"
    assert climate.tags == [OWN_TAG]
    assert sorted((f.flow.name, f.value) for f in climate.impact_factors) == [
        ("Carbon dioxide, fossil", 1.0), ("Methane, fossil", 29.8)]
    assert [(p.name, p.value) for p in climate.parameters] == [
        ("gwp_ch4", 29.8)]
    water = one(client, o.ImpactCategory, "Test water")
    assert water.direction == o.Direction.INPUT
    assert water.impact_factors[0].unit.name == "m3"
    nw = m.nw_sets[0]
    assert (nw.name, nw.weighted_score_unit) == ("Test world", "pt")
    assert sorted((f.impact_category.name, f.normalisation_factor,
                   f.weighting_factor) for f in nw.factors) == [
        ("Test climate", 8000.0, 0.25), ("Test water", 100.0, 0.75)]
    assert "2 categories, 3 factors, 1 NW sets" in r.text
    text = ok(session, 'SHOW METHOD "Test method"').text
    assert "Made by olcaBASIC: YES" in text and "Test world" in text
    text = ok(session, 'SHOW CATEGORY "Test climate"').text
    assert "Methane, fossil" in text and "29.8" in text


def test_a_made_method_calculates(session, client):
    ok(session, WIDGET)
    ok(session, METHOD)
    r = ok(session, 'CALCULATE "Widget" USING "Test method" '
                    'NW SET "Test world"')
    impacts = {i["category"]: i["amount"]
               for i in r.data[-1]["result"]["impacts"]}
    assert impacts["Test climate"] == pytest.approx(0.5)
    r = ok(session, "RESULT NORMALISED")
    rows = {row["category"]: row["amount"]
            for row in r.data[-1]["result"]["rows"]}
    assert rows["Test climate"] == pytest.approx(0.5 / 8000)
    r = ok(session, "RESULT WEIGHTED")
    rows = {row["category"]: row["amount"]
            for row in r.data[-1]["result"]["rows"]}
    assert rows["Test climate"] == pytest.approx(0.5 / 8000 * 0.25)


def test_make_method_is_idempotent(session, client):
    ok(session, METHOD)
    r = ok(session, METHOD.replace("29.8", "30"))
    assert "exists already" in r.text
    climate = one(client, o.ImpactCategory, "Test climate")
    assert max(f.value for f in climate.impact_factors) == 29.8


def test_formula_factor(session, client):
    ok(session, '''
MAKE METHOD "Formula method"
    CATEGORY "C" UNIT "kg"
        PARAM k = 3
        PARAM twice = FORMULA "k * 2"
        FACTOR "Zinc" FORMULA "twice"
        FACTOR "Phosphate", 2 LOCATION "DE" UNCERTAINTY NORMAL 2, 0.1
    END CATEGORY
END METHOD''')
    cat = one(client, o.ImpactCategory, "C")
    by = {f.flow.name: f for f in cat.impact_factors}
    assert by["Zinc"].formula == "twice"
    assert by["Phosphate"].location.name == "Germany"
    assert by["Phosphate"].uncertainty.distribution_type == (
        o.UncertaintyType.NORMAL_DISTRIBUTION)
    params = {p.name: p for p in cat.parameters}
    assert params["twice"].formula == "k * 2"
    assert params["twice"].is_input_parameter is False
    assert params["k"].parameter_scope == o.ParameterScope.IMPACT_SCOPE


@pytest.mark.parametrize("body,message,line", [
    ('', "needs at least one category", 2),
    ('  CATEGORY "C"\n  END CATEGORY', "needs a reference unit", 3),
    ('  CATEGORY "C" UNIT "kg"\n    FACTOR "No such flow", 1\n'
     '  END CATEGORY', "No elementary flow is called 'No such flow'", 4),
    ('  CATEGORY "C" UNIT "kg"\n    FACTOR "Carbon dioxide, fossil", 1\n'
     '  END CATEGORY', "matches 2 elementary flows", 4),
    ('  CATEGORY "C" UNIT "kg"\n    FACTOR "test steel, low-alloyed", 1\n'
     '  END CATEGORY', "No elementary flow is called", 4),
    ('  CATEGORY "C" UNIT "kg"\n    FACTOR "Zinc", 1\n    FACTOR "Zinc", 2\n'
     '  END CATEGORY', "has two factors", 5),
    ('  CATEGORY "C" UNIT "kg"\n  END CATEGORY\n  CATEGORY "C" UNIT "kg"\n'
     '  END CATEGORY', "given twice", 5),
    ('  CATEGORY "C" UNIT "kg"\n    FACTOR "Zinc", 1 PER kWh\n'
     '  END CATEGORY', "kWh", 4),
    ('  CATEGORY "C" UNIT "kg"\n  END CATEGORY\n  NW SET "N"\n'
     '    "D", 1\n  END NW SET', "has no category called 'D'", 6),
    ('  CATEGORY "C" UNIT "kg"\n  END CATEGORY\n  NW SET "N"\n'
     '    "C", 0\n  END NW SET', "normalisation factor of 'C' is 0", 6),
    ('  CATEGORY "C" UNIT "kg"\n  END CATEGORY\n  NW SET "N"\n'
     '  END NW SET', "has no factors", 5),
])
def test_method_refusals_write_nothing(session, client, body, message, line):
    e = err(session, f'\nMAKE METHOD "Bad"\n{body}\nEND METHOD')
    assert message in e["message"], e
    if body:
        assert e["line"] == line
    assert not client.by_name(o.ImpactMethod, "Bad")
    assert not client.by_name(o.ImpactCategory, "C")


@pytest.mark.parametrize("body,message", [
    ('  COLOUR "red"', "'COLOUR' is not a line of a METHOD block"),
    ('  CATEGORY "C" UNIT "kg"\n    COLOUR "red"\n  END CATEGORY',
     "'COLOUR' is not a line of a CATEGORY block"),
    ('  CATEGORY "C" UNIT "kg"\n    FACTOR "Zinc"\n  END CATEGORY',
     "FACTOR needs a value"),
    ('  CATEGORY "C" UNIT "kg"\n    FACTOR "Zinc", 1\n',
     "Expected END CATEGORY, got END METHOD"),
    ('  CATEGORY "C" UNIT "kg"\n    FACTOR "Zinc", 1\nEND METHOD',
     "Expected END CATEGORY, got END METHOD"),
    ('  REMOVE CATEGORY "C"', "REMOVE belongs in EDIT METHOD"),
    ('  NW SET "N"\n    COLOUR\n  END NW SET',
     "is not a line of an NW SET block"),
    ('  NW SET "N"\n    "C"\n  END NW SET', "Expected a comma"),
    ('  NW SET "N"\n    "C", NONE\n  END NW SET', "gives neither"),
])
def test_method_parse_errors(body, message):
    with pytest.raises(ParseError, match=message):
        parse(f'MAKE METHOD "Bad"\n{body}\nEND METHOD')


def test_a_method_block_must_be_closed():
    with pytest.raises(ParseError, match="missing END METHOD"):
        parse('MAKE METHOD "Bad"\n  CATEGORY "C" UNIT "kg"\n'
              '  END CATEGORY\n')
    with pytest.raises(ParseError, match="missing END EDIT"):
        parse('EDIT METHOD "Bad"\n  DESCRIPTION "x"\n')


def test_edit_own_method(session, client):
    ok(session, METHOD)
    r = ok(session, '''
EDIT METHOD "Test method"
    DESCRIPTION "Changed"
    CATEGORY "Test climate"
        FACTOR "Carbon dioxide, fossil" IN "unspecified", 2
        FACTOR "Zinc", 5
        REMOVE FACTOR "Methane, fossil"
    END CATEGORY
    CATEGORY "Test acid" UNIT "mol H+ eq"
        FACTOR "Zinc", 3
    END CATEGORY
    REMOVE CATEGORY "Test water"
    NW SET "Test world" UNIT "pt"
        "Test climate", 4000, 0.5
    END NW SET
    NW SET "Test other"
        "Test acid", 10
    END NW SET
END EDIT''')
    m = one(client, o.ImpactMethod, "Test method")
    assert m.description == "Changed"
    assert [c.name for c in m.impact_categories] == ["Test climate",
                                                     "Test acid"]
    climate = one(client, o.ImpactCategory, "Test climate")
    assert sorted((f.flow.name, f.value) for f in climate.impact_factors) == [
        ("Carbon dioxide, fossil", 2.0), ("Zinc", 5.0)]
    assert not client.by_name(o.ImpactCategory, "Test water")
    assert one(client, o.ImpactCategory, "Test acid").tags == [OWN_TAG]
    sets = {s.name: s for s in m.nw_sets}
    assert set(sets) == {"Test world", "Test other"}
    assert [(f.impact_category.name, f.normalisation_factor)
            for f in sets["Test world"].factors] == [("Test climate", 4000.0)]
    assert "1 factor(s) added, 1 replaced, 1 removed" in r.text
    assert "category 'Test water' removed" in r.text
    ok(session, 'EDIT METHOD "Test method"\n  REMOVE NW SET "Test other"\n'
                'END EDIT')
    assert [s.name for s in one(client, o.ImpactMethod,
                                "Test method").nw_sets] == ["Test world"]


def test_removing_a_category_takes_it_out_of_the_nw_sets(session, client):
    ok(session, METHOD)
    ok(session, 'EDIT METHOD "Test method"\n  REMOVE CATEGORY "Test water"\n'
                'END EDIT')
    nw = one(client, o.ImpactMethod, "Test method").nw_sets[0]
    assert [f.impact_category.name for f in nw.factors] == ["Test climate"]


def test_edit_method_refusals_write_nothing(session, client):
    ok(session, METHOD)
    before = one(client, o.ImpactCategory, "Test climate").to_dict()
    e = err(session, 'EDIT METHOD "Test method"\n  CATEGORY "Test climate"\n'
                     '    FACTOR "Zinc", 5\n    REMOVE FACTOR "Phosphate"\n'
                     '  END CATEGORY\nEND EDIT')
    assert "'Test climate' has no factor for 'Phosphate'" in e["message"]
    assert e["line"] == 4
    assert one(client, o.ImpactCategory, "Test climate").to_dict() == before
    e = err(session, 'EDIT METHOD "Test method"\n  REMOVE CATEGORY "Nope"\n'
                     'END EDIT')
    assert "no category called 'Nope'" in e["message"]
    e = err(session, 'EDIT METHOD "Test method"\n  REMOVE NW SET "Nope"\n'
                     'END EDIT')
    assert "no NW set 'Nope'" in e["message"]
    e = err(session, 'EDIT METHOD "Nope"\n  DESCRIPTION "x"\nEND EDIT')
    assert "No impact method is called 'Nope'" in e["message"]


FOREIGN_EDIT = f'''
EDIT METHOD "{EF}"__CONFIRM__
    CATEGORY "Climate change"
        FACTOR "Zinc", 3
        FACTOR "Phosphate", 1
    END CATEGORY
END EDIT'''


def _foreign_untouched(client):
    cat = one(client, o.ImpactCategory, "Climate change") if len(
        client.by_name(o.ImpactCategory, "Climate change")) == 1 else None
    cats = [c for c in client.store["ImpactCategory"].values()
            if c.name == "Climate change"]
    return all(len(c.impact_factors) == 3 for c in cats)


def test_a_foreign_method_is_refused_without_confirm(session, client):
    e = err(session, FOREIGN_EDIT.replace("__CONFIRM__", ""))
    assert "was not made by olcaBASIC" in e["message"]
    assert "would change 2 characterisation factors" in e["message"]
    assert "Back the database up first" in e["hint"]
    assert f'EDIT METHOD "{EF}" CONFIRM' in e["hint"]
    assert _foreign_untouched(client)


def test_a_foreign_method_cannot_be_edited_through_a_session(session, client):
    e = err(session, FOREIGN_EDIT.replace("__CONFIRM__", " CONFIRM"))
    assert "olcaBASIC terminal" in e["hint"]
    assert "MAKE METHOD" in e["hint"]
    assert _foreign_untouched(client)


def test_a_person_can_confirm_a_foreign_edit(interp, client, monkeypatch,
                                             capsys):
    asked = _answers(monkeypatch, "YES")
    interp.run_program(FOREIGN_EDIT.replace("__CONFIRM__", " CONFIRM"))
    out = capsys.readouterr().out
    assert len(asked) == 1 and "Type YES" in asked[0]
    assert "2 characterisation factors" in out
    assert "Back the database up first" in out
    assert not _foreign_untouched(client)
    m = one(client, o.ImpactMethod, EF)
    assert not m.tags


@pytest.mark.parametrize("reply", ["no", "", "yes please"])
def test_any_other_answer_cancels_a_foreign_edit(interp, client, monkeypatch,
                                                 reply):
    _answers(monkeypatch, reply)
    with pytest.raises(BasicError, match="cancelled. Nothing was changed"):
        interp.run_program(FOREIGN_EDIT.replace("__CONFIRM__", " CONFIRM"))
    assert _foreign_untouched(client)


def test_deleting_a_foreign_method_follows_the_same_rule(session, client):
    e = err(session, f'DELETE METHOD "{EF}"')
    assert "was not made by olcaBASIC" in e["message"]
    assert "would delete" in e["message"]
    assert f'DELETE METHOD "{EF}" CONFIRM' in e["hint"]
    e = err(session, f'DELETE METHOD "{EF}" CONFIRM')
    assert "olcaBASIC terminal" in e["hint"]
    assert client.by_name(o.ImpactMethod, EF)


def test_deleting_an_own_method_takes_its_categories(session, client):
    ok(session, METHOD)
    r = ok(session, 'DELETE METHOD "Test method"')
    assert "and 2 of its categories" in r.text
    assert not client.by_name(o.ImpactMethod, "Test method")
    assert not client.by_name(o.ImpactCategory, "Test climate")


def test_a_method_used_by_a_project_cannot_be_deleted(session, client):
    ok(session, WIDGET)
    ok(session, METHOD)
    ok(session, PROJECT)
    e = err(session, 'DELETE METHOD "Test method"')
    assert "still used by Test project (Project)" in e["message"]


# ── projects ─────────────────────────────────────────────────

PROJECT = '''
MAKE PROJECT "Test project"
    METHOD "Test method"
    NW SET "Test world"
    DESCRIPTION "Two variants of the widget"
    VARIANT "base" SYSTEM "Widget"
    END VARIANT
    VARIANT "double" SYSTEM "Widget" AMOUNT 2 kg ALLOCATE PHYSICAL
        elec = 5
        DESCRIPTION "Twice as much"
    END VARIANT
    VARIANT "off" SYSTEM "Widget" DISABLED
    END VARIANT
END PROJECT
'''


def test_make_project(session, client):
    ok(session, WIDGET)
    ok(session, METHOD)
    ok(session, PROJECT)
    p = one(client, o.Project, "Test project")
    assert p.impact_method.name == "Test method"
    assert p.nw_set.name == "Test world"
    assert p.description == "Two variants of the widget"
    assert [v.name for v in p.variants] == ["base", "double", "off"]
    double = p.variants[1]
    assert (double.amount, double.unit.name, double.description) == (
        2.0, "kg", "Twice as much")
    assert double.allocation_method == o.AllocationType.PHYSICAL_ALLOCATION
    assert [(r.name, r.value) for r in double.parameter_redefs] == [
        ("elec", 5.0)]
    assert p.variants[2].is_disabled is True
    text = ok(session, 'SHOW PROJECT "Test project"').text
    assert "double" in text and "elec = 5" in text


def test_calculate_project(session, client):
    ok(session, WIDGET)
    ok(session, METHOD)
    ok(session, PROJECT)
    r = ok(session, 'CALCULATE PROJECT "Test project"')
    result = r.data[-1]["result"]
    assert r.data[-1]["call"] == "calculate_project"
    assert list(result["results"]) == ["base", "double"]
    assert result["disabled"] == ["off"]

    def climate(name):
        return next(i["amount"] for i in result["results"][name]
                    if i["category"] == "Test climate")
    assert climate("base") == pytest.approx(0.5)
    assert climate("double") == pytest.approx(1.0)
    assert result["normalised"]["double"]["Test climate"] == pytest.approx(
        1.0 / 8000)
    assert result["weighted"]["base"]["Test climate"] == pytest.approx(
        0.5 / 8000 * 0.25)
    assert result["variants"]["double"]["parameters"] == {"elec": 5.0}
    assert "Disabled variants (not calculated): off" in r.text
    assert client.undisposed() == 0
    # each variant's setup carried its own amount and parameter values
    setups = client.setups[-2:]
    assert setups[1].amount == 2.0
    assert [(p.name, p.value) for p in setups[1].parameters] == [
        ("elec", 5.0)]
    # SAVE RESULTS writes the comparison
    assert session.interpreter.runtime.last_results_type == "scenarios"


def test_project_variant_parameters_change_the_result(session, client):
    ok(session, WIDGET)
    ok(session, f'''
MAKE PROJECT "Elec project"
    METHOD "{EF}"
    VARIANT "base" SYSTEM "Widget"
    END VARIANT
    VARIANT "more" SYSTEM "Widget"
        elec = 6.5
    END VARIANT
END PROJECT''')
    r = ok(session, 'CALCULATE PROJECT "Elec project"')
    res = r.data[-1]["result"]["results"]

    def fossil(name):
        return next(i["amount"] for i in res[name]
                    if i["category"] == "Climate change: fossil")
    assert fossil("more") - fossil("base") == pytest.approx(4.0 * 0.25)


@pytest.mark.parametrize("body,message", [
    ('  METHOD "Test method"', "needs at least one variant"),
    ('  METHOD "No method"\n  VARIANT "a" SYSTEM "Widget"\n  END VARIANT',
     "No method"),
    ('  METHOD "Test method"\n  VARIANT "a" SYSTEM "Nope"\n  END VARIANT',
     "No product system is called 'Nope'"),
    ('  METHOD "Test method"\n  VARIANT "a" SYSTEM "Widget"\n    zz = 1\n'
     '  END VARIANT', "has no parameter 'zz'"),
    ('  METHOD "Test method"\n  VARIANT "a" SYSTEM "Widget" AMOUNT 0 kg\n'
     '  END VARIANT', "must be above 0"),
    ('  METHOD "Test method"\n  VARIANT "a" SYSTEM "Widget" AMOUNT 1 zz\n'
     '  END VARIANT', "Unit 'zz' is not in this database"),
    ('  METHOD "Test method"\n  NW SET "Nope"\n  VARIANT "a" SYSTEM '
     '"Widget"\n  END VARIANT', "Nope"),
    ('  METHOD "Test method"\n  VARIANT "a" SYSTEM "Widget"\n  END VARIANT\n'
     '  VARIANT "a" SYSTEM "Widget"\n  END VARIANT', "given twice"),
])
def test_project_refusals_write_nothing(session, client, body, message):
    ok(session, WIDGET)
    ok(session, METHOD)
    e = err(session, f'MAKE PROJECT "Bad"\n{body}\nEND PROJECT')
    assert message in e["message"] + e["hint"], e
    assert not client.by_name(o.Project, "Bad")


@pytest.mark.parametrize("body,message", [
    ('  VARIANT "a" SYSTEM "Widget"\n  END VARIANT',
     "The project needs a method"),
    ('  METHOD "m"\n  VARIANT "a"\n  END VARIANT',
     "A variant needs a product system"),
    ('  METHOD "m"\n  VARIANT "a" SYSTEM "s"\n  VARIANT "b" SYSTEM "s"\n'
     '  END VARIANT', "missing END VARIANT"),
    ('  METHOD "m"\n  WITH LUCK', "WITH 'LUCK'"),
    ('  METHOD "m"\n  VARIANT "a" SYSTEM "s" AMOUNT 2\n  END VARIANT',
     "AMOUNT needs a unit"),
])
def test_project_parse_errors(body, message):
    with pytest.raises(ParseError, match=message):
        parse(f'MAKE PROJECT "Bad"\n{body}\nEND PROJECT')


def test_calculate_project_refusals(session, client):
    e = err(session, 'CALCULATE PROJECT "Nope"')
    assert "No project is called 'Nope'" in e["message"]
    ok(session, WIDGET)
    ok(session, METHOD)
    ok(session, 'MAKE PROJECT "All off"\n  METHOD "Test method"\n'
                '  VARIANT "a" SYSTEM "Widget" DISABLED\n  END VARIANT\n'
                'END PROJECT')
    e = err(session, 'CALCULATE PROJECT "All off"')
    assert "Every variant of 'All off' is disabled" in e["message"]
    assert client.undisposed() == 0


def test_a_failed_project_calculation_leaves_nothing_open(session, client):
    ok(session, WIDGET)
    ok(session, METHOD)
    ok(session, PROJECT)
    client.fail_next["calculate"] = RuntimeError("synthetic failure")
    e = err(session, 'CALCULATE PROJECT "Test project"')
    assert "synthetic failure" in e["message"]
    assert client.undisposed() == 0


# ── stored results ───────────────────────────────────────────

def test_save_result_as(session, client):
    ok(session, WIDGET)
    ok(session, f'CALCULATE "Widget" USING "{EF}"')
    r = ok(session, 'SAVE RESULT AS "Widget stored" FOLDER "00: Test/results"'
                    ' DESCRIPTION "A1-A3"')
    stored = one(client, o.Result, "Widget stored")
    assert stored.product_system.name == "Widget"
    assert stored.impact_method.name == EF
    assert stored.category == "00: Test/results"
    assert stored.description == "A1-A3"
    amounts = {i.indicator.name: i.amount for i in stored.impact_results}
    assert amounts["Climate change: fossil"] == pytest.approx(
        2.5 * 0.25 + 0.8 * 2.0 + 0.5)
    ref = [f for f in stored.flow_results if f.is_ref_flow]
    assert len(ref) == 1 and ref[0].flow.name == "Widget"
    assert ref[0].is_input is False
    co2 = [f for f in stored.flow_results
           if f.flow.name == "Carbon dioxide, fossil"]
    assert co2 and co2[0].amount == pytest.approx(0.5)
    assert "Saved stored result: Widget stored" in r.text
    # the result is still open
    ok(session, "RESULT IMPACTS")
    text = ok(session, 'SHOW RESULT "Widget stored"').text
    assert "Climate change: fossil" in text and "Product system: Widget" in text
    assert "Widget stored" in ok(session, "FIND RESULT").text


def test_save_result_as_does_not_write_over_a_result(session, client):
    ok(session, WIDGET)
    ok(session, f'CALCULATE "Widget" USING "{EF}"')
    ok(session, 'SAVE RESULT AS "Widget stored"')
    first = one(client, o.Result, "Widget stored").id
    e = err(session, 'SAVE RESULT AS "Widget stored"')
    assert "exists already" in e["message"] and "REPLACE" in e["hint"]
    r = ok(session, 'SAVE RESULT AS "Widget stored" REPLACE')
    assert "Replaced stored result" in r.text
    assert one(client, o.Result, "Widget stored").id == first


def test_save_result_as_from_a_named_result(session, client):
    ok(session, WIDGET)
    ok(session, f'CALCULATE "Widget" USING "{EF}" AS base')
    ok(session, f'CALCULATE "Widget" USING "IPCC 2021"')
    ok(session, 'SAVE RESULT AS "From base" IN base')
    assert one(client, o.Result, "From base").impact_method.name == EF


def test_save_result_as_needs_an_open_result(session):
    e = err(session, 'SAVE RESULT AS "x"')
    assert e["message"] == "No result is open."
    e = err(session, 'SAVE RESULT AS "x" IN nope')
    assert "No open result is called 'nope'" in e["message"]
    r = session.run('SAVE RESULT AS "x"', dry_run=True)
    assert not r.ok and "No result is open" in r.errors[0]["message"]


def test_the_old_save_commands_are_unchanged():
    assert type(parse('SAVE RESULTS "x.csv"')[0]).__name__ == (
        "SaveResultsStmt")
    assert type(parse('SAVE "x.csv"')[0]).__name__ == "SaveResultsStmt"
    assert type(parse('SAVE "x.baslca"')[0]).__name__ == "SaveProgramStmt"
    assert type(parse('SAVE PROGRAM "x"')[0]).__name__ == "SaveProgramStmt"


def test_delete_and_move_a_stored_result(session, client):
    ok(session, WIDGET)
    ok(session, f'CALCULATE "Widget" USING "{EF}"')
    ok(session, 'SAVE RESULT AS "Widget stored"')
    ok(session, 'MOVE RESULT "Widget stored" TO "00: Test/kept"')
    assert one(client, o.Result, "Widget stored").category == "00: Test/kept"
    ok(session, 'DELETE RESULT "Widget stored"')
    assert not client.by_name(o.Result, "Widget stored")


# ── SHUTDOWN SERVER ──────────────────────────────────────────

def test_shutdown_is_refused_without_confirm(session, client):
    e = err(session, "SHUTDOWN SERVER")
    assert "SHUTDOWN SERVER CONFIRM" in e["hint"]
    assert not client.shut_down


def test_shutdown_cannot_run_through_a_session(session, client):
    e = err(session, "SHUTDOWN SERVER CONFIRM")
    assert "olcaBASIC terminal" in e["hint"]
    assert not client.shut_down
    r = session.run("SHUTDOWN SERVER CONFIRM", dry_run=True)
    assert not r.ok


def test_a_person_can_shut_the_server_down(interp, client, monkeypatch,
                                           capsys):
    interp.run_program(SETUP + WIDGET
                       + f'\nCALCULATE "Widget" USING "{EF}" AS keep')
    _answers(monkeypatch, "YES")
    interp.run_line("SHUTDOWN SERVER CONFIRM")
    assert client.shut_down
    assert client.undisposed() == 0
    assert "has stopped" in capsys.readouterr().out


def test_shutdown_cancelled(interp, client, monkeypatch):
    _answers(monkeypatch, "no")
    with pytest.raises(BasicError, match="cancelled"):
        interp.run_program("SHUTDOWN SERVER CONFIRM")
    assert not client.shut_down


# ── the terminal: blocks typed line by line ──────────────────

def _type(interp, monkeypatch, text):
    from olcabasic.repl import REPL
    lines = iter(text.strip().splitlines())

    def fake_input(prompt=""):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError
    monkeypatch.setattr("builtins.input", fake_input)
    REPL(interp).run()


def test_the_terminal_waits_for_the_end_of_the_new_blocks(interp, client,
                                                          monkeypatch):
    _type(interp, monkeypatch, SETUP + WIDGET + METHOD + PROJECT + """
EDIT METHOD "Test method"
    NW SET "Test second"
        "Test climate", 2
    END NW SET
END EDIT
MAKE UNITS "Units of test"
    UNIT "tu", 1 REFERENCE
END UNITS
MAKE FLOW PROPERTY "Test quantity"
    UNITS "Units of test"
END PROPERTY
""")
    assert one(client, o.Project, "Test project").nw_set.name == "Test world"
    assert [s.name for s in one(client, o.ImpactMethod,
                                "Test method").nw_sets] == ["Test world",
                                                            "Test second"]
    assert one(client, o.FlowProperty, "Test quantity")


# ── what the live server taught (0.4.0) ──────────────────────

def test_an_activity_unit_alone_brings_its_quantity(session, client):
    """openLCA keeps the unit of a social indicator only with its flow
    property, so the unit's own property is written with it."""
    ok(session, '''
MAKE SOCIAL INDICATOR "Unit only"
    ACTIVITY UNIT "h"
END SOCIAL INDICATOR''')
    si = one(client, o.SocialIndicator, "Unit only")
    assert si.activity_unit is not None and si.activity_unit.name == "h"
    assert si.activity_quantity is not None


def test_a_method_source_the_server_drops_is_reported(session, client):
    client.drops_method_source = True
    ok(session, 'MAKE SOURCE "Synthetic paper"\nEND SOURCE')
    r = ok(session, '''
MAKE METHOD "Sourced method"
    SOURCE "Synthetic paper"
    CATEGORY "Sourced climate" UNIT "kg CO2 eq"
        FACTOR "Methane, fossil", 29.8
    END CATEGORY
END METHOD''')
    assert "did not keep the SOURCE" in r.text
    assert one(client, o.ImpactMethod, "Sourced method").source is None


def test_a_method_source_that_is_kept_is_not_mentioned(session, client):
    ok(session, 'MAKE SOURCE "Synthetic paper"\nEND SOURCE')
    r = ok(session, '''
MAKE METHOD "Sourced method"
    SOURCE "Synthetic paper"
    CATEGORY "Sourced climate" UNIT "kg CO2 eq"
        FACTOR "Methane, fossil", 29.8
    END CATEGORY
END METHOD''')
    assert "did not keep" not in r.text
    assert one(client, o.ImpactMethod, "Sourced method").source.name == "Synthetic paper"
