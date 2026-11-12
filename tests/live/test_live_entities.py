"""
Live tests: every entity type against a real openLCA.

    pytest -m live

Everything is made in the folder "00: olcaBASIC live entities": an
actor, a source, a currency, a location, a unit group with its flow
property, a social indicator, a data quality system, an impact method
with a normalisation and weighting set, a project and a stored result.
Each is read back from openLCA. The method is used to calculate the
reference model, and its one factor is checked against the inventory.

The method, the project and the stored result are deleted at the end.
The other entities stay and are reused by the next run: before openLCA
2.7 the server cannot say where an actor, source, currency or location
is used, so deleting one means reading every process, which takes more
than half an hour on a large database. Set OLCA_LIVE_DELETE_FLOW=1 to
delete them too.

Nothing here names a dataset of the database: the elementary flow the
method characterises is picked from the inventory of the reference
model when the test runs.
"""

import json
import os

import pytest
import olca_schema as o

from test_live_baseline import close

pytestmark = pytest.mark.live

FOLDER = "00: olcaBASIC live entities"
P = "olcaBASIC live"            # prefix of every name made here
ACTOR = f"{P} actor"
SOURCE = f"{P} source"
CURRENCY = f"{P} currency"
LOCATION = f"{P} location"
UNITS = f"{P} units"
PROPERTY = f"{P} quantity"
SOCIAL = f"{P} social indicator"
DQ = f"{P} quality system"
METHOD = f"{P} method"
CATEGORY = f"{P} category"
OTHER = f"{P} second category"
NW = f"{P} set"
PROJECT = f"{P} project"
STORED = f"{P} stored result"


def near(a, b, tol=1e-6):
    return close(a, b, tol) or abs(a - b) < 1e-15


def get(runner, cls, name):
    client = runner.engine.client
    found = [d for d in client.get_descriptors(cls) if d.name == name]
    assert len(found) == 1, f"{len(found)} {cls.__name__} called {name}"
    return client.get(cls, found[0].id)


def refused(runner, code):
    r = runner.session.run(code)
    assert not r.ok, r.text
    return r.errors[0]


@pytest.fixture(scope="module")
def made(runner):
    """The simple entities, made once (or found from an earlier run)."""
    runner.session.run(f'''CLOSE RESULT ALL
CONFIRM DELETE ON
DELETE RESULT "{STORED}"
DELETE PROJECT "{PROJECT}"
DELETE METHOD "{METHOD}"''')
    runner.run(f'''
SET PROCESS FOLDER "{FOLDER}"
SET FLOW FOLDER "{FOLDER}"
MAKE ACTOR "{ACTOR}"
    CITY "Leeds"
    COUNTRY "United Kingdom"
    EMAIL "live@example.org"
    DESCRIPTION "Made by the olcaBASIC live tests"
END ACTOR
MAKE SOURCE "{SOURCE}"
    REFERENCE "olcaBASIC live tests (2026)."
    YEAR 2026
    URL "https://example.org/live"
END SOURCE
MAKE LOCATION "{LOCATION}"
    CODE "OLB-LIVE"
    LATITUDE 53.8
    LONGITUDE -1.55
END LOCATION
MAKE UNITS "{UNITS}"
    UNIT "olb_tu", 1 REFERENCE
    UNIT "olb_ktu", 1000 SYNONYMS "olb kilo test unit"
END UNITS
MAKE PROPERTY "{PROPERTY}"
    UNITS "{UNITS}"
END PROPERTY
MAKE SOCIAL INDICATOR "{SOCIAL}"
    ACTIVITY VARIABLE "Working hours"
    ACTIVITY UNIT "h"
    MEASURED IN "h per week"
END SOCIAL INDICATOR
MAKE DQ SYSTEM "{DQ}"
    SOURCE "{SOURCE}"
    UNCERTAINTIES YES
    INDICATOR "Reliability"
    SCORE 1 "Verified" UNCERTAINTY 1.0
    SCORE 2 "Estimated" UNCERTAINTY 1.2
    INDICATOR "Completeness"
    SCORE 1 "All sites"
    SCORE 2 "Some sites"
END DQ SYSTEM
''')
    # a currency needs a factor once the database has a reference one
    client = runner.engine.client
    has_ref = bool(client.get_descriptors(o.Currency))
    factor = "    FACTOR 1.25\n" if has_ref else ""
    refs = [c for c in client.get_all(o.Currency)
            if c.ref_currency is None or c.ref_currency.id == c.id]
    reference = (f'    REFERENCE "{refs[0].id}"\n'
                 if has_ref and len(refs) > 1 else "")
    runner.run(f'MAKE CURRENCY "{CURRENCY}"\n    CODE "OLB"\n{factor}'
               f'{reference}END CURRENCY')
    yield runner
    if os.getenv("OLCA_LIVE_DELETE_FLOW") == "1":
        runner.session.run(f'''CONFIRM DELETE ON
DELETE DQ SYSTEM "{DQ}"
DELETE SOCIAL INDICATOR "{SOCIAL}"
DELETE PROPERTY "{PROPERTY}"
DELETE UNITS "{UNITS}"
DELETE LOCATION "{LOCATION}"
DELETE CURRENCY "{CURRENCY}"
DELETE SOURCE "{SOURCE}"
DELETE ACTOR "{ACTOR}"''')


