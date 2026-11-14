"""
The EPD toolkit: data quality over the impact indicators with a residual
check and scenarios, representativeness ratings, the register and the
assessment table, biogenic carbon balances, group sensitivity, the model
export, and several products in one program.

Everything is synthetic: a timber-like product with made-up names and
numbers, on the fake client's synthetic EN 15804+A2 method.
"""

import csv
import datetime
import json

import pytest
import olca_schema as o

from fake_client import (
    BIO_CH4, BIO_CH4_FACTOR, BIO_CO2, BIO_UPTAKE, ELECTRICITY, EPD_BIOGENIC,
    EPD_GWP, EPD_IMPACT_INDICATORS, EPD_METHOD, LANDFILL, STEEL, TRANSPORT,
    add_epd_methods, epd_indicator, nothing_left_open, seed_ecoinvent_like,
)
from olcabasic import Session
from olcabasic.parser import ParseError, parse
from olcabasic.workflows import en15804, programmes
from olcabasic.workflows.epd import EpdWorkflow
from olcabasic.workflows.epd_toolkit import (decode_reason, encode_reason,
                                             ratings_of)

FOLDER = "00: Test timber"
C = 44.0 / 12.0                 # kg CO2 per kg C

# One kg of product holds 0.45 kg of biogenic carbon (0.9 kg oven-dry
# wood); sawdust carrying 0.05 kg C leaves A1 as a co-product.
PRODUCT_C = 0.45
SAWDUST_C = 0.05
STORED = PRODUCT_C * C          # 1.65 kg CO2


@pytest.fixture
def client():
    c = add_epd_methods(seed_ecoinvent_like())
    yield c
    nothing_left_open(c)


@pytest.fixture
def session(client):
    s = Session(client=client)
    assert s.run('DATABASE FAMILY "ecoinvent"').ok
    return s


@pytest.fixture(autouse=True)
def fixed_date(monkeypatch):
    monkeypatch.setattr(EpdWorkflow, "today",
                        staticmethod(lambda: datetime.date(2026, 11, 12)))


def uid(client, name, location):
    for p in client.store["Process"].values():
        if p.name == name and p.location is not None \
                and client._location_code(p.location) == location:
            return p.id
    raise AssertionError(f"no {name} at {location}")


SECONDARY = 'DATA SECONDARY SOURCE "Database" PROVIDER "synthetic 1" YEAR 2024'
PRIMARY = 'DATA PRIMARY SOURCE "Collected" PROVIDER "EPD owner" YEAR 2025'
RATINGS = (
    'RATING GEOGRAPHY "Good" REASON "Synthetic data, same region"\n'
    '  RATING TECHNOLOGY "Very good" REASON "Synthetic data, same '
    'technology"\n'
    '  RATING TIME "Fair" REASON "Synthetic data, nine years old"')


def block(name="Test timber", folder=FOLDER, biogenic=True, content=None,
          exports=True, programme=True, extra=""):
    head = ('  PROGRAMME "IES" GPI "5.1.0"\n  PCR "Test PCR" VERSION "1.0"\n'
            '  DATABASE "synthetic" VERSION "1"\n') if programme else ""
    bio = "  BIOGENIC CARBON NO\n"
    if biogenic:
        bio = ("  BIOGENIC CARBON YES\n  "
               + (content or f"BIOGENIC CONTENT PRODUCT {PRODUCT_C} kg C")
               + "\n")
        if exports:
            bio += f'  BIOGENIC EXPORT A1 "Sawdust", {SAWDUST_C} kg C\n'
    return (f'EPD "{name}"\n{head}  DECLARED UNIT 1, kg\n'
            f'  METHOD "{EPD_METHOD}"\n  FOLDER "{folder}"\n'
            f'  MODULES A1, A2, A3, C1, C2, C3, C4, D\n{bio}{extra}END EPD\n')


def bridges(client, ratings=RATINGS):
    gb = uid(client, ELECTRICITY, "GB")
    return f'''
BRIDGE "Steel", kg
  PROVIDER "{STEEL}"
  {SECONDARY}
  {ratings}
END BRIDGE
BRIDGE "Electricity", kWh
  PROVIDER "{gb}"
  ELECTRICITY RESIDUAL
  COUNTRY "GB"
  ENERGY SOURCE "Test mix"
  DATA PRIMARY SOURCE "Database" PROVIDER "synthetic 1" YEAR 2024
  {ratings}
END BRIDGE
BRIDGE "Lorry", t*km
  PROVIDER "{TRANSPORT}"
  DATA PRIMARY SOURCE "Database" PROVIDER "synthetic 1" YEAR 2024
  {ratings}
END BRIDGE
BRIDGE "Landfill", kg WASTE
  PROVIDER "{LANDFILL}"
  {SECONDARY}
  {ratings}
END BRIDGE
'''


def modules(uptake=(PRODUCT_C + SAWDUST_C) * C, sawdust_out=SAWDUST_C * C,
            c3_release=0.9 * STORED, c4_release=0.1 * STORED, d_uptake=0.0,
            direct_background="", kwh="kiln_kwh", tkm="road_tkm",
            ratings=RATINGS):
    """The timber-like model. Defaults are a model built right: the
    uptake covers the log, the sawdust leaves A1 with its carbon, the
    carbon is released or leaves at end of life, and D has none."""
    sawdust = (f'    OUTPUT "{BIO_CO2}", {sawdust_out}, kg TO AIR\n'
               if sawdust_out else "")
    d_line = (f'    INPUT "{BIO_UPTAKE}", {d_uptake}, kg FROM NATURE\n'
              if d_uptake else "")
    return f'''
MODULE A1
  MAKE PROCESS "Forestry and sawing"
    {PRIMARY}
    {ratings}
    OUTPUT MAKE FLOW "Sawn timber", 1, kg, PRODUCT
    INPUT "{BIO_UPTAKE}", {uptake}, kg FROM NATURE
{sawdust}    INPUT USE PROCESS "BRIDGE | Steel | kg", 0.3, kg
{direct_background}  END PROCESS
  TOTAL "Raw material supply"
END MODULE
MODULE A2
  MAKE PROCESS "Transport to the mill"
    {PRIMARY}
    {ratings}
    OUTPUT MAKE FLOW "Transport, done", 1, kg, PRODUCT
    INPUT USE PROCESS "BRIDGE | Lorry | t*km", {tkm}, t*km
  END PROCESS
  TOTAL "Transport"
END MODULE
MODULE A3
  MAKE PROCESS "Kilning and planing"
    {PRIMARY}
    {ratings}
    OUTPUT MAKE FLOW "Timber, at gate", 1, kg, PRODUCT
    INPUT USE PROCESS "BRIDGE | Electricity | kWh", {kwh}, kWh
    OUTPUT "{BIO_CH4}", 0.0001, kg TO AIR
  END PROCESS
  TOTAL "Manufacturing"
END MODULE
MODULE C1
  TOTAL "Deconstruction"
END MODULE
MODULE C2
  MAKE PROCESS "Transport to waste processing"
    {SECONDARY}
    {ratings}
    OUTPUT MAKE FLOW "Waste transport, done", 1, kg, PRODUCT
    INPUT USE PROCESS "BRIDGE | Lorry | t*km", 0.05, t*km
  END PROCESS
  TOTAL "Transport"
END MODULE
MODULE C3
  MAKE PROCESS "Chipping for reuse"
    {SECONDARY}
    {ratings}
    OUTPUT MAKE FLOW "Chipping, done", 1, kg, PRODUCT
    OUTPUT "{BIO_CO2}", {c3_release}, kg TO AIR
    INPUT USE PROCESS "BRIDGE | Electricity | kWh", 0.02, kWh
  END PROCESS
  TOTAL "Waste processing"
END MODULE
MODULE C4
  MAKE PROCESS "Landfilling"
    {SECONDARY}
    {ratings}
    OUTPUT MAKE FLOW "Disposal, done", 1, kg, PRODUCT
    OUTPUT "{BIO_CO2}", {c4_release}, kg TO AIR
    OUTPUT USE PROCESS "BRIDGE | Landfill | kg", 0.1, kg
  END PROCESS
  TOTAL "Disposal"
END MODULE
MODULE D
  NET FLOW "Wood chips", 0.9, kg QUALITY 80%
  MAKE PROCESS "Avoided virgin timber"
    {SECONDARY}
    {ratings}
    OUTPUT MAKE FLOW "Credit", 1, kg, PRODUCT
{d_line}    INPUT USE PROCESS "BRIDGE | Steel | kg", -0.02, kg
  END PROCESS
  TOTAL "Benefits beyond the system boundary"
END MODULE
'''