def test_everything_made_is_in_the_test_folder(made):
    for cls, name in ((o.Actor, ACTOR), (o.Source, SOURCE),
                      (o.Currency, CURRENCY), (o.Location, LOCATION),
                      (o.UnitGroup, UNITS), (o.FlowProperty, PROPERTY),
                      (o.SocialIndicator, SOCIAL), (o.DQSystem, DQ)):
        entity = get(made, cls, name)
        assert (entity.category or "").startswith(FOLDER), name


def test_actor_source_location_read_back(made):
    a = get(made, o.Actor, ACTOR)
    assert (a.country, a.email) == ("United Kingdom", "live@example.org")
    s = get(made, o.Source, SOURCE)
    assert (s.year, s.url) == (2026, "https://example.org/live")
    loc = get(made, o.Location, LOCATION)
    assert loc.code == "OLB-LIVE"
    assert near(loc.latitude, 53.8) and near(loc.longitude, -1.55)


def test_currency_points_at_a_reference_currency(made):
    cur = get(made, o.Currency, CURRENCY)
    assert cur.code == "OLB" and cur.ref_currency is not None
    assert cur.conversion_factor in (1.0, 1.25)


def test_units_and_property_read_back(made):
    group = get(made, o.UnitGroup, UNITS)
    factors = {u.name: u.conversion_factor for u in group.units}
    assert factors == {"olb_tu": 1.0, "olb_ktu": 1000.0}
    assert [u.name for u in group.units if u.is_ref_unit] == ["olb_tu"]
    prop = get(made, o.FlowProperty, PROPERTY)
    assert prop.unit_group.id == group.id


def test_social_indicator_and_dq_system_read_back(made):
    si = get(made, o.SocialIndicator, SOCIAL)
    assert si.activity_variable == "Working hours"
    assert si.activity_unit is not None and si.activity_unit.name == "h"
    dq = get(made, o.DQSystem, DQ)
    assert dq.has_uncertainties is True
    assert dq.source is not None and dq.source.name == SOURCE
    assert sorted(i.name for i in dq.indicators) == ["Completeness",
                                                     "Reliability"]
    assert all(len(i.scores) == 2 for i in dq.indicators)


def test_making_again_changes_nothing(made):
    r = made.session.run(f'MAKE ACTOR "{ACTOR}"\n    CITY "York"\nEND ACTOR')
    assert r.ok and "exists already" in r.text
    assert get(made, o.Actor, ACTOR).city in ("Leeds", "Sheffield")


def test_edit_and_move(made):
    made.run(f'EDIT ACTOR "{ACTOR}"\n    CITY "Sheffield"\nEND EDIT')
    a = get(made, o.Actor, ACTOR)
    assert (a.city, a.email) == ("Sheffield", "live@example.org")
    made.run(f'EDIT ACTOR "{ACTOR}"\n    CITY "Leeds"\nEND EDIT')
    made.run(f'MOVE ACTOR "{ACTOR}" TO "{FOLDER}/moved"')
    assert get(made, o.Actor, ACTOR).category == f"{FOLDER}/moved"
    made.run(f'MOVE ACTOR "{ACTOR}" TO "{FOLDER}"')
    assert get(made, o.Actor, ACTOR).category == FOLDER


def test_find_and_show(made):
    for word, name in (("ACTOR", ACTOR), ("SOURCE", SOURCE),
                       ("CURRENCY", CURRENCY), ("LOCATION", LOCATION),
                       ("UNITS", UNITS), ("PROPERTY", PROPERTY),
                       ("SOCIAL INDICATOR", SOCIAL), ("DQ SYSTEM", DQ)):
        found = made.run(f'FIND {word} "{P}"')
        assert name in [e["name"] for e in found["entities"]], word
        shown = made.run(f'SHOW {word} "{name}"')
        assert shown["name"] == name
        data = made.run(f'SHOW {word} "{name}" JSON')["json"]
        assert data["name"] == name and data["@type"]
    for word in ("PARAMETER", "CATEGORY", "PROJECT", "RESULT", "EPD"):
        assert made.run(f"FIND {word}")["type"] == word


def test_show_json_is_what_openlca_stores(made):
    r = made.session.run(f'SHOW LOCATION "{LOCATION}" JSON')
    assert r.ok
    data = json.loads(r.text[r.text.index("{"):])
    assert data["@type"] == "Location" and data["code"] == "OLB-LIVE"


def test_flow_maps_are_refused(made):
    e = refused(made, "FIND FLOW MAP")
    assert "IPC" in e["message"]


def test_attach_a_file_or_say_why_not(made, tmp_path):
    f = tmp_path / "olcabasic_live.txt"
    f.write_text("olcaBASIC live test attachment")
    name = f"{SOURCE} with file"
    r = made.session.run(
        f'MAKE SOURCE "{name}"\n    ATTACH "{f.as_posix()}"\nEND SOURCE')
    if made.engine.ipc_supports("data/put/source-file"):
        if "exists already" not in r.text:
            assert r.ok, r.errors
            assert get(made, o.Source, name).external_file
    else:
        if "exists already" not in r.text:
            assert not r.ok
            assert "2.6.2" in r.errors[0]["message"] + r.errors[0]["hint"]
        assert get(made, o.Source, name)


def test_export_json_ld(made, tmp_path):
    target = tmp_path / "olcabasic_live_actor.zip"
    r = made.session.run(f'EXPORT ACTOR "{ACTOR}" TO "{target.as_posix()}"')
    if not r.ok and "needs openLCA" in r.errors[0]["message"]:
        pytest.skip(r.errors[0]["message"])
    assert r.ok, r.errors
    assert target.exists() and target.stat().st_size > 0
    import zipfile
    with zipfile.ZipFile(target) as z:
        assert any(n.startswith("actors/") for n in z.namelist())


# ── method, project, stored result ───────────────────────────

@pytest.fixture(scope="module")
def method(made, live, baseline, names):
    """An own method with one factor of 2 on the largest elementary
    flow of the reference model, and a second, empty category."""
    system = names["name"]
    first = next(iter(baseline["calculate"]))
    live.run(f'CALCULATE "{system}" USING "{first}"')
    row = live.run("RESULT FLOWS TOP 1")["rows"][0]
    live.run("CLOSE RESULT ALL")
    made = live.session.run(f'''
MAKE METHOD "{METHOD}" FOLDER "{FOLDER}"
    DESCRIPTION "Made by the olcaBASIC live tests"
    SOURCE "{SOURCE}"
    CATEGORY "{CATEGORY}" UNIT "test eq" CODE "OLB"
        FACTOR "{row["flow_id"]}", 2
    END CATEGORY
    CATEGORY "{OTHER}" UNIT "test eq"
    END CATEGORY
    NW SET "{NW}" UNIT "pt"
        "{CATEGORY}", 1000, 0.5
        "{OTHER}", 10, 0.5
    END NW SET
END METHOD''')
    assert made.ok, f"{made.errors}\n{made.text}"
    yield {"live": live, "system": system, "flow": row, "text": made.text}
    live.session.run(f'''CLOSE RESULT ALL
CONFIRM DELETE ON
DELETE RESULT "{STORED}"
DELETE PROJECT "{PROJECT}"
DELETE METHOD "{METHOD}"''')


def test_the_method_is_tagged_and_read_back(method):
    live = method["live"]
    m = get(live, o.ImpactMethod, METHOD)
    assert "olcaBASIC" in (m.tags or [])
    assert sorted(c.name for c in m.impact_categories) == sorted(
        [CATEGORY, OTHER])
    # openLCA 2.6 reads a method's source as text and drops the
    # reference; olcaBASIC must then say so (found live, 12/11/2026).
    if m.source is None:
        assert "did not keep the SOURCE" in method["text"]
    else:
        assert m.source.name == SOURCE
    cat = get(live, o.ImpactCategory, CATEGORY)
    assert len(cat.impact_factors) == 1
    assert cat.impact_factors[0].flow.id == method["flow"]["flow_id"]
    assert near(cat.impact_factors[0].value, 2.0)
    assert [s.name for s in m.nw_sets] == [NW]


def test_the_method_calculates_factor_times_inventory(method):
    live = method["live"]
    got = live.run(f'CALCULATE "{method["system"]}" USING "{METHOD}" '
                   f'NW SET "{NW}"')
    total = next(i["amount"] for i in got["impacts"]
                 if i["category"] == CATEGORY)
    sign = -1.0 if method["flow"]["direction"] == "input" else 1.0
    want = 2.0 * method["flow"]["amount"]
    assert near(abs(total), abs(want)), (total, want, sign)
    norm = {r["category"]: r["amount"]
            for r in live.run("RESULT NORMALISED")["rows"]}
    assert near(norm[CATEGORY], total / 1000)
    weighted = {r["category"]: r["amount"]
                for r in live.run("RESULT WEIGHTED")["rows"]}
    assert near(weighted[CATEGORY], total / 1000 * 0.5)
    method["total"] = total