PARAMS = "LET kiln_kwh = 2\nLET road_tkm = 0.2\n"
STEPS = "EPD SYSTEMS\nEPD CHECK\nEPD CALCULATE\n"


def build(session, client, epd=None, **kw):
    r = session.run(PARAMS + (epd or block()) + bridges(client)
                    + modules(**kw))
    assert r.ok, f"{r.errors}\n{r.text}"
    return r


def ready(session, client, **kw):
    build(session, client, **kw)
    r = session.run(STEPS)
    assert r.ok, f"{r.errors}\n{r.text}"
    return r


def use_directly(client, process_name, provider_name, amount):
    """Add an input that buys straight from a background process, the
    way a model edited in openLCA itself can end up. (olcaBASIC refuses
    to build this inside a MODULE.)"""
    proc = next(p for p in client.store["Process"].values()
                if p.name == process_name)
    provider = next(p for p in client.store["Process"].values()
                    if p.name == provider_name)
    ref = next(ex for ex in provider.exchanges
               if ex.is_quantitative_reference)
    proc.exchanges.append(o.Exchange(
        internal_id=max(ex.internal_id or 0 for ex in proc.exchanges) + 1,
        is_input=True, amount=amount, flow=ref.flow, unit=ref.unit,
        flow_property=ref.flow_property,
        default_provider=o.Ref(id=provider.id, name=provider.name,
                               ref_type=o.RefType.Process)))


def refused(result, *words):
    assert not result.ok, result.text
    text = result.errors[0]["message"] + " " + result.errors[0]["hint"]
    for word in words:
        assert word in text, f"{word!r} not in: {text}"
    return result.errors[0]


def said(result, *words):
    for word in words:
        assert word in result.text, f"{word!r} not in:\n{result.text}"


# ── the indicators, by code ──────────────────────────────────

@pytest.mark.parametrize("name,code", [
    ("Climate change - total (GWP-total)", "GWP-total"),
    ("Climate change (GWP-total) - v3.1", "GWP-total"),
    ("PCR - Climate change (GWP-IOBC/GHG) - v3.1", "GWP-GHG"),
    ("Depletion of abiotic resources (ADP-minerals&metals)", "ADPE"),
    ("Resources, fossil (ADPF)", "ADPF"),
    ("Use of renewable primary energy (PERE)", "PERE"),
    ("EN15804+A2 (EF 3.1)", None),
    ("Something without a code", None),
])
def test_the_code_is_read_from_the_brackets(name, code):
    assert en15804.indicator_code(name) == code


def test_the_impact_indicator_list_is_a_named_value_of_the_profile():
    p = programmes.get("IES")
    assert p.impact_indicator_codes == (
        "GWP-total", "GWP-fossil", "GWP-biogenic", "GWP-luluc", "ODP", "AP",
        "EP-freshwater", "EP-marine", "EP-terrestrial", "POCP", "ADPE",
        "ADPF", "WDP", "GWP-GHG", "PM", "IRP", "ETP-fw", "HTP-c", "HTP-nc",
        "SQP")
    assert len(p.impact_indicator_codes) == 20
    assert (p.residual_tolerance_pct, p.residual_floor) == (0.1, 1e-9)
    assert p.dq_levels == ("Very good", "Good", "Fair", "Poor", "Very poor")
    assert en15804.CARBON_FRACTION_OF_DRY_WOOD == 0.5


def test_the_gwp_indicator_is_found_by_its_code(session, client):
    client.add_method("EN15804+A2 (coded)", {
        **{f"Indicator {n:02d} ({c})": "u" for n, c in enumerate(
            programmes.get("IES").impact_indicator_codes) if c != "GWP-GHG"},
        "PCR - Climate change (GWP-IOBC/GHG)": "kg CO2 eq.",
        **{f"Other {n:02d}": "u" for n in range(18)}})
    r = session.run(block(biogenic=False).replace(
        EPD_METHOD, "EN15804+A2 (coded)"))
    assert r.ok, r.errors
    assert session.runtime.epd.gwp_indicator == (
        "PCR - Climate change (GWP-IOBC/GHG)")


# ── data quality: impact indicators only ─────────────────────

def test_coverage_and_proxy_run_over_the_impact_indicators(session, client):
    ready(session, client)
    r = session.run("EPD DATA QUALITY")
    assert r.ok, r.errors
    data = session.runtime.epd.dq
    assert data["impact_indicators"] == 20
    assert data["indicators_reported"] == 38
    assert max(c["indicators"] for c in data["coverage"]) <= 20
    said(r, "Counted: the 20 environmental impact indicators of the "
            "method's 38 categories", "reported, not counted",
         "of 20 impact indicators")


def test_a_resource_indicator_does_not_count_towards_the_proxy_limit(
        session, client):
    """Proxy data that dominates a resource use indicator only is not
    over the limit; the same share of an impact indicator is."""
    resource = epd_indicator(21)            # (PERE)
    impact = epd_indicator(7)               # (AP)
    for name, gives in (("Proxy resource only", {resource: 50.0}),
                        ("Proxy impact too", {impact: 50.0})):
        flow = client.add_flow(f"test {name}", "Mass",
                               category="C:Test manufacturing")
        client.add_background_process(name, flow, "kg", "GLO",
                                      "C:Test manufacturing", gives)
    extra_bridges = f'''
BRIDGE "Resource proxy", kg
  PROVIDER "Proxy resource only"
  DATA PROXY SOURCE "Database" PROVIDER "synthetic 1" YEAR 2024 REASON "Test"
  {RATINGS}
END BRIDGE
BRIDGE "Impact proxy", kg
  PROVIDER "Proxy impact too"
  DATA PROXY SOURCE "Database" PROVIDER "synthetic 1" YEAR 2024 REASON "Test"
  {RATINGS}
END BRIDGE
'''
    use = '    INPUT USE PROCESS "BRIDGE | Resource proxy | kg", 1, kg\n'
    r = session.run(PARAMS + block() + bridges(client) + extra_bridges
                    + modules(direct_background=use) + STEPS
                    + "EPD DATA QUALITY")
    assert r.ok, f"{r.errors}\n{r.text}"
    assert all(row["indicator"] in EPD_IMPACT_INDICATORS
               for row in session.runtime.epd.dq["proxy"])


def test_proxy_data_in_an_impact_indicator_is_over_the_limit(session,
                                                             client):
    impact = epd_indicator(7)
    flow = client.add_flow("test proxy thing", "Mass",
                           category="C:Test manufacturing")
    client.add_background_process("Proxy impact", flow, "kg", "GLO",
                                  "C:Test manufacturing", {impact: 50.0})
    extra = f'''
BRIDGE "Impact proxy", kg
  PROVIDER "Proxy impact"
  DATA PROXY SOURCE "Database" PROVIDER "synthetic 1" YEAR 2024 REASON "Test"
  {RATINGS}
END BRIDGE
'''
    use = '    INPUT USE PROCESS "BRIDGE | Impact proxy | kg", 1, kg\n'
    r = session.run(PARAMS + block() + bridges(client) + extra
                    + modules(direct_background=use) + STEPS
                    + "EPD DATA QUALITY")
    refused(r, "EPD DATA QUALITY found")
    said(r, f"Proxy data gives", f"'{impact}'",
         "10% of any impact indicator", "A.5.1")


def test_a_method_without_codes_cannot_be_split(session, client):
    client.add_method("EN15804+A2 (uncoded)",
                      {f"Category {n:02d}": "unit" for n in range(37)}
                      | {"Climate, GWP-GHG": "kg CO2 eq."})
    r = session.run(PARAMS + block(biogenic=False).replace(
        EPD_METHOD, "EN15804+A2 (uncoded)") + bridges(client)
        + modules(uptake=0, sawdust_out=0, c3_release=0, c4_release=0)
        .replace(f'    INPUT "{BIO_UPTAKE}", 0, kg FROM NATURE\n', "")
        .replace(f'    OUTPUT "{BIO_CO2}", 0, kg TO AIR\n', "")
        + STEPS)
    assert r.ok, f"{r.errors}\n{r.text}"
    e = refused(session.run("EPD DATA QUALITY"),
                "could not be picked out", "GWP-total", "in brackets")
    assert "Tables 3 and 4" in e["hint"] and "A.5.4" in e["hint"]


# ── the residual check ───────────────────────────────────────

def test_the_parts_add_up_on_a_model_built_through_bridges(session, client):
    ready(session, client)
    epd = session.runtime.epd
    split = {c: epd._parts(c, epd._system_of(c), 0) for c in epd.d["modules"]}
    assert epd._residuals(split) == []
    assert all(not data["unbridged"] for data in split.values())


def test_a_background_process_used_directly_is_refused_at_calculate(
        session, client):
    build(session, client)
    use_directly(client, "A1 | Forestry and sawing", STEEL, 0.5)
    e = refused(session.run(STEPS), "EPD CALCULATE refused",
                "no bridge", "A1 | Forestry and sawing")
    assert "BRIDGE" in e["hint"]


def test_a_background_process_used_directly_gives_a_residual_error(
        session, client, monkeypatch):
    """The residual check stays as a second line: with the bridge gate
    out of the way, the split still finds the gap."""
    build(session, client)
    use_directly(client, "A1 | Forestry and sawing", STEEL, 0.5)
    monkeypatch.setattr(
        type(session.engine), "system_unbridged",
        lambda self, ref, folders=None: {"unbridged": []})
    r = session.run(STEPS)
    assert r.ok, f"{r.errors}\n{r.text}"
    r = session.run("EPD DATA QUALITY")
    e = refused(r, "EPD DATA QUALITY found")
    said(r, "Module A1: the module's processes and bridges add up to",
         "but the module total is", "a gap of", "limit 0.1%",
         "other indicators have a gap too",
         f"Used without a bridge in this module: '{STEEL}'",
         "Put each behind a BRIDGE block")
    assert session.runtime.epd.dq["passed"] is False
    assert any("Module A1" in x for x in session.runtime.epd.dq["errors"])
    # and the report is refused
    refused(session.run('EPD REPORT "x.csv"'), "EPD REPORT refused")


def test_the_residual_tolerance_and_floor_are_the_profiles(session, client,
                                                           monkeypatch):
    ready(session, client)
    epd = session.runtime.epd
    split = {"A1": {"totals": {"x": 100.0, "tiny": 1e-12},
                    "parts": [{"values": {"x": 99.95, "tiny": 0.0}}],
                    "unbridged": []}}
    assert epd._residuals(split) == []                 # 0.05% and below floor
    split["A1"]["parts"][0]["values"]["x"] = 99.8      # 0.2%
    found = epd._residuals(split)
    assert len(found) == 1 and "0.20%" in found[0]
    assert "The usual cause is an input that does not go through a bridge" \
        in found[0]


# ── ratings ──────────────────────────────────────────────────

def test_ratings_are_stored_on_the_process(session, client):
    build(session, client)
    bridge = next(p for p in client.store["Process"].values()
                  if p.name == "BRIDGE | Steel | kg")
    have = ratings_of(session.engine.get_process_tags(bridge.id, "epd")["tags"])
    assert have["GEOGRAPHY"] == {"level": "Good",
                                 "reason": "Synthetic data, same region"}
    assert have["TIME"]["level"] == "Fair"
    # The ratings are in the description, where openLCA shows them, and
    # not in the tags: openLCA keeps 255 characters of tags for a
    # process and refuses a save that overruns them (found live).
    assert "Data quality ratings (olcaBASIC):" in bridge.description
    assert "Geography: Good. Synthetic data, same region" in bridge.description
    assert not any("rating" in t for t in bridge.tags)
    assert len(",".join(bridge.tags)) <= 255


def test_long_reasons_do_not_overrun_the_tags(session, client):
    """Three long reasons used to make openLCA refuse the save, and
    the data declaration was lost with them."""
    long = "A reason that runs to a good many words, as real ones do. " * 4
    build(session, client, ratings="")
    r = session.run(
        'EDIT PROCESS "BRIDGE | Steel | kg"\n'
        f'  RATING GEOGRAPHY "Good" REASON "{long}"\n'
        f'  RATING TECHNOLOGY "Fair" REASON "{long}"\n'
        f'  RATING TIME "Poor" REASON "{long}"\n'
        'END EDIT')
    assert r.ok, r.errors
    bridge = next(p for p in client.store["Process"].values()
                  if p.name == "BRIDGE | Steel | kg")
    have = ratings_of(session.engine.get_process_tags(bridge.id, "epd")["tags"])
    assert have["TIME"] == {"level": "Poor", "reason": long.strip()}
    assert "epd:data=SECONDARY" in bridge.tags      # the declaration is kept


def test_a_description_edit_keeps_the_ratings(session, client):
    build(session, client)
    bridge = next(p for p in client.store["Process"].values()
                  if p.name == "BRIDGE | Steel | kg")
    done = session.engine.edit_process(bridge.id,
                                       description="A new description")
    assert "error" not in done, done
    bridge = client.store["Process"][bridge.id]
    assert bridge.description.startswith("A new description")
    have = ratings_of(session.engine.get_process_tags(bridge.id, "epd")["tags"])
    assert have["GEOGRAPHY"]["level"] == "Good"


def test_declarations_too_long_for_openlca_are_refused(session, client):
    """A save openLCA would refuse is an error, not a silent loss."""
    build(session, client)
    words = "x" * 300
    r = session.run('EDIT PROCESS "BRIDGE | Steel | kg"\n'
                    f'  DATA SECONDARY SOURCE "{words}" PROVIDER "p" YEAR 2024\n'
                    'END EDIT')
    refused(r, "openLCA keeps no more than 255")


def test_a_save_openlca_refuses_is_an_error(client):
    """olca-ipc returns None for a refused save; the engine raises."""
    import olca_schema as o
    import pytest as _pytest
    from olcabasic.engine import Engine
    engine = Engine(client)
    p = o.Process(id="refused-save", name="Refused",
                  tags=["t=" + "x" * 300])
    with _pytest.raises(RuntimeError, match="did not save"):
        engine.client.put(p)


def test_reasons_round_trip():
    text = "100% of supply, by mass; no data for 2019, 2020"
    assert "," not in encode_reason(text)
    assert decode_reason(encode_reason(text)) == text


def test_the_level_is_matched_whatever_its_case(session, client):
    r = session.run(block() + f'''
BRIDGE "Steel", kg
  PROVIDER "{STEEL}"
  {SECONDARY}
  RATING GEOGRAPHY "very GOOD" REASON "x"
END BRIDGE''')
    assert r.ok, r.errors
    bridge = next(p for p in client.store["Process"].values()
                  if p.name == "BRIDGE | Steel | kg")
    assert "Geography: Very good. x" in bridge.description


def test_a_level_that_is_not_on_the_scale_is_refused(session, client):
    r = session.run(block() + f'''
BRIDGE "Steel", kg
  PROVIDER "{STEEL}"
  {SECONDARY}
  RATING GEOGRAPHY "Excellent" REASON "x"
END BRIDGE''')
    e = refused(r, "'Excellent' is not a level of the data quality scale",
                '"Very good", "Good", "Fair", "Poor", "Very poor"',
                "Annex E")
    assert e["line"] == 17


@pytest.mark.parametrize("line,message", [
    ('RATING "Good" REASON "x"', "RATING needs what is rated"),
    ('RATING GEOGRAPHY', "needs a level"),
    ('RATING GEOGRAPHY "Good"', "needs REASON"),
    ('RATING GEOGRAPHY "Good" REASON', "needs REASON"),
    ('RATING GEOGRAPHY "Good" REASON "x"\n  RATING GEOGRAPHY "Fair" REASON '
     '"y"', "given twice"),
])
def test_rating_parse_errors(line, message):
    with pytest.raises(ParseError, match=message):
        parse(f'BRIDGE "Steel", kg\n  PROVIDER "p"\n  {line}\nEND BRIDGE')


def test_an_empty_reason_is_refused(session, client):
    r = session.run(block() + f'''
BRIDGE "Steel", kg
  PROVIDER "{STEEL}"
  {SECONDARY}
  RATING TIME "Good" REASON "  "
END BRIDGE''')
    refused(r, "RATING TIME has an empty REASON")


def test_edit_process_adds_a_rating(session, client):
    build(session, client, ratings="")
    r = session.run('EDIT PROCESS "BRIDGE | Lorry | t*km"\n'
                    '  RATING TIME "Poor" REASON "Fourteen years old"\n'
                    'END EDIT')
    assert r.ok, r.errors
    bridge = next(p for p in client.store["Process"].values()
                  if p.name == "BRIDGE | Lorry | t*km")
    assert "Time: Poor. Fourteen years old" in bridge.description


def test_data_quality_refuses_while_a_dataset_in_the_coverage_is_unrated(
        session, client):
    session.run(PARAMS + block() + bridges(client, ratings="")
                + modules(ratings="") + STEPS)
    r = session.run("EPD DATA QUALITY")
    e = refused(r, "EPD DATA QUALITY found", "RATING", "EPD DQ SHEET")
    said(r, "'BRIDGE | Steel | kg' is in the 80% coverage and has no RATING "
            "for GEOGRAPHY, TECHNOLOGY, TIME", "A.5.4", "[not rated]")
    assert "BRIDGE | Steel | kg" in session.runtime.epd.dq["unrated"]
    refused(session.run('EPD REPORT "x.csv"'), "EPD REPORT refused")