def test_save_result_as_and_read_back(method):
    live = method["live"]
    live.run(f'SAVE RESULT AS "{STORED}" FOLDER "{FOLDER}" REPLACE')
    stored = get(live, o.Result, STORED)
    assert stored.product_system.name == method["system"]
    assert stored.impact_method.name == METHOD
    amounts = {i.indicator.name: i.amount for i in stored.impact_results}
    assert near(amounts[CATEGORY], method["total"])
    assert sum(1 for f in stored.flow_results if f.is_ref_flow) == 1
    assert len(stored.flow_results) > 1
    shown = live.run(f'SHOW RESULT "{STORED}"')
    assert shown["name"] == STORED
    live.run("CLOSE RESULT ALL")


def test_edit_own_method_changes_the_result(method):
    live = method["live"]
    live.run(f'''
EDIT METHOD "{METHOD}"
    CATEGORY "{CATEGORY}"
        FACTOR "{method["flow"]["flow_id"]}", 3
    END CATEGORY
END EDIT''')
    got = live.run(f'CALCULATE "{method["system"]}" USING "{METHOD}"')
    total = next(i["amount"] for i in got["impacts"]
                 if i["category"] == CATEGORY)
    assert near(total, method["total"] * 1.5)
    live.run("CLOSE RESULT ALL")
    method["total3"] = total


def test_project_compares_its_variants(method):
    live = method["live"]
    system = get(live, o.ProductSystem, method["system"])
    unit = system.target_unit.name
    amount = system.target_amount or 1.0
    live.run(f'''
MAKE PROJECT "{PROJECT}" FOLDER "{FOLDER}"
    METHOD "{METHOD}"
    NW SET "{NW}"
    VARIANT "base" SYSTEM "{method["system"]}"
    END VARIANT
    VARIANT "double" SYSTEM "{method["system"]}" AMOUNT {2 * amount} {unit}
    END VARIANT
    VARIANT "off" SYSTEM "{method["system"]}" DISABLED
    END VARIANT
END PROJECT''')
    p = get(live, o.Project, PROJECT)
    assert [v.name for v in p.variants] == ["base", "double", "off"]
    assert p.impact_method.name == METHOD and p.nw_set.name == NW
    got = live.run(f'CALCULATE PROJECT "{PROJECT}"')
    assert list(got["results"]) == ["base", "double"]

    def total(name):
        return next(i["amount"] for i in got["results"][name]
                    if i["category"] == CATEGORY)
    assert near(total("base"), method["total3"])
    assert near(total("double"), 2 * method["total3"])
    assert near(got["normalised"]["base"][CATEGORY],
                method["total3"] / 1000)
    assert live.session.open_results == []


def test_a_method_in_use_is_not_deleted(method):
    live = method["live"]
    e = refused(live, f'CONFIRM DELETE ON\nDELETE METHOD "{METHOD}"')
    assert "still used by" in e["message"]
    assert get(live, o.ImpactMethod, METHOD)


def test_a_foreign_method_is_refused_and_untouched(method, baseline):
    """An installed method is never edited: the refusal comes before
    anything is written."""
    live = method["live"]
    foreign = next(iter(baseline["calculate"]))
    before = get(live, o.ImpactMethod, foreign).to_dict()
    cat = before["impactCategories"][0]["name"]
    e = refused(live, f'''
EDIT METHOD "{foreign}"
    CATEGORY "{cat}"
        FACTOR "{method["flow"]["flow_id"]}", 1
    END CATEGORY
END EDIT''')
    assert "was not made by olcaBASIC" in e["message"]
    assert "Back the database up first" in e["hint"]
    e = refused(live, f'CONFIRM DELETE ON\nDELETE METHOD "{foreign}"')
    assert "was not made by olcaBASIC" in e["message"]
    assert get(live, o.ImpactMethod, foreign).to_dict() == before


def test_delete_what_was_made(method):
    live = method["live"]
    live.run(f'''CONFIRM DELETE ON
DELETE RESULT "{STORED}"
DELETE PROJECT "{PROJECT}"
DELETE METHOD "{METHOD}"''')
    client = live.engine.client
    for cls, name in ((o.Result, STORED), (o.Project, PROJECT),
                      (o.ImpactMethod, METHOD), (o.ImpactCategory, CATEGORY),
                      (o.ImpactCategory, OTHER)):
        assert not [d for d in client.get_descriptors(cls)
                    if d.name == name], name