def test_one_missing_rating_is_enough_to_refuse(session, client):
    two = "\n".join(RATINGS.split("\n")[:2])
    session.run(PARAMS + block() + bridges(client)
                + modules().replace(
                    f'MAKE PROCESS "Chipping for reuse"\n    {SECONDARY}\n'
                    f'    {RATINGS}',
                    f'MAKE PROCESS "Chipping for reuse"\n    {SECONDARY}\n'
                    f'    {two}') + STEPS)
    r = session.run("EPD DATA QUALITY")
    if r.ok:        # only refused if the process is in the 80% set
        assert "C3 | Chipping for reuse" not in [
            c["process"] for c in session.runtime.epd.dq["coverage"]]
    else:
        said(r, "'C3 | Chipping for reuse' is in the 80% coverage and has "
                "no RATING for TIME")


def test_rated_datasets_pass(session, client):
    ready(session, client)
    r = session.run("EPD DATA QUALITY")
    assert r.ok, r.errors
    assert session.runtime.epd.dq["unrated"] == []
    said(r, "EPD DATA QUALITY passed")


# ── EPD DQ SHEET and EPD DQ TABLE ────────────────────────────

def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def test_the_sheet_lists_what_the_assessment_has_to_cover(session, client,
                                                          tmp_path):
    ready(session, client)
    out = tmp_path / "register.csv"
    r = session.run(f'EPD DQ SHEET "{out.as_posix()}"')
    assert r.ok, r.errors
    rows = read_csv(out)
    head = rows[0]
    assert head[:3] == ["Dataset", "Kind", "Modules"]
    assert "Rating: geography" in head and "Reason: time" in head
    by_name = {row[0]: dict(zip(head, row)) for row in rows[1:]}
    steel = by_name["BRIDGE | Steel | kg"]
    assert steel["Kind"] == "bridge"
    assert steel["Background process"] == STEEL
    assert steel["Background location"]
    assert steel["Data category"] == "secondary"
    assert steel["Source"] == "synthetic 1"
    assert steel["Reference year"] == "2024"
    assert steel["Rating: geography"] == "Good"
    assert steel["Reason: geography"] == "Synthetic data, same region"
    coverage = {c["process"] for c in session.run(
        "EPD DATA QUALITY").data[-1]["result"]["coverage"]}
    assert coverage <= set(by_name)
    said(r, "Every dataset the assessment has to cover is rated")
    assert r.data[-1]["call"] == "epd_dq_sheet"


def test_the_sheet_runs_before_the_ratings_are_there(session, client,
                                                     tmp_path):
    session.run(PARAMS + block() + bridges(client, ratings="")
                + modules(ratings="") + STEPS)
    out = tmp_path / "register.csv"
    r = session.run(f'EPD DQ SHEET "{out.as_posix()}"')
    assert r.ok, r.errors
    said(r, "still need ratings", "BRIDGE | Steel | kg",
         "Very good, Good, Fair, Poor, Very poor")
    rows = read_csv(out)
    steel = dict(zip(rows[0], next(row for row in rows[1:]
                                   if row[0] == "BRIDGE | Steel | kg")))
    assert steel["Rating: geography"] == ""
    assert "BRIDGE | Steel | kg" in r.data[-1]["result"]["unrated"]


def test_the_sheet_carries_what_the_background_process_says(session, client,
                                                            tmp_path):
    proc = next(p for p in client.store["Process"].values()
                if p.name == STEEL)
    proc.process_documentation = o.ProcessDocumentation(
        valid_from="2018-01-01", valid_until="2024-12-31",
        technology_description="Synthetic technology",
        geography_description="Synthetic geography",
        time_description="Synthetic period")
    ready(session, client)
    out = tmp_path / "register.csv"
    assert session.run(f'EPD DQ SHEET "{out.as_posix()}"').ok
    rows = read_csv(out)
    steel = dict(zip(rows[0], next(row for row in rows[1:]
                                   if row[0] == "BRIDGE | Steel | kg")))
    assert (steel["Valid from"], steel["Valid until"]) == ("2018-01-01",
                                                           "2024-12-31")
    assert steel["Technology description"] == "Synthetic technology"
    assert steel["Geography description"] == "Synthetic geography"
    assert steel["Time description"] == "Synthetic period"


def test_the_table_is_the_assessment_for_the_report(session, client,
                                                    tmp_path):
    ready(session, client)
    out = tmp_path / "assessment.md"
    r = session.run(f'EPD DQ TABLE "{out.as_posix()}"')
    assert r.ok, r.errors
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Data quality assessment")
    assert ("| Dataset | Products | Geographical representativeness | "
            "Technical representativeness | Temporal representativeness |"
            ) in text
    row = next(line for line in text.splitlines()
               if line.startswith("| BRIDGE | Steel | kg".replace("|", "/")
                                  .replace("/ BRIDGE", "| BRIDGE", 1)))
    assert f"(background: {STEEL.replace('|', '/')})" in row
    assert "Test timber" in row
    assert "Good. Synthetic data, same region" in row
    assert "Fair. Synthetic data, nine years old" in row
    assert "A.5.4" in text and "Annex E" in text
    assert "—" not in text and "–" not in text
    said(r, "1 product")


def test_the_sheet_and_the_table_need_the_results(session, client):
    build(session, client)
    refused(session.run('EPD DQ SHEET "x.csv"'), "needs the results",
            "EPD CALCULATE")
    refused(session.run('EPD DQ TABLE "x.md"'), "needs the results")


def test_file_commands_need_a_file_name():
    for line in ("EPD DQ SHEET", "EPD DQ TABLE", "EPD EXPORT MODEL"):
        with pytest.raises(ParseError, match="needs a file name"):
            parse(line)
    with pytest.raises(ParseError, match="EPD DQ SHEET"):
        parse('EPD DQ "x.csv"')


# ── data quality per scenario ────────────────────────────────

def test_data_quality_from_a_scenarios_file(session, client, tmp_path):
    ready(session, client)
    path = tmp_path / "scenarios.csv"
    path.write_text("Parameter,Site one,Site two\n"
                    "kiln_kwh,2,8\nroad_tkm,0.2,0.4\n")
    r = session.run(f'EPD DATA QUALITY FROM "{path.as_posix()}"')
    assert r.ok, f"{r.errors}\n{r.text}"
    said(r, "Scenario Site one: kiln_kwh = 2, road_tkm = 0.2",
         "EPD DATA QUALITY [Site two]", "passed for 2 scenarios")
    data = r.data[-1]["result"]["scenarios"]
    assert list(data) == ["Site one", "Site two"]

    def share(label):
        return {row["process"]: row["share_of_gwp"]
                for row in data[label]["rows"]}
    # four times the electricity: its share of GWP-GHG in A1-A3 goes up
    assert share("Site two")["BRIDGE | Electricity | kWh"] > \
        share("Site one")["BRIDGE | Electricity | kWh"]
    # the baseline matches the run without scenarios
    assert session.run("EPD DATA QUALITY").ok
    base = {row["process"]: row["share_of_gwp"]
            for row in session.runtime.epd.dq["rows"]}
    assert share("Site one") == pytest.approx(base)


def test_scenario_runs_do_not_open_the_gate_to_the_report(session, client,
                                                          tmp_path):
    ready(session, client)
    path = tmp_path / "scenarios.csv"
    path.write_text("Parameter,Only\nkiln_kwh,3\n")
    assert session.run(f'EPD DATA QUALITY FROM "{path.as_posix()}"').ok
    refused(session.run('EPD REPORT "x.csv"'), "EPD REPORT refused")


def test_a_scenario_parameter_no_module_holds_is_an_error(session, client,
                                                          tmp_path):
    ready(session, client)
    path = tmp_path / "scenarios.csv"
    path.write_text("Parameter,Only\nkiln_kwh,3\nkiln_kw,3\n")
    refused(session.run(f'EPD DATA QUALITY FROM "{path.as_posix()}"'),
            "No module of the EPD holds the parameter kiln_kw",
            "Check the spelling")


def test_data_quality_with_a_stored_parameter_set(session, client):
    ready(session, client)
    r = session.run('''
EDIT SYSTEM "A3: Manufacturing"
  PARAMETER SET "Hot kiln"
    kiln_kwh = 8
  END PARAMETER SET
END EDIT''')
    assert r.ok, r.errors
    r = session.run('EPD DATA QUALITY PARAMETER SET "Hot kiln"')
    assert r.ok, f"{r.errors}\n{r.text}"
    said(r, "Scenario Hot kiln: kiln_kwh = 8", "passed for 1 scenario")
    refused(session.run('EPD DATA QUALITY PARAMETER SET "Nope"'),
            "No module system has a parameter set called 'Nope'",
            "EDIT SYSTEM")


def test_a_missing_scenarios_file(session, client):
    ready(session, client)
    refused(session.run('EPD DATA QUALITY FROM "nowhere.csv"'),
            "File not found", "Parameter")


# ── biogenic carbon ──────────────────────────────────────────

def test_biogenic_carbon_yes_needs_the_content(session):
    e = refused(session.run(block(content="REM none").replace(
        "  REM none\n", "")),
        "BIOGENIC CARBON YES needs the biogenic carbon content",
        "6.4.4", "BIOGENIC CONTENT PRODUCT n kg C", "FROM MASS")
    assert e["line"] == 9


def test_content_from_dry_mass(session):
    r = session.run(block(content="BIOGENIC CONTENT PRODUCT FROM MASS 0.9 kg "
                                  "DRY PACKAGING 0.02 kg C"))
    assert r.ok, r.errors
    content = session.runtime.epd.d["biogenic_content"]
    assert content["product"] == pytest.approx(0.45)
    assert content["product_from_mass"] == 0.9
    assert content["packaging"] == 0.02


@pytest.mark.parametrize("line,message", [
    ("BIOGENIC CONTENT 0.45 kg C", "starts with PRODUCT"),
    ("BIOGENIC CONTENT PRODUCT 0.45", "write 'kg C' after the number"),
    ("BIOGENIC CONTENT PRODUCT 0.45 kg", "write 'kg C' after the number"),
    ("BIOGENIC CONTENT PRODUCT FROM 0.9 kg DRY", "Expected FROM MASS"),
    ("BIOGENIC CONTENT PRODUCT FROM MASS 0.9 kg C",
     "write 'kg DRY' after the number"),
    ("BIOGENIC CONTENT PRODUCT 1 kg C\n  BIOGENIC CONTENT PRODUCT 2 kg C",
     "given twice"),
    ('BIOGENIC EXPORT A1 "Sawdust"', "Expected a comma"),
    ('BIOGENIC EXPORT A1, 2 kg C', "needs what leaves"),
    ('BIOGENIC EXPORT "Sawdust", 2 kg C', "module"),
    ("BIOGENIC NONSENSE", "Expected BIOGENIC CARBON YES or NO"),
])
def test_biogenic_parse_errors(line, message):
    with pytest.raises(ParseError, match=message):
        parse(block(content=line, exports=False))


@pytest.mark.parametrize("content,exports,message", [
    ("BIOGENIC CONTENT PRODUCT 0 kg C", "", "the declared content is zero"),
    ("BIOGENIC CONTENT PRODUCT -1 kg C", "", "zero or more"),
    ("BIOGENIC CONTENT PRODUCT 0.45 kg C",
     '  BIOGENIC EXPORT C3 "Chips", 0.4 kg C\n',
     "the module is A1, A2 or A3"),
    ("BIOGENIC CONTENT PRODUCT 0.45 kg C",
     '  BIOGENIC EXPORT A1 "Sawdust", 0 kg C\n', "above zero"),
])
def test_biogenic_definition_errors(session, content, exports, message):
    refused(session.run(block(content=content, exports=False, extra=exports)),
            message)


def test_content_is_refused_with_biogenic_carbon_no(session):
    r = session.run(block(biogenic=False,
                          extra="  BIOGENIC CONTENT PRODUCT 0.45 kg C\n"))
    refused(r, "belong with BIOGENIC CARBON YES")


def test_a_model_built_right_passes(session, client):
    r = ready(session, client)
    said(r, "Biogenic carbon", "The balances close",
         "Declared content: 0.45 kg C in the product",
         "Co-product leaving A1: Sawdust, 0.05 kg C")
    epd = session.runtime.epd
    found = epd.biogenic
    assert found["passed"]
    assert found["uptake_a1_a3"] == pytest.approx(-STORED)
    assert found["expected_a1_a3"] == pytest.approx(-STORED)
    assert found["sum_a_to_c"] == pytest.approx(0.0, abs=1e-12)
    assert found["biogenic_co2"]["C3"] == pytest.approx(0.9 * STORED)
    assert found["biogenic_co2"]["D"] == 0
    # the methane of A3 is in the indicator, and out of the balance
    # (the methane, and the made-up biogenic share of the electricity)
    assert found["other_gases"]["A3"] == pytest.approx(
        0.0001 * BIO_CH4_FACTOR + 2 * 0.001)
    assert epd.results["A3"][EPD_BIOGENIC] != 0
    assert client.undisposed() == 0


def test_whole_tree_uptake_is_refused(session, client):
    """The uptake of the whole tree in the background data, not of the
    product."""
    build(session, client, uptake=3.0 * STORED)
    r = session.run(STEPS)
    refused(r, "biogenic carbon of the model does not balance",
            "The results are not kept")
    said(r, "Biogenic CO2 in A1 to A3 is", "but the declared content "
            "(0.45 kg C in the product) is -1.65",
         "takes up", "times the carbon that is in the product",
         "EN 16485, 6.3.4.2", "PCR 2019:14, Annex 2",
         "Biogenic CO2 does not balance over A to C")
    assert session.runtime.epd.results == {}
    refused(session.run("EPD DATA QUALITY"), "needs the results")


def test_a_co_product_without_its_carbon_is_refused(session, client):
    build(session, client, sawdust_out=0)
    r = session.run(STEPS)
    refused(r, "does not balance")
    said(r, "The difference is the carbon of the declared co-products: "
            "Sawdust (0.05 kg C)", "They leave A1 to A3 without their carbon",
         "factor of +1 whatever allocation", "EN 15804+A2, 6.4.3.2")


def test_a_co_product_without_its_carbon_and_not_declared(session, client):
    build(session, client, epd=block(exports=False), sawdust_out=0)
    r = session.run(STEPS)
    refused(r, "does not balance")
    said(r, "carbon in co-products leaves with +1 (declare them with "
            "BIOGENIC EXPORT)")


def test_a_missing_export_at_end_of_life_is_refused(session, client):
    """The 90% that leaves for reuse carries no carbon out."""
    build(session, client, c3_release=0)
    r = session.run(STEPS)
    refused(r, "does not balance")
    said(r, "Biogenic CO2 does not balance over A to C: the sum is -1.485",
         "The modules after A3 release 0.165 of the 1.65 taken up",
         "counts as an emission in the module where it leaves",
         "EN 16485, 6.3.4.5")
    assert "Biogenic CO2 in A1 to A3 is" not in r.text     # that part is right


def test_uptake_in_module_d_is_refused(session, client):
    build(session, client, d_uptake=-0.9 * STORED)
    r = session.run(STEPS)
    refused(r, "does not balance (1 problem")
    said(r, "Biogenic CO2 in module D is 1.485 kg CO2 eq., not zero",
         "offset by an equal emission")


def test_methane_does_not_break_the_balance(session, client):
    """GWP-biogenic over A to C is not zero when biogenic methane is
    emitted (PCR 2019:14, Annex 2, Table 6): the balance is of the CO2
    in the indicator, not of the indicator."""
    ready(session, client)
    epd = session.runtime.epd
    a_to_c = [c for c in epd.d["modules"] if c != "D"]
    indicator = sum(epd.results[c][EPD_BIOGENIC] for c in a_to_c)
    other = sum(epd.biogenic["other_gases"][c] for c in a_to_c)
    assert indicator == pytest.approx(other)
    assert other >= 0.0001 * BIO_CH4_FACTOR * 0.999
    assert epd.biogenic["passed"]


def test_packaging_carbon_stays_out_of_a1_a3_when_a5_is_not_declared(
        session, client):
    build(session, client, epd=block(
        content=f"BIOGENIC CONTENT PRODUCT {PRODUCT_C} kg C PACKAGING 0.1 "
                f"kg C"))
    r = session.run(STEPS)
    assert r.ok, f"{r.errors}\n{r.text}"
    assert session.runtime.epd.biogenic["expected_a1_a3"] == pytest.approx(
        -STORED)


def test_the_tolerances_are_named_values(session, client):
    # 0.3% too much uptake: inside the 0.5% allowed on the content, but
    # the A to C sum is then outside its 0.1%
    build(session, client, uptake=(PRODUCT_C * 1.003 + SAWDUST_C) * C)
    r = session.run(STEPS)
    refused(r, "does not balance (1 problem")
    said(r, "does not balance over A to C")
    assert "Biogenic CO2 in A1 to A3 is" not in r.text


def test_the_report_declares_the_content(session, client, tmp_path):
    ready(session, client)
    out = tmp_path / "r.csv"
    r = session.run(f'EPD DATA QUALITY\nEPD REPORT "{out.as_posix()}"')
    assert r.ok, r.errors
    head = {row[0]: row[1:] for row in read_csv(out) if len(row) > 1}
    assert head["Biogenic carbon in the product"] == ["Yes"]
    assert head["Biogenic carbon content in product (kg C)"] == ["0.45"]
    assert head["Biogenic carbon content in packaging (kg C)"] == ["0"]
    assert head["Biogenic carbon leaving A1 in co-products (kg C)"] == [
        "0.05", "Sawdust"]
    assert "C.2.4" in head["Biogenic carbon balance"][0]


def test_without_a_programme_the_checks_still_run(session, client):
    r = session.run(PARAMS + block(programme=False) + bridges(client)
                    + modules(c3_release=0) + STEPS.replace(
                        "EPD CHECK", 'EPD CHECK SKIP "test"'))
    refused(r, "does not balance")
    assert "PCR 2019:14" not in r.text and "EN 15804+A2, C.2.4" in r.text


def test_a_method_without_gwp_biogenic_cannot_be_checked(session, client):
    client.add_method("EN15804+A2 (no biogenic)", {
        **{f"Indicator {n:02d} ({c})": "u" for n, c in enumerate(
            programmes.get("IES").impact_indicator_codes)
           if c != "GWP-biogenic"},
        "Biogenic, uncoded": "kg CO2 eq.",
        **{f"Other {n:02d}": "u" for n in range(18)}})
    r = session.run(PARAMS + block().replace(
        EPD_METHOD, "EN15804+A2 (no biogenic)") + bridges(client)
        + modules() + STEPS)
    refused(r, "GWP-biogenic indicator", "could not be picked out")


# ── EPD SENSITIVITY ──────────────────────────────────────────

def test_group_sensitivity_by_hand(session, client, tmp_path):
    ready(session, client)
    out = tmp_path / "sens.csv"
    r = session.run(f'''
EPD SENSITIVITY BY 20% SAVE "{out.as_posix()}"
  GROUP "Electricity" VARY kiln_kwh
  GROUP "Transport" VARY road_tkm
END EPD SENSITIVITY''')
    assert r.ok, f"{r.errors}\n{r.text}"
    data = r.data[-1]["result"]
    assert data["calculations"] == 4          # A3 twice, A2 twice
    assert [g["modules"] for g in data["groups"]] == [["A3"], ["A2"]]
    rows = {row["indicator"]: row for row in data["table"]["A to C"]}
    gwp = rows[EPD_GWP]
    # by hand: steel 0.3 kg x 2.0, lorry 0.2 tkm x 0.12, electricity
    # 2 kWh x 0.25, C2 lorry 0.05 x 0.12, C3 electricity 0.02 x 0.25,
    # C4 landfill 0.1 x 0.05
    fixed = 0.3 * 2.0 + 0.05 * 0.12 + 0.02 * 0.25 + 0.1 * 0.05
    base = fixed + 0.2 * 0.12 + 2 * 0.25
    assert gwp["baseline"] == pytest.approx(base)
    assert gwp["Electricity -20%"] == pytest.approx(base - 0.2 * 2 * 0.25)
    assert gwp["Electricity +20%"] == pytest.approx(base + 0.2 * 2 * 0.25)
    assert gwp["Transport -20%"] == pytest.approx(base - 0.2 * 0.2 * 0.12)
    assert gwp["Transport +20%"] == pytest.approx(base + 0.2 * 0.2 * 0.12)
    # D is on its own, and nothing in it moves
    d = {row["indicator"]: row for row in data["table"]["D"]}[EPD_GWP]
    assert d["baseline"] == pytest.approx(-0.02 * 2.0)
    assert d["Electricity +20%"] == d["baseline"]
    said(r, "4 calculations", "Module D is shown on its own")
    # the file
    rows = read_csv(out)
    assert rows[0] == ["Indicator", "Unit", "Modules", "Baseline",
                       "Electricity -20%", "Electricity +20%",
                       "Transport -20%", "Transport +20%"]
    assert len(rows) == 1 + 38 * 2
    line = next(row for row in rows if row[0] == EPD_GWP
                and row[2] == "A to C")
    assert float(line[5]) == pytest.approx(base + 0.2 * 2 * 0.25)
    assert client.undisposed() == 0


def test_a_group_moves_its_parameters_together(session, client):
    ready(session, client)
    r = session.run('''
EPD SENSITIVITY BY 10%
  GROUP "Both" VARY kiln_kwh, road_tkm
END EPD SENSITIVITY''')
    assert r.ok, r.errors
    data = r.data[-1]["result"]
    assert data["groups"][0]["modules"] == ["A2", "A3"]
    assert data["calculations"] == 4
    gwp = {row["indicator"]: row
           for row in data["table"]["A to C"]}[EPD_GWP]
    assert gwp["Both +10%"] - gwp["baseline"] == pytest.approx(
        0.1 * (2 * 0.25 + 0.2 * 0.12))


def test_a_parameter_used_in_two_modules_moves_in_both(session, client):
    r = session.run("LET shared_kwh = 2\nLET road_tkm = 0.2\n" + block()
                    + bridges(client)
                    + modules(kwh="shared_kwh").replace(
                        'INPUT USE PROCESS "BRIDGE | Electricity | kWh", '
                        '0.02, kWh',
                        'INPUT USE PROCESS "BRIDGE | Electricity | kWh", '
                        'shared_kwh / 100, kWh') + STEPS)
    assert r.ok, f"{r.errors}\n{r.text}"
    r = session.run('EPD SENSITIVITY BY 50%\n  GROUP "E" VARY shared_kwh\n'
                    'END EPD SENSITIVITY')
    assert r.ok, r.errors
    data = r.data[-1]["result"]
    assert data["groups"][0]["modules"] == ["A3", "C3"]
    gwp = {row["indicator"]: row
           for row in data["table"]["A to C"]}[EPD_GWP]
    assert gwp["E +50%"] - gwp["baseline"] == pytest.approx(
        0.5 * (2 * 0.25 + 0.02 * 0.25))


def test_an_unknown_parameter_is_an_error_not_a_skipped_group(session,
                                                              client):
    ready(session, client)
    r = session.run('EPD SENSITIVITY BY 20%\n  GROUP "E" VARY kiln_kwh\n'
                    '  GROUP "Typo" VARY kiln_khw\nEND EPD SENSITIVITY')
    e = refused(r, "No module of the EPD holds the parameter kiln_khw",
                "Check the spelling")
    assert e["line"] == 3
    assert not [c for c in r.data if c["call"] == "epd_sensitivity"]


def test_a_calculated_parameter_cannot_be_varied(session, client):
    r = session.run("LET base_kwh = 1\nLET kiln_kwh = base_kwh * 2\n"
                    "LET road_tkm = 0.2\n" + block() + bridges(client)
                    + modules() + STEPS)
    assert r.ok, f"{r.errors}\n{r.text}"
    r = session.run('EPD SENSITIVITY BY 20%\n  GROUP "E" VARY kiln_kwh\n'
                    'END EPD SENSITIVITY')
    refused(r, "kiln_kwh is calculated from a formula", "Vary the "
            "parameters the formula uses")
    r = session.run('EPD SENSITIVITY BY 20%\n  GROUP "E" VARY base_kwh\n'
                    'END EPD SENSITIVITY')
    assert r.ok, r.errors
    assert r.data[-1]["result"]["groups"][0]["modules"] == ["A3"]


def test_sensitivity_needs_the_baseline(session, client):
    build(session, client)
    refused(session.run('EPD SENSITIVITY BY 20%\n  GROUP "E" VARY kiln_kwh\n'
                        'END EPD SENSITIVITY'),
            "needs the baseline results", "EPD CALCULATE")


@pytest.mark.parametrize("source,message", [
    ('EPD SENSITIVITY\n  GROUP "E" VARY a\nEND EPD SENSITIVITY',
     "needs BY and a percentage"),
    ('EPD SENSITIVITY BY 20%\nEND EPD SENSITIVITY', "has no GROUP line"),
    ('EPD SENSITIVITY BY 20%\n  GROUP "E"\nEND EPD SENSITIVITY',
     "needs VARY"),
    ('EPD SENSITIVITY BY 20%\n  GROUP "E" VARY "a"\nEND EPD SENSITIVITY',
     "plain words"),
    ('EPD SENSITIVITY BY 20%\n  GROUP "E" VARY a\n', "missing END EPD "
     "SENSITIVITY"),
    ('EPD SENSITIVITY BY 20%\n  GROUP "E" VARY a\nEND SENSITIVITY',
     "Expected END EPD SENSITIVITY"),
    ('EPD SENSITIVITY BY 20%\n  COLOUR\nEND EPD SENSITIVITY',
     "is not a line of an EPD SENSITIVITY block"),
    ('EPD SENSITIVITY BY 0%\n  GROUP "E" VARY a\nEND EPD SENSITIVITY',
     "above 0 and below 100"),
])
def test_sensitivity_parse_errors(source, message):
    with pytest.raises(ParseError, match=message):
        parse(source)


def test_a_group_named_twice(session, client):
    ready(session, client)
    refused(session.run('EPD SENSITIVITY BY 20%\n  GROUP "E" VARY kiln_kwh\n'
                        '  GROUP "E" VARY road_tkm\nEND EPD SENSITIVITY'),
            "The group 'E' is given twice")


# ── EPD EXPORT MODEL ─────────────────────────────────────────

def test_export_model(session, client, tmp_path):
    ready(session, client)
    out = tmp_path / "model.json"
    before = len([c for c in client.calls if c[0] in ("put", "delete")])
    r = session.run(f'EPD EXPORT MODEL "{out.as_posix()}"')
    assert r.ok, r.errors
    assert len([c for c in client.calls
                if c[0] in ("put", "delete")]) == before        # read only
    data = json.loads(out.read_text(encoding="utf-8"))
    meta = data["metadata"]
    assert meta["folder"] == FOLDER and meta["model"] == "Test timber"
    assert meta["epd"]["modules"] == ["A1", "A2", "A3", "C1", "C2", "C3",
                                      "C4", "D"]
    assert meta["system_count"] == 8
    names = {p["name"]: p for p in data["processes"].values()}
    assert "BRIDGE | Steel | kg" in names and "A3: Manufacturing" in names
    kiln = names["A3 | Kilning and planing"]
    assert kiln["category"] == f"{FOLDER}/A3"
    assert "Time: " in kiln["description"]         # the ratings
    ex = next(x for x in kiln["exchanges"]
              if x["flow_name"] and "Electricity" in x["flow_name"])
    assert set(ex) >= {"flow_name", "flow_id", "is_input", "amount",
                       "amount_formula", "unit", "flow_property",
                       "internal_id", "description", "dq_entry",
                       "base_uncertainty", "cost_value", "cost_formula",
                       "currency", "location", "default_provider",
                       "uncertainty", "is_quantitative_reference",
                       "is_avoided_product"}
    assert ex["default_provider"]["name"] == "BRIDGE | Electricity | kWh"
    assert ex["amount_formula"]
    assert any(p["name"] == "kiln_kwh" and p["value"] == 2
               for p in data["global_parameters"])
    assert any(f["name"] == BIO_UPTAKE for f in data["flows"].values())
    system = next(s for s in data["systems"]
                  if s["name"] == "A3: Manufacturing")
    assert system["analysis_groups"][0]["name"] == "A3"
    assert meta["parameterised_exchanges"] > 0
    said(r, "Model saved to", "8 product systems")


def test_export_model_needs_a_json_name(session, client):
    build(session, client)
    refused(session.run('EPD EXPORT MODEL "model.txt"'),
            "not a .json file name")


# ── several products in one study ────────────────────────────

THREE = '''
SUB product(pname, pfolder, kwh, uptake)
  EPD pname
    PROGRAMME "IES" GPI "5.1.0"
    PCR "Test PCR" VERSION "1.0"
    DATABASE "synthetic" VERSION "1"
    DECLARED UNIT 1, kg
    METHOD "__METHOD__"
    FOLDER pfolder
    MODULES A1, A2, A3, C1, C2, C3, C4, D
    BIOGENIC CARBON YES
    BIOGENIC CONTENT PRODUCT uptake kg C
  END EPD
__MODULES__
  EPD SYSTEMS
  EPD CHECK
  EPD CALCULATE
  EPD DATA QUALITY
  EPD REPORT pfolder + ".csv"
  EPD DQ TABLE "assessment.md"
  EPD CLOSE
END SUB
'''


def test_three_products_share_their_bridges(session, client, tmp_path,
                                            monkeypatch):
    monkeypatch.chdir(tmp_path)

    def one(n):
        carbon = 0.45 + 0.05 * n
        stored = carbon * C
        body = (modules(uptake="uptake * 44 / 12", sawdust_out=0,
                        c3_release=0.9 * stored, c4_release=0.1 * stored,
                        kwh="kwh")
                .replace('"Sawn timber"', 'pname + ", sawn"')
                .replace('"Timber, at gate"', 'pname + ", at gate"'))
        return body

    # the shared bridges are built once, in their own folder
    shared = bridges(client).replace(
        'END BRIDGE', '  FOLDER "00: Test shared/Bridges"\nEND BRIDGE')
    program = "LET road_tkm = 0.2\n" + shared + THREE.replace(
        "__METHOD__", EPD_METHOD).replace("__MODULES__", "__BODY__")
    # each product has its own carbon content, so the module bodies are
    # written out per product
    subs, calls = [], []
    for n, name in enumerate(("Timber one", "Timber two", "Timber three")):
        sub = THREE.replace("__METHOD__", EPD_METHOD).replace(
            "__MODULES__", one(n)).replace("SUB product(", f"SUB product{n}(")
        subs.append(sub)
        calls.append(f'product{n} "{name}", "00: Test {name}", '
                     f'{2 + n}, {0.45 + 0.05 * n}')
    r = session.run("LET road_tkm = 0.2\n" + shared + "\n".join(subs)
                    + "\n" + "\n".join(calls))
    assert r.ok, f"{r.errors}\n{r.text[-3000:]}"

    # one set of bridges, used by all three
    bridge_procs = [p for p in client.store["Process"].values()
                    if p.name.startswith("BRIDGE | ")]
    assert len(bridge_procs) == 4
    assert {p.category for p in bridge_procs} == {"00: Test shared/Bridges"}
    # three independent EPDs: each has its own module systems and report
    for name in ("Timber one", "Timber two", "Timber three"):
        assert (tmp_path / f"00: Test {name}.csv").exists()
        systems = [s for s in client.store["ProductSystem"].values()
                   if (s.category or "").startswith(f"00: Test {name}")]
        assert len(systems) == 8
    assert session.runtime.epd is None                     # EPD CLOSE
    # the assessment table covers all three, with the shared bridge once
    text = (tmp_path / "assessment.md").read_text(encoding="utf-8")
    assert "- A = Timber one" in text and "- C = Timber three" in text
    steel = [line for line in text.splitlines()
             if line.startswith("| BRIDGE / Steel / kg")]
    assert len(steel) == 1 and "| A, B, C |" in steel[0]
    assert "Good. Synthetic data, same region" in steel[0]
    assert client.undisposed() == 0


def test_a_rating_on_a_shared_bridge_counts_for_every_product(session,
                                                              client,
                                                              tmp_path):
    """The shared bridges start unrated: both products are refused. One
    EDIT PROCESS on the bridge then serves both."""
    shared = bridges(client, ratings="").replace(
        'END BRIDGE', '  FOLDER "00: Test shared/Bridges"\nEND BRIDGE')
    assert session.run(PARAMS + shared).ok
    names = ("Timber one", "Timber two")
    for name in names:
        r = session.run(block(name=name, folder=f"00: Test {name}")
                        + modules() + STEPS)
        assert r.ok, f"{r.errors}\n{r.text}"
        r = session.run("EPD DATA QUALITY")
        refused(r, "EPD DATA QUALITY found")
        said(r, "'BRIDGE | Steel | kg' is in the 80% coverage and has no "
                "RATING")
        assert session.run("EPD CLOSE").ok
    for bridge in ("Steel | kg", "Electricity | kWh", "Lorry | t*km",
                   "Landfill | kg"):
        r = session.run(f'EDIT PROCESS "BRIDGE | {bridge}"\n  {RATINGS}\n'
                        f'END EDIT')
        assert r.ok, r.errors
    for name in names:
        r = session.run(block(name=name, folder=f"00: Test {name}")
                        + STEPS + "EPD DATA QUALITY")
        assert r.ok, f"{r.errors}\n{r.text}"
        assert session.run("EPD CLOSE").ok


def test_the_bridge_rule_holds_across_products(session, client):
    """A second product cannot use a background process directly
    either: the bridge gate refuses that product alone."""
    shared = bridges(client).replace(
        'END BRIDGE', '  FOLDER "00: Test shared/Bridges"\nEND BRIDGE')
    assert session.run(PARAMS + shared).ok
    r = session.run(block(name="Timber one", folder="00: Test Timber one")
                    + modules() + STEPS + "EPD DATA QUALITY\nEPD CLOSE")
    assert r.ok, f"{r.errors}\n{r.text}"
    r = session.run(block(name="Timber two", folder="00: Test Timber two")
                    + modules())
    assert r.ok, f"{r.errors}\n{r.text}"
    two = next(p for p in client.store["Process"].values()
               if p.name == "A1 | Forestry and sawing"
               and p.category.startswith("00: Test Timber two"))
    two.name = "A1 | Forestry and sawing (two)"
    use_directly(client, two.name, STEEL, 0.5)
    two.name = "A1 | Forestry and sawing"
    refused(session.run(STEPS), "EPD CALCULATE refused", "no bridge")


# ── dry run and help ─────────────────────────────────────────

def test_dry_run_knows_the_new_commands():
    s = Session(offline=True)
    r = s.run('EPD SENSITIVITY BY 20%\n  GROUP "E" VARY a\n'
              'END EPD SENSITIVITY\nEPD DQ SHEET "x.csv"', dry_run=True)
    messages = " ".join(e["message"] for e in r.errors)
    assert "EPD SENSITIVITY needs an EPD" in messages
    assert "EPD DQ SHEET needs an EPD" in messages


def test_help_covers_the_toolkit(session):
    text = session.run("HELP EPD").text
    for word in ("RATING", "EPD DQ SHEET", "EPD DQ TABLE", "EPD SENSITIVITY",
                 "EPD EXPORT MODEL", "BIOGENIC CONTENT", "EPD SAVE"):
        assert word in text
    assert "Very good, Good, Fair, Poor and Very poor" in session.run(
        "HELP RATING").text


# ── what the multi-product work turned up ────────────────────

def test_a_sub_variable_used_as_an_amount_is_a_value(session, client):
    """A SUB's parameter is not an openLCA parameter: used as an amount
    it is written as its value, so the SUB can run again with another
    one and no formula points at a name openLCA does not know."""
    r = session.run(f'''
CONFIRM DELETE ON
SET PROCESS FOLDER "00: Test"
SET FLOW FOLDER "00: Test"
LET shared = 3
BRIDGE "electricity", kWh
  PROVIDER "{ELECTRICITY}" LOCATION "GB"
END BRIDGE
BRIDGE "steel", kg
  PROVIDER "{STEEL}"
END BRIDGE
SUB build_one(pname, kwh)
  MAKE PROCESS pname
    OUTPUT MAKE FLOW pname, 1, kg, PRODUCT
    INPUT USE PROCESS "BRIDGE | electricity | kWh", kwh * 2, kWh
    INPUT USE PROCESS "BRIDGE | steel | kg", shared, kg
  END PROCESS
END SUB
build_one "Thing one", 2
build_one "Thing two", 5
''')
    assert r.ok, f"{r.errors}\n{r.text}"
    assert not client.by_name(o.Parameter, "kwh")
    assert client.by_name(o.Parameter, "shared")
    for name, kwh in (("Thing one", 2), ("Thing two", 5)):
        proc = client.by_name(o.Process, name)[0]
        elec = next(ex for ex in proc.exchanges
                    if ex.flow and "electricity" in client._flow_name(
                        ex.flow.id))
        values = {p.name: p.value for p in proc.parameters or []}
        amount = values.get(elec.amount_formula, elec.amount)
        if elec.amount_formula and elec.amount_formula not in values:
            assert "kwh" not in elec.amount_formula
            amount = eval(elec.amount_formula)        # numbers only
        assert amount == pytest.approx(kwh * 2)
        steel = next(ex for ex in proc.exchanges
                     if ex.flow and "steel" in client._flow_name(ex.flow.id))
        assert steel.amount_formula == "shared"


def test_a_system_is_found_by_its_process_not_its_name(session, client):
    """Two processes with the same name in two folders each get their
    own product system when each system has its own folder."""
    r = session.run(f'''
SET FLOW FOLDER "00: Test"
SET PROCESS FOLDER "00: Test/one"
BRIDGE "steel", kg
  PROVIDER "{STEEL}"
END BRIDGE
MAKE PROCESS "Same name"
  OUTPUT MAKE FLOW "Product one", 1, kg, PRODUCT
  INPUT USE PROCESS "BRIDGE | steel | kg", 1, kg
END PROCESS
SET PROCESS FOLDER "00: Test/two"
MAKE PROCESS "Same name"
  OUTPUT MAKE FLOW "Product two", 1, kg, PRODUCT
  INPUT USE PROCESS "BRIDGE | steel | kg", 3, kg
END PROCESS''')
    assert r.ok, f"{r.errors}\n{r.text}"
    one, two = sorted(client.by_name(o.Process, "Same name"),
                      key=lambda p: p.category)
    engine = session.engine
    made = engine.create_product_system(one.id, category="00: Test/one")
    assert made.get("system_id") and not made.get("already_existed")
    again = engine.create_product_system(one.id, category="00: Test/one")
    assert again["already_existed"] and again["system_id"] == made["system_id"]
    other = engine.create_product_system(two.id, category="00: Test/two")
    assert other["system_id"] != made["system_id"]
    assert not other.get("already_existed")
    assert engine.system_for_process(one.id)["id"] == made["system_id"]
    assert engine.system_for_process(two.id)["id"] == other["system_id"]


def test_a_same_named_system_of_another_process_is_not_reused(session,
                                                              client):
    r = session.run(f'''
SET FLOW FOLDER "00: Test"
SET PROCESS FOLDER "00: Test/one"
BRIDGE "steel", kg
  PROVIDER "{STEEL}"
END BRIDGE
MAKE PROCESS "Same name"
  OUTPUT MAKE FLOW "Product one", 1, kg, PRODUCT
  INPUT USE PROCESS "BRIDGE | steel | kg", 1, kg
END PROCESS
SET PROCESS FOLDER "00: Test/two"
MAKE PROCESS "Same name"
  OUTPUT MAKE FLOW "Product two", 1, kg, PRODUCT
  INPUT USE PROCESS "BRIDGE | steel | kg", 3, kg
END PROCESS''')
    assert r.ok, r.errors
    one, two = sorted(client.by_name(o.Process, "Same name"),
                      key=lambda p: p.category)
    engine = session.engine
    assert engine.create_product_system(one.id).get("system_id")
    refusal = engine.create_product_system(two.id)
    assert "built from another process of that name" in refusal["error"]
    assert "FOLDER" in refusal["hint"]
    assert len(client.store["ProductSystem"]) == 1


# ── A.5.4: core reference years and the database of large later steps ─

def test_every_a3_process_has_its_reference_year_listed(session, client):
    ready(session, client)
    r = session.run("EPD DATA QUALITY")
    assert r.ok, r.text
    dq = next(x["result"] for x in r.data if x["call"] == "epd_data_quality")
    assert {"process": "A3 | Kilning and planing", "year": 2025} in \
        dq["a3_years"]
    assert "Reference years of the other A3 (core) processes" in r.text


def test_a_core_process_without_a_year_is_refused(session, client):
    ready(session, client)
    proc = next(p for p in client.store["Process"].values()
                if p.name == "A3 | Kilning and planing")
    from olcabasic.workflows.epd import TAG_PREFIX
    proc.tags = [t for t in proc.tags if not t.startswith(TAG_PREFIX + ":year")]
    session.engine.clear_caches()
    r = session.run("EPD DATA QUALITY")
    assert not r.ok
    assert "is an A3 (core) process and its DATA line has no YEAR" in r.text


def test_a_large_step_after_a3_has_its_database_listed(session, client):
    r = session.run(PARAMS + block() + bridges(client)
                    + modules().replace('"BRIDGE | Electricity | kWh", 0.02',
                                        '"BRIDGE | Electricity | kWh", 20'))
    assert r.ok, r.text
    assert session.run(STEPS).ok
    r = session.run("EPD DATA QUALITY")
    dq = next(x["result"] for x in r.data if x["call"] == "epd_data_quality")
    late = {d["process"]: d for d in dq["downstream"]}
    assert "C3 | Chipping for reuse" in late or \
        "BRIDGE | Electricity | kWh" in late, dq["downstream"]
    row = next(iter(late.values()))
    assert row["source"] and row["share_of_gwp"] > 10
    assert "Processes after A3 above 10%" in r.text
