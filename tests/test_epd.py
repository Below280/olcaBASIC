"""
The EPD workflow (EN 15804+A2) and the International EPD System profile.

Everything runs against the fake client with a synthetic EN 15804+A2
method: 38 categories with made-up names. No text of a standard or of a
programme's instructions is used here, only clause numbers.
"""

import csv
import datetime

import pytest

from fake_client import (
    ELECTRICITY, EPD_GWP, EPD_METHOD, EPD_SHORT_METHOD, LANDFILL, STEEL,
    TRANSPORT, add_epd_methods, seed_ecoinvent_like,
)
from olcabasic import Session, templates
from olcabasic.parser import ParseError, parse
from olcabasic.workflows import epd as epd_module
from olcabasic.workflows import programmes
from olcabasic.workflows.epd import (
    EpdWorkflow, TYPE_GATE, TYPE_GATE_CD, TYPE_GATE_OPTIONS, TYPE_GRAVE,
    TYPE_OPTIONS_CD, check_definition, epd_type,
)
from olcabasic.workflows.programmes import ies

FOLDER = "00: Test EPD"
FULL = "A1, A2, A3, C1, C2, C3, C4, D"


@pytest.fixture
def client():
    from fake_client import nothing_left_open
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


def epd_block(modules=FULL, programme=True, extra="", unit="DECLARED UNIT 1, kg",
              method=EPD_METHOD, biogenic="NO", name="Test block"):
    head = ('  PROGRAMME "IES" GPI "5.1.0"\n  PCR "Test PCR" VERSION "1.0"\n'
            '  DATABASE "synthetic" VERSION "1"\n') if programme else ""
    return (f'EPD "{name}"\n{head}  {unit}\n  METHOD "{method}"\n'
            f'  FOLDER "{FOLDER}"\n  MODULES {modules}\n'
            f'  BIOGENIC CARBON {biogenic}\n{extra}END EPD\n')


SECONDARY = 'DATA SECONDARY SOURCE "Database" PROVIDER "synthetic 1" YEAR 2024'
PRIMARY = 'DATA PRIMARY SOURCE "Collected" PROVIDER "EPD owner" YEAR 2025'

# The three representativeness ratings every dataset in the 80% coverage
# has to carry (0.4.0). The reason holds a comma on purpose.
RATINGS = (
    'RATING GEOGRAPHY "Good" REASON "Synthetic data, same region"\n'
    '  RATING TECHNOLOGY "Very good" REASON "Synthetic data, same '
    'technology"\n'
    '  RATING TIME "Fair" REASON "Synthetic data, nine years old"')


def bridges(client, electricity="RESIDUAL", steel_data=SECONDARY,
            location_based=True, country="GB", region=""):
    gb = uid(client, ELECTRICITY, "GB")
    de = uid(client, ELECTRICITY, "DE")
    second = (f'  LOCATION BASED PROVIDER "{de}"\n'
              if location_based and electricity != "CONSUMPTION" else "")
    reg = f'  REGION "{region}"\n' if region else ""
    return f'''
BRIDGE "Steel", kg
  PROVIDER "{STEEL}"
  {steel_data}
  {RATINGS}
END BRIDGE
BRIDGE "Electricity", kWh
  PROVIDER "{gb}"
  ELECTRICITY {electricity}
  COUNTRY "{country}"
{reg}  ENERGY SOURCE "Test mix"
{second}  DATA PRIMARY SOURCE "Database" PROVIDER "synthetic 1" YEAR 2024
  {RATINGS}
END BRIDGE
BRIDGE "Lorry", t*km
  PROVIDER "{TRANSPORT}"
  DATA PRIMARY SOURCE "Database" PROVIDER "synthetic 1" YEAR 2024
  {RATINGS}
END BRIDGE
BRIDGE "Landfill", kg WASTE
  PROVIDER "{LANDFILL}"
  {SECONDARY}
  {RATINGS}
END BRIDGE
'''


MODULES = f'''
MODULE A1
  MAKE PROCESS "Steel supply"
    {SECONDARY}
    OUTPUT MAKE FLOW "Steel, supplied", 1.1, kg, PRODUCT
    INPUT USE PROCESS "BRIDGE | Steel | kg", 1.1, kg
  END PROCESS
  TOTAL "Raw material supply"
END MODULE
MODULE A2
  MAKE PROCESS "Transport to factory"
    {PRIMARY}
    OUTPUT MAKE FLOW "Transport, done", 1, kg, PRODUCT
    INPUT USE PROCESS "BRIDGE | Lorry | t*km", 0.2, t*km
  END PROCESS
  TOTAL "Transport"
END MODULE
MODULE A3
  MAKE PROCESS "Manufacturing"
    {PRIMARY}
    OUTPUT MAKE FLOW "Block, at gate", 1, kg, PRODUCT
    INPUT USE PROCESS "BRIDGE | Electricity | kWh", 2, kWh
  END PROCESS
  TOTAL "Manufacturing"
END MODULE
MODULE C1
  TOTAL "Deconstruction"
END MODULE
MODULE C2
  MAKE PROCESS "Transport to waste processing"
    {SECONDARY}
    OUTPUT MAKE FLOW "Waste transport, done", 1, kg, PRODUCT
    INPUT USE PROCESS "BRIDGE | Lorry | t*km", 0.05, t*km
  END PROCESS
  TOTAL "Transport"
END MODULE
MODULE C3
  TOTAL "Waste processing"
END MODULE
MODULE C4
  MAKE PROCESS "Landfilling"
    {SECONDARY}
    OUTPUT MAKE FLOW "Disposal, done", 1, kg, PRODUCT
    OUTPUT USE PROCESS "BRIDGE | Landfill | kg", 0.2, kg
  END PROCESS
  TOTAL "Disposal"
END MODULE
MODULE D
  NET FLOW "Steel scrap", 0.8, kg QUALITY 80%
  MAKE PROCESS "Avoided steel"
    {SECONDARY}
    OUTPUT MAKE FLOW "Credit", 1, kg, PRODUCT
    INPUT USE PROCESS "BRIDGE | Steel | kg", -0.5, kg
  END PROCESS
  TOTAL "Benefits beyond the system boundary"
END MODULE
'''


def build(session, client, **kw):
    """Define the EPD, the bridges and every module."""
    r = session.run(epd_block() + bridges(client, **kw) + MODULES)
    assert r.ok, r.errors
    return r


def amount_of(process, ex):
    """The amount of an exchange. A number in a PROCESS block becomes a
    process parameter, and the exchange holds its name as a formula."""
    values = {p.name: p.value for p in process.parameters or []}
    return values.get(ex.amount_formula, ex.amount)


def refused(result, *words):
    assert not result.ok, result.text
    text = (result.errors[0]["message"] + " " + result.errors[0]["hint"])
    for word in words:
        assert word in text, f"{word!r} not in: {text}"
    return result.errors[0]


def read_report(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def table(rows, title):
    """The indicator rows under a section title, as {indicator: {column: value}}."""
    start = next(i for i, r in enumerate(rows) if r and r[0] == title)
    header = rows[start + 1]
    out = {}
    for r in rows[start + 2:]:
        if not r:
            break
        out[r[0]] = {col: float(v) for col, v in zip(header[2:], r[2:])}
    return out


# ── the EPD type ─────────────────────────────────────────────

@pytest.mark.parametrize("modules, exempt, expected", [
    ("A1 A2 A3 C1 C2 C3 C4 D", False, TYPE_GATE_CD),
    ("A1 A2 A3 A4 C1 C2 C3 C4 D", False, TYPE_OPTIONS_CD),
    ("A1 A2 A3 B1 C1 C2 C3 C4 D", False, TYPE_OPTIONS_CD),
    ("A1 A2 A3 A4 A5 B1 B2 B3 B4 B5 B6 B7 C1 C2 C3 C4 D", False, TYPE_GRAVE),
    ("A1 A2 A3", True, TYPE_GATE),
    ("A1 A2 A3 A5", True, TYPE_GATE_OPTIONS),
])
def test_epd_type_follows_from_the_modules(modules, exempt, expected):
    assert epd_type(modules.split(), exempt) == expected


# ── the EPD block: refusals ──────────────────────────────────

EXEMPT = ('  EXEMPT C AND D\n    INTEGRATED "Cast into the structure"\n'
          '    NOT IDENTIFIABLE "Chemically transformed"\n'
          '    END OF LIFE SCENARIOS "See the EPD of the structure"\n'
          '  END EXEMPT\n')


def test_a_complete_block_is_accepted(session):
    r = session.run(epd_block())
    assert r.ok, r.errors
    assert TYPE_GATE_CD in r.text
    assert "38 categories" in r.text
    assert session.runtime.epd.name == "Test block"
    assert session.runtime.epd.gwp_indicator == EPD_GWP


def test_the_folder_tree_holds_declared_modules_and_bridges_only(session):
    session.run(epd_block())
    pending = session.runtime.pending_folders
    for code in FULL.split(", "):
        assert f"{FOLDER}/{code}" in pending
    assert f"{FOLDER}/Bridges" in pending
    assert f"{FOLDER}/A4" not in pending and f"{FOLDER}/B1" not in pending


@pytest.mark.parametrize("line, label", [
    ("  DECLARED UNIT 1, kg\n", "DECLARED UNIT"),
    (f'  METHOD "{EPD_METHOD}"\n', "METHOD"),
    (f'  FOLDER "{FOLDER}"\n', "FOLDER"),
    (f"  MODULES {FULL}\n", "MODULES"),
    ("  BIOGENIC CARBON NO\n", "BIOGENIC CARBON"),
])
def test_each_required_line_is_required(session, line, label):
    block = epd_block()
    assert line in block
    err = refused(session.run(block.replace(line, "")), label)
    assert err["line"] == 1
    assert session.runtime.epd is None


def test_modules_without_c_and_d_are_refused(session):
    err = refused(session.run(epd_block(modules="A1, A2, A3")),
                  "C1 to C4 and D", "clause 5.2", "EXEMPT C AND D")
    assert err["line"] == 8          # the MODULES line


@pytest.mark.parametrize("modules", [
    "A1, A2, A3, C1, C2, C3, C4",        # no D
    "A1, A2, A3, D",                     # D alone
    "A1, A2, A3, C1, C2, D",             # part of C
])
def test_c_and_d_are_all_or_nothing(session, modules):
    refused(session.run(epd_block(modules=modules)),
            "together or not at all", "clause 5.2")


def test_a1_to_a3_are_always_declared(session):
    refused(session.run(epd_block(modules="A1, A3, C1, C2, C3, C4, D")),
            "A2", "clause 5.2")


def test_an_unknown_module_is_refused(session):
    refused(session.run(epd_block(modules="A1, A2, A3, A9, C1, C2, C3, C4, D")),
            "'A9' is not a module")


def test_a_module_named_twice_is_refused(session):
    refused(session.run(epd_block(modules="A1, A1, A2, A3, C1, C2, C3, C4, D")),
            "more than once")


def test_the_exemption_is_accepted_with_all_three_statements(session):
    r = session.run(epd_block(modules="A1, A2, A3", extra=EXEMPT))
    assert r.ok, r.errors
    assert TYPE_GATE in r.text
    assert session.runtime.epd.d["exempt"]["integrated"] == "Cast into the structure"


@pytest.mark.parametrize("dropped, label", [
    ('    INTEGRATED "Cast into the structure"\n', "INTEGRATED"),
    ('    NOT IDENTIFIABLE "Chemically transformed"\n', "NOT IDENTIFIABLE"),
    ('    END OF LIFE SCENARIOS "See the EPD of the structure"\n',
     "END OF LIFE SCENARIOS"),
])
def test_the_exemption_needs_every_statement(session, dropped, label):
    refused(session.run(epd_block(modules="A1, A2, A3",
                                  extra=EXEMPT.replace(dropped, ""))),
            label, "clause 5.2")


def test_an_empty_justification_is_refused(session):
    extra = EXEMPT.replace('"Cast into the structure"', '"  "')
    refused(session.run(epd_block(modules="A1, A2, A3", extra=extra)),
            "INTEGRATED")


def test_the_exemption_is_refused_with_biogenic_carbon(session):
    err = refused(session.run(epd_block(modules="A1, A2, A3", extra=EXEMPT,
                                        biogenic="YES")),
                  "biogenic carbon", "clause 5.2")
    assert err["line"] == 9          # the BIOGENIC CARBON line


def test_the_exemption_with_c_and_d_declared_is_refused(session):
    refused(session.run(epd_block(extra=EXEMPT)), "EXEMPT C AND D", "together")


def test_the_exemption_with_use_stage_modules_is_refused(session):
    refused(session.run(epd_block(modules="A1, A2, A3, B1", extra=EXEMPT)),
            "B1")


def test_the_exemption_with_a4_is_cradle_to_gate_with_options(session):
    r = session.run(epd_block(modules="A1, A2, A3, A4", extra=EXEMPT))
    assert r.ok and TYPE_GATE_OPTIONS in r.text


def test_exempt_block_must_cover_c_and_d_together():
    with pytest.raises(ParseError, match="EXEMPT C AND D"):
        parse(epd_block(extra='  EXEMPT C\n  END EXEMPT\n'))


def test_biogenic_carbon_needs_yes_or_no():
    with pytest.raises(ParseError, match="YES or NO"):
        parse(epd_block(biogenic="MAYBE"))


def test_functional_unit_is_refused_for_cradle_to_gate(session):
    refused(session.run(epd_block(unit="FUNCTIONAL UNIT 1, kg")),
            "FUNCTIONAL UNIT", "clause 5.2", "DECLARED UNIT 1, kg")


def test_functional_unit_is_refused_for_the_exempt_cradle_to_gate(session):
    refused(session.run(epd_block(modules="A1, A2, A3", extra=EXEMPT,
                                  unit="FUNCTIONAL UNIT 1, kg")),
            "FUNCTIONAL UNIT")


def test_functional_unit_is_allowed_with_options(session):
    r = session.run(epd_block(modules="A1, A2, A3, A4, C1, C2, C3, C4, D",
                              unit="FUNCTIONAL UNIT 1, kg"))
    assert r.ok, r.errors
    assert "Functional unit: 1 kg" in r.text


def test_the_unit_amount_must_be_positive(session):
    refused(session.run(epd_block(unit="DECLARED UNIT 0, kg")), "above zero")


# ── the method ───────────────────────────────────────────────

def test_the_short_method_is_refused_by_name(session):
    err = refused(session.run(epd_block(method=EPD_SHORT_METHOD)),
                  "not the EPD method", EPD_METHOD)
    assert err["line"] == 6


def test_a_method_that_is_not_en15804_is_refused(session):
    refused(session.run(epd_block(method="EF v3.1")),
            "not an EN 15804+A2 method")


def test_a_method_with_the_wrong_number_of_categories_is_refused(session, client):
    client.add_method("EN15804+A2 (test copy)",
                      {f"Category {n}": "unit" for n in range(20)})
    refused(session.run(epd_block(method="EN15804+A2 (test copy)")),
            "has 20 impact categories", "38", "CATEGORIES 20")


def test_the_expected_number_of_categories_can_be_stated(session, client):
    client.add_method("EN15804+A2 (test copy)",
                      {f"Category {n}": "unit" for n in range(20)})
    block = epd_block(method="EN15804+A2 (test copy)", programme=False)
    block = block.replace('(test copy)"', '(test copy)" CATEGORIES 20')
    r = session.run(block)
    assert r.ok, r.errors
    assert "20 categories" in r.text


def test_stating_a_count_does_not_let_the_wrong_size_through(session):
    block = epd_block().replace(f'"{EPD_METHOD}"', f'"{EPD_METHOD}" CATEGORIES 20')
    refused(session.run(block), "has 38 impact categories", "20")


def test_a_method_that_is_not_installed_is_refused(session):
    refused(session.run(epd_block(method="EN15804+A2 (EF 4.0)")), "EN15804")


def test_part_of_the_method_name_is_not_enough(session):
    refused(session.run(epd_block(method="EN15804+A2")), "full name")


def test_gwp_indicator_must_be_a_category_of_the_method(session):
    refused(session.run(epd_block(extra='  GWP INDICATOR "Nonsense"\n')),
            "GWP INDICATOR")


# ── programme and cut-offs ───────────────────────────────────

def test_an_unknown_programme_is_refused(session):
    block = epd_block().replace('"IES"', '"Acme EPD"')
    refused(session.run(block), "no programme profile", '"IES"')


def test_another_gpi_version_is_refused(session):
    block = epd_block().replace('GPI "5.1.0"', 'GPI "4.0"')
    refused(session.run(block), "5.1.0", "4.0")


def test_the_programme_can_be_named_in_full(session):
    block = epd_block().replace('"IES"', '"International EPD System"')
    r = session.run(block)
    assert r.ok and session.runtime.epd.profile is ies.PROFILE


def test_without_a_programme_only_the_standard_applies(session):
    r = session.run(epd_block(programme=False))
    assert r.ok
    assert session.runtime.epd.profile is None
    assert "no PROGRAMME line" in r.text


def test_cutoffs_are_recorded(session):
    r = session.run(epd_block(extra='  CUTOFF A3 "Lubricants", 0.2%\n'
                                    '  CUTOFF A3 "Labels", 0.1%\n'))
    assert r.ok
    assert [c["item"] for c in session.runtime.epd.d["cutoffs"]] == [
        "Lubricants", "Labels"]


def test_cutoffs_above_the_limit_are_refused(session):
    extra = ('  CUTOFF A3 "Lubricants", 3%\n  CUTOFF A1 "Additive", 4%\n'
             '  CUTOFF A3 "Packaging film", 2.5%\n')
    err = refused(session.run(epd_block(extra=extra)),
                  "A3 add up to 5.5%", "5%", "A.3.3")
    assert err["line"] == 10         # the first A3 cut-off


def test_the_cutoff_limit_is_a_programme_rule(session):
    extra = '  CUTOFF A3 "Lubricants", 6%\n'
    assert session.run(epd_block(extra=extra, programme=False)).ok


def test_a_cutoff_for_an_undeclared_module_is_refused(session):
    refused(session.run(epd_block(extra='  CUTOFF A4 "Pallets", 1%\n')),
            "A4", "not in MODULES")


def test_every_threshold_is_a_named_value_of_the_profile():
    p = programmes.get("IES")
    assert (p.cutoff_limit_pct, p.proxy_limit_pct) == (5.0, 10.0)
    assert (p.primary_max_age_years, p.secondary_max_age_years) == (5, 10)
    assert (p.gwp_row_threshold_pct, p.primary_share_cap_pct,
            p.coverage_pct) == (10.0, 90.0, 80.0)
    assert p.subnational_countries == {"AU", "BR", "CA", "CN", "IN", "US"}
    assert p.electricity_hierarchy == ("CONTRACT", "RESIDUAL", "CONSUMPTION")
    assert p.module_d_in_totals is False
    assert set(p.clauses.values()) <= {
        "A.3.3", "A.5.1", "A.5.2", "A.5.3", "A.5.4", "A.6.2", "A.7.1",
        "A.7.5", "A.8"}


def test_the_workflow_holds_no_programme_numbers():
    """The limits live in the profile: the EPD workflow may not repeat
    them as literals."""
    import inspect
    import re
    source = inspect.getsource(epd_module)
    code = "\n".join(line.split("#")[0] for line in source.split("\n"))
    code = re.sub(r'""".*?"""', "", code, flags=re.S)
    for literal in ("5.0", "10.0", "90.0", "80.0"):
        assert not re.search(rf"[<>=]=?\s*{re.escape(literal)}\b", code), literal


# ── MODULE blocks ────────────────────────────────────────────

def test_module_needs_an_epd(session):
    refused(session.run('MODULE A1\n  TOTAL "x"\nEND MODULE'),
            "needs an EPD", "EPD \"name\"")


def test_an_undeclared_module_is_refused(session):
    session.run(epd_block())
    refused(session.run('MODULE A4\n  TOTAL "Transport to site"\nEND MODULE'),
            "MODULE A4 is not declared")


def test_a_module_needs_a_total(session):
    session.run(epd_block())
    refused(session.run("MODULE A1\nEND MODULE"), "no TOTAL line")


def test_names_get_their_prefixes(session, client):
    build(session, client)
    names = {p.name: p.category for p in client.store["Process"].values()
             if (p.category or "").startswith(FOLDER)}
    assert names["A1 | Steel supply"] == f"{FOLDER}/A1"
    assert names["A1: Raw material supply"] == f"{FOLDER}/A1"
    assert names["A3 | Manufacturing"] == f"{FOLDER}/A3"
    assert names["D: Benefits beyond the system boundary"] == f"{FOLDER}/D"
    assert names["BRIDGE | Steel | kg"] == f"{FOLDER}/Bridges"


def test_a_typed_prefix_is_refused(session, client):
    session.run(epd_block() + bridges(client))
    r = session.run(f'''MODULE A1
  MAKE PROCESS "A1: Steel supply"
    {SECONDARY}
    OUTPUT MAKE FLOW "Steel, supplied", 1, kg, PRODUCT
  END PROCESS
  TOTAL "Raw material supply"
END MODULE''')
    refused(r, "already carries a module prefix", "A1 | Steel supply")


def test_folder_is_not_used_inside_a_module(session, client):
    session.run(epd_block() + bridges(client))
    r = session.run(f'''MODULE A1
  MAKE PROCESS "Steel supply"
    FOLDER "Somewhere else"
    {SECONDARY}
    OUTPUT MAKE FLOW "Steel, supplied", 1, kg, PRODUCT
  END PROCESS
  TOTAL "Raw material supply"
END MODULE''')
    refused(r, "FOLDER is not used inside MODULE A1")


def test_a_background_process_used_directly_is_an_error(session, client):
    session.run(epd_block() + bridges(client))
    r = session.run(f'''MODULE A1
  MAKE PROCESS "Steel supply"
    {SECONDARY}
    OUTPUT MAKE FLOW "Steel, supplied", 1, kg, PRODUCT
    INPUT USE PROCESS "{STEEL}", 1, kg
  END PROCESS
  TOTAL "Raw material supply"
END MODULE''')
    err = refused(r, "background process", "BRIDGE")
    assert err["line"] == 5
    assert not any(p.name == "A1 | Steel supply"
                   for p in client.store["Process"].values())


def test_a_process_of_the_epd_can_be_used(session, client):
    session.run(epd_block() + bridges(client))
    r = session.run(f'''MODULE A1
  MAKE PROCESS "Steel supply"
    {SECONDARY}
    OUTPUT MAKE FLOW "Steel, supplied", 2, kg, PRODUCT
    INPUT USE PROCESS "BRIDGE | Steel | kg", 2, kg
  END PROCESS
  MAKE PROCESS "Steel cutting"
    {SECONDARY}
    OUTPUT MAKE FLOW "Steel, cut", 1.9, kg, PRODUCT
    INPUT USE PROCESS "A1 | Steel supply", 2, kg
  END PROCESS
  TOTAL "Raw material supply"
END MODULE''')
    assert r.ok, r.errors
    # the supply feeds the cutting, so only the cutting is in the total
    assert "not added to the total" in r.text and "A1 | Steel supply" in r.text
    total = next(p for p in client.store["Process"].values()
                 if p.name == "A1: Raw material supply")
    inputs = [ex for ex in total.exchanges if not ex.is_quantitative_reference]
    assert [ex.flow.name for ex in inputs] == ["Steel, cut"]
    assert amount_of(total, inputs[0]) == pytest.approx(1.9)


def test_using_another_modules_process_is_a_warning(session, client):
    build(session, client)
    session.run('CONFIRM DELETE ON\nDELETE PROCESS "A3: Manufacturing"\n'
                'DELETE PROCESS "A3 | Manufacturing"')
    r = session.run(f'''MODULE A3
  MAKE PROCESS "Manufacturing"
    {PRIMARY}
    OUTPUT MAKE FLOW "Block, at gate", 1, kg, PRODUCT
    INPUT USE PROCESS "A1 | Steel supply", 1.1, kg
  END PROCESS
  TOTAL "Manufacturing"
END MODULE''')
    assert r.ok, r.errors
    assert any("counted in both modules" in w["message"] for w in r.warnings)


def test_the_total_has_the_declared_unit_as_its_product(session, client):
    build(session, client)
    total = next(p for p in client.store["Process"].values()
                 if p.name == "A1: Raw material supply")
    qref = next(ex for ex in total.exchanges if ex.is_quantitative_reference)
    assert (amount_of(total, qref), qref.unit.name) == (1.0, "kg")
    inputs = [ex for ex in total.exchanges if not ex.is_quantitative_reference]
    assert len(inputs) == 1
    assert amount_of(total, inputs[0]) == pytest.approx(1.1)
    assert inputs[0].default_provider.name == "A1 | Steel supply"


def test_total_as_an_intermediate_product(session, client):
    session.run(epd_block() + bridges(client))
    r = session.run(f'''MODULE A1
  MAKE PROCESS "Steel supply"
    {SECONDARY}
    OUTPUT MAKE FLOW "Steel, supplied", 1.1, kg, PRODUCT
    INPUT USE PROCESS "BRIDGE | Steel | kg", 1.1, kg
  END PROCESS
  TOTAL "Raw material supply" AS "Materials for one block", 2, kg
END MODULE''')
    assert r.ok, r.errors
    total = next(p for p in client.store["Process"].values()
                 if p.name == "A1: Raw material supply")
    qref = next(ex for ex in total.exchanges if ex.is_quantitative_reference)
    assert (qref.flow.name, amount_of(total, qref)) == (
        "Materials for one block", 2.0)


def test_a_total_keeps_a_formula_on_a_global_variable(session, client):
    session.run(epd_block() + bridges(client))
    r = session.run(f'''LET steel_mass = 1.1
MODULE A1
  MAKE PROCESS "Steel supply"
    {SECONDARY}
    OUTPUT MAKE FLOW "Steel, supplied", steel_mass, kg, PRODUCT
    INPUT USE PROCESS "BRIDGE | Steel | kg", steel_mass, kg
  END PROCESS
  TOTAL "Raw material supply"
END MODULE''')
    assert r.ok, r.errors
    total = next(p for p in client.store["Process"].values()
                 if p.name == "A1: Raw material supply")
    link = next(ex for ex in total.exchanges if not ex.is_quantitative_reference)
    assert link.amount_formula == "steel_mass"


def test_an_empty_module_gives_a_total_and_a_note(session, client):
    r = build(session, client)
    assert "MODULE C1 has no processes" in r.text
    assert any(p.name == "C1: Deconstruction"
               for p in client.store["Process"].values())


def test_net_flow_belongs_in_module_d(session):
    session.run(epd_block())
    r = session.run('MODULE A1\n  NET FLOW "Scrap", 1, kg\n  TOTAL "x"\nEND MODULE')
    refused(r, "NET FLOW belongs in MODULE D")


def test_the_quality_factor_is_a_percentage(session):
    session.run(epd_block())
    r = session.run('MODULE D\n  NET FLOW "Scrap", 1, kg QUALITY 120%\n'
                    '  TOTAL "x"\nEND MODULE')
    refused(r, "QUALITY 120%", "0 to 100%")


def test_module_d_needs_a_net_flow_under_the_programme(session):
    session.run(epd_block())
    refused(session.run('MODULE D\n  TOTAL "Benefits"\nEND MODULE'),
            "NET FLOW", "A.7.5")


def test_module_d_without_a_net_flow_is_allowed_without_a_programme(session):
    session.run(epd_block(programme=False))
    assert session.run('MODULE D\n  TOTAL "Benefits"\nEND MODULE').ok


def test_net_flows_are_stored_on_the_total(session, client):
    build(session, client)
    total = next(p for p in client.store["Process"].values()
                 if p.name.startswith("D:"))
    assert "epd:netflow1=Steel scrap|0.8|kg|80" in total.tags
    assert "epd:role=total" in total.tags


# ── data provenance ──────────────────────────────────────────

def test_a_process_without_data_is_refused_under_the_programme(session, client):
    session.run(epd_block() + bridges(client))
    r = session.run('''MODULE A1
  MAKE PROCESS "Steel supply"
    OUTPUT MAKE FLOW "Steel, supplied", 1, kg, PRODUCT
  END PROCESS
  TOTAL "Raw material supply"
END MODULE''')
    refused(r, "no DATA line", "A.5.4", "DATA PRIMARY")


def test_a_bridge_without_data_is_refused_under_the_programme(session):
    session.run(epd_block())
    r = session.run(f'BRIDGE "Steel", kg\n  PROVIDER "{STEEL}"\nEND BRIDGE')
    refused(r, "no DATA line", "DATA SECONDARY")


def test_data_is_optional_without_a_programme(session):
    session.run(epd_block(programme=False))
    r = session.run(f'BRIDGE "Steel", kg\n  PROVIDER "{STEEL}"\nEND BRIDGE\n'
                    'MODULE A1\n  MAKE PROCESS "Steel supply"\n'
                    '    OUTPUT MAKE FLOW "Steel, supplied", 1, kg, PRODUCT\n'
                    '    INPUT USE PROCESS "BRIDGE | Steel | kg", 1, kg\n'
                    '  END PROCESS\n  TOTAL "Raw material supply"\nEND MODULE')
    assert r.ok, r.errors


def test_provenance_is_stored_as_tags_and_validity_dates(session, client):
    build(session, client)
    proc = next(p for p in client.store["Process"].values()
                if p.name == "A3 | Manufacturing")
    for tag in ("epd:data=PRIMARY", "epd:source=Collected",
                "epd:provider=EPD owner", "epd:year=2025", "epd:module=A3",
                "epd:role=process", "epd:control=DIRECT"):
        assert tag in proc.tags
    assert proc.process_documentation.valid_from == "2025-01-01"
    assert proc.process_documentation.valid_until == "2025-12-31"
    bridge = next(p for p in client.store["Process"].values()
                  if p.name == "BRIDGE | Electricity | kWh")
    for tag in ("epd:electricity=RESIDUAL", "epd:country=GB",
                "epd:energy_source=Test mix", "epd:role=bridge",
                "epd:switch=epd_location_based"):
        assert tag in bridge.tags


def test_a_comma_in_a_value_does_not_split_the_tag(session, client):
    session.run(f'BRIDGE "Steel", kg\n  FOLDER "00: Loose"\n  PROVIDER "{STEEL}"\n'
                '  DATA SECONDARY SOURCE "Database" PROVIDER "A, B and C" '
                'YEAR 2024\nEND BRIDGE')
    bridge = next(p for p in client.store["Process"].values()
                  if p.name == "BRIDGE | Steel | kg")
    assert "epd:provider=A; B and C" in bridge.tags


def test_data_lines_work_without_an_epd(session, client):
    r = session.run('''MAKE PROCESS "Loose process"
  FOLDER "00: Loose"
  DATA PROXY SOURCE "Literature" PROVIDER "A paper" YEAR 2015 REASON "Other country"
  CONTROL NONE
  OUTPUT MAKE FLOW "Loose product", 1, kg, PRODUCT
END PROCESS''')
    assert r.ok, r.errors
    proc = next(p for p in client.store["Process"].values()
                if p.name == "Loose process")
    assert "epd:data=PROXY" in proc.tags
    assert "epd:reason=Other country" in proc.tags
    assert "epd:control=NONE" in proc.tags


def test_edit_process_changes_the_declaration(session, client):
    build(session, client)
    r = session.run('''EDIT PROCESS "A1 | Steel supply"
  DATA PRIMARY SOURCE "EPD" PROVIDER "S-P-00000" YEAR 2023 SHARE 60%
END EDIT''')
    assert r.ok, r.errors
    proc = next(p for p in client.store["Process"].values()
                if p.name == "A1 | Steel supply")
    assert "epd:data=PRIMARY" in proc.tags and "epd:share=60" in proc.tags
    assert "epd:data=SECONDARY" not in proc.tags
    assert "epd:module=A1" in proc.tags          # other tags are kept


@pytest.mark.parametrize("line, message", [
    ('DATA SOURCE "x" PROVIDER "y" YEAR 2020', "data category"),
    ('DATA PRIMARY SOURCE "x" YEAR 2020', "missing PROVIDER"),
    ('DATA PRIMARY SOURCE "x" PROVIDER "y"', "missing YEAR"),
    ('DATA PROXY SOURCE "x" PROVIDER "y" YEAR 2019', "REASON"),
    ('DATA PRIMARY SOURCE "x" PROVIDER "y" YEAR 2020 SHARE 140%', "SHARE"),
    ("CONTROL SOMETIMES", "DIRECT or NONE"),
])
def test_incomplete_declarations_are_parse_errors(line, message):
    with pytest.raises(ParseError, match=message) as e:
        parse(f'MAKE PROCESS "x"\n  {line}\n'
              '  OUTPUT MAKE FLOW "x", 1, kg, PRODUCT\nEND PROCESS')
    assert e.value.line == 2


def test_the_data_queue_still_works(session, client):
    """DATA with values is still the statement that feeds READ INPUTS
    FROM DATA; DATA PRIMARY and its kin are lines inside a block."""
    r = session.run(f'BRIDGE "Steel", kg\n  FOLDER "00: Loose"\n'
                    f'  PROVIDER "{STEEL}"\nEND BRIDGE\n'
                    'DATA "BRIDGE | Steel | kg", 3, "kg"\n'
                    'MAKE PROCESS "Loose process"\n  FOLDER "00: Loose"\n'
                    f'  {SECONDARY}\n'
                    '  OUTPUT MAKE FLOW "Loose product", 1, kg, PRODUCT\n'
                    '  READ INPUTS FROM DATA\nEND PROCESS')
    assert r.ok, r.errors
    proc = next(p for p in client.store["Process"].values()
                if p.name == "Loose process")
    assert len(proc.exchanges) == 2 and "epd:data=SECONDARY" in proc.tags


def test_primary_data_is_required_under_direct_control(session, client):
    session.run(epd_block() + bridges(client))
    r = session.run(f'''MODULE A3
  MAKE PROCESS "Manufacturing"
    {SECONDARY}
    OUTPUT MAKE FLOW "Block, at gate", 1, kg, PRODUCT
  END PROCESS
  TOTAL "Manufacturing"
END MODULE''')
    refused(r, "direct control", "DATA SECONDARY", "A.7.1", "CONTROL NONE")


def test_control_none_lifts_the_primary_data_rule(session, client):
    session.run(epd_block() + bridges(client))
    r = session.run(f'''MODULE A3
  MAKE PROCESS "Packaging by a supplier"
    CONTROL NONE
    {SECONDARY}
    OUTPUT MAKE FLOW "Packaging", 1, kg, PRODUCT
  END PROCESS
  TOTAL "Manufacturing"
END MODULE''')
    assert r.ok, r.errors


# ── electricity ──────────────────────────────────────────────

A3_WITH_ELECTRICITY = f'''MODULE A3
  MAKE PROCESS "Manufacturing"
    {PRIMARY}
    OUTPUT MAKE FLOW "Block, at gate", 1, kg, PRODUCT
    INPUT USE PROCESS "BRIDGE | Electricity | kWh", 2, kWh
  END PROCESS
  TOTAL "Manufacturing"
END MODULE'''


def test_consumption_mix_is_refused_under_direct_control(session, client):
    session.run(epd_block() + bridges(client, electricity="CONSUMPTION"))
    err = refused(session.run(A3_WITH_ELECTRICITY),
                  "consumption-mix", "direct control", "A.7.1",
                  "ELECTRICITY RESIDUAL")
    assert err["line"] == 5
    assert not any(p.name == "A3 | Manufacturing"
                   for p in client.store["Process"].values())


def test_the_consumption_mix_rule_has_no_override(session, client):
    """Nothing in the language turns the refusal into a warning."""
    session.run(epd_block() + bridges(client, electricity="CONSUMPTION"))
    for attempt in ("ON ERROR CONTINUE\n", "EPD CHECK SKIP \"in a hurry\"\n"):
        r = session.run(attempt + A3_WITH_ELECTRICITY)
        assert not any(p.name == "A3 | Manufacturing"
                       for p in client.store["Process"].values()), attempt


def test_consumption_mix_is_allowed_outside_direct_control(session, client):
    session.run(epd_block() + bridges(client, electricity="CONSUMPTION"))
    r = session.run(A3_WITH_ELECTRICITY.replace(
        f"    {PRIMARY}", f"    CONTROL NONE\n    {SECONDARY}"))
    assert r.ok, r.errors


def test_consumption_mix_is_refused_in_a1_when_marked_direct(session, client):
    session.run(epd_block() + bridges(client, electricity="CONSUMPTION"))
    r = session.run(A3_WITH_ELECTRICITY.replace("MODULE A3", "MODULE A1")
                    .replace(f"    {PRIMARY}", f"    CONTROL DIRECT\n    {PRIMARY}"))
    refused(r, "consumption-mix", "A1")


def test_consumption_mix_is_allowed_without_a_programme(session, client):
    session.run(epd_block(programme=False)
                + bridges(client, electricity="CONSUMPTION"))
    assert session.run(A3_WITH_ELECTRICITY).ok


def test_an_electricity_bridge_must_say_how_it_is_modelled(session, client):
    session.run(epd_block())
    gb = uid(client, ELECTRICITY, "GB")
    r = session.run(f'BRIDGE "Grid power", kWh\n  PROVIDER "{gb}"\n'
                    f'  {SECONDARY}\nEND BRIDGE')
    refused(r, "supplies electricity", "A.6.2", "ELECTRICITY CONTRACT")


def test_electricity_needs_a_country(session, client):
    gb = uid(client, ELECTRICITY, "GB")
    r = session.run(f'BRIDGE "Electricity", kWh\n  PROVIDER "{gb}"\n'
                    '  ELECTRICITY RESIDUAL\nEND BRIDGE')
    refused(r, "needs the country", "COUNTRY")


@pytest.mark.parametrize("country", ["AU", "BR", "CA", "CN", "IN", "US"])
def test_a_national_mix_is_refused_where_grids_are_sub_national(
        session, client, country):
    session.run(epd_block())
    r = session.run(bridges(client, country=country))
    refused(r, "sub-national", country, "A.6.2", "REGION")


def test_a_region_satisfies_the_sub_national_rule(session, client):
    session.run(epd_block())
    r = session.run(bridges(client, country="US", region="WECC"))
    assert r.ok, r.errors


def test_a_contract_needs_no_region(session, client):
    session.run(epd_block())
    r = session.run(bridges(client, electricity="CONTRACT", country="US"))
    assert r.ok, r.errors


def test_electricity_needs_one_of_the_three_approaches():
    with pytest.raises(ParseError, match="modelling approach"):
        parse('BRIDGE "E", kWh\n  ELECTRICITY GREEN\nEND BRIDGE')


def test_country_without_electricity_is_refused(session):
    r = session.run(f'BRIDGE "Steel", kg\n  PROVIDER "{STEEL}"\n'
                    '  COUNTRY "GB"\nEND BRIDGE')
    refused(r, "no ELECTRICITY line")


# ── the steps, in order ──────────────────────────────────────

def test_commands_need_an_epd(session):
    for command in ("EPD SYSTEMS", "EPD CHECK", "EPD CALCULATE",
                    "EPD DATA QUALITY", 'EPD REPORT "x.csv"'):
        refused(session.run(command), "needs an EPD")


def test_systems_need_every_module_total(session, client):
    session.run(epd_block() + bridges(client))
    refused(session.run("EPD SYSTEMS"), "A1, A2, A3, C1, C2, C3, C4, D",
            "TOTAL")


def test_systems_are_created_one_per_module(session, client):
    build(session, client)
    r = session.run("EPD SYSTEMS")
    assert r.ok, r.errors
    systems = sorted(s.name for s in client.store["ProductSystem"].values())
    assert systems == sorted([
        "A1: Raw material supply", "A2: Transport", "A3: Manufacturing",
        "C1: Deconstruction", "C2: Transport", "C3: Waste processing",
        "C4: Disposal", "D: Benefits beyond the system boundary"])
    assert "8 product systems ready" in r.text
    # one after another, in module order
    made = [c[1] for c in client.calls if c[0] == "create_product_system"]
    assert len(made) == 8


def test_check_needs_the_systems(session, client):
    build(session, client)
    refused(session.run("EPD CHECK"), "product system", "EPD SYSTEMS")


def test_calculate_is_refused_before_check(session, client):
    build(session, client)
    session.run("EPD SYSTEMS")
    e = refused(session.run("EPD CALCULATE"), "EPD CALCULATE refused",
                "EPD CHECK")
    assert "SKIP" not in e["hint"]       # not offered under a programme


def test_calculate_refusal_offers_skip_without_a_programme(session, client):
    r = session.run(epd_block(programme=False) + bridges(client) + MODULES)
    assert r.ok, r.errors
    session.run("EPD SYSTEMS")
    refused(session.run("EPD CALCULATE"), "EPD CHECK", "SKIP")


def test_check_skip_is_refused_under_a_programme(session, client):
    build(session, client)
    session.run("EPD SYSTEMS")
    refused(session.run('EPD CHECK SKIP "Checked on 11/11/2026"'),
            'not allowed under PROGRAMME "IES"', "no exceptions",
            "Run EPD CHECK")
    refused(session.run("EPD CALCULATE"), "EPD CALCULATE refused")


def test_check_lists_what_is_missing_and_ends_with_the_caveat(session, client):
    build(session, client)
    r = session.run("EPD SYSTEMS\nEPD CHECK")
    assert r.ok, r.errors
    assert "Product systems validated: 8" in r.text
    assert "Missing pedigree scores" in r.text
    assert "Missing description" in r.text and "A3 | Manufacturing" in r.text
    assert "structure and declarations only" in r.text
    assert "does not show that the amounts or the results are right" in r.text
    assert session.runtime.epd.check_state == "passed"


def test_check_fails_on_a_bridge_with_no_provider(session, client):
    build(session, client)
    session.run(f'BRIDGE "Spare", kg\n  {SECONDARY}\nEND BRIDGE\nEPD SYSTEMS')
    r = session.run("EPD CHECK")
    refused(r, "EPD CHECK found 1 problem")
    assert "has no provider" in r.text
    refused(session.run("EPD CALCULATE"), "EPD CHECK failed")


def test_check_finds_a_rule_broken_outside_the_session(session, client):
    """A consumption mix swapped in after the process was built."""
    build(session, client)
    bridge = next(p for p in client.store["Process"].values()
                  if p.name == "BRIDGE | Electricity | kWh")
    bridge.tags = [t.replace("RESIDUAL", "CONSUMPTION") for t in bridge.tags]
    session.run("EPD SYSTEMS")
    r = session.run("EPD CHECK")
    assert not r.ok
    assert "consumption-mix bridge" in r.text and "A.7.1" in r.text


def test_check_skip_needs_a_reason():
    with pytest.raises(ParseError, match="needs a reason"):
        parse("EPD CHECK SKIP")


def test_check_skip_lets_calculate_run_and_is_reported(session, client, tmp_path):
    """Only outside a programme: see test_check_skip_is_refused_under_a_programme."""
    r = session.run(epd_block(programme=False) + bridges(client) + MODULES)
    assert r.ok, r.errors
    out = tmp_path / "r.csv"
    r = session.run('EPD SYSTEMS\nEPD CHECK SKIP "Checked on 11/11/2026"\n'
                    f'EPD CALCULATE\nEPD REPORT "{out}"')
    assert r.ok, r.errors
    rows = read_report(out)
    check = next(r for r in rows if r and r[0] == "Model check")
    assert check[1] == "Skipped on 12/11/2026: Checked on 11/11/2026"


def test_a_change_after_check_means_checking_again(session, client):
    build(session, client)
    session.run("EPD SYSTEMS\nEPD CHECK")
    session.run(f'BRIDGE "Extra", kg\n  PROVIDER "{STEEL}"\n  {SECONDARY}\n'
                'END BRIDGE')
    refused(session.run("EPD CALCULATE"), "has not been run since the model "
                                          "last changed")


def test_report_is_refused_before_calculate(session, client):
    build(session, client)
    refused(session.run('EPD REPORT "x.csv"'), "EPD CALCULATE")


def test_report_is_refused_before_data_quality_under_the_programme(
        session, client, tmp_path):
    build(session, client)
    session.run("EPD SYSTEMS\nEPD CHECK\nEPD CALCULATE")
    out = tmp_path / "r.csv"
    refused(session.run(f'EPD REPORT "{out}"'), "EPD REPORT refused",
            "A.5.4", "EPD DATA QUALITY")
    assert not out.exists()


def test_data_quality_needs_a_programme(session, client):
    session.run(epd_block(programme=False))
    refused(session.run("EPD DATA QUALITY"), "names no programme",
            'PROGRAMME "IES"')


def test_epd_commands_do_not_run_inside_a_module():
    with pytest.raises(ParseError):
        parse('MODULE A1\n  EPD "x"\n  END EPD\n  TOTAL "y"\nEND MODULE')


def test_status_and_close(session, client):
    assert "No EPD is active" in session.run("EPD STATUS").text
    build(session, client)
    text = session.run("EPD STATUS").text
    assert "A1: Raw material supply" in text and "EPD CHECK: not run" in text
    assert "closed" in session.run("EPD CLOSE").text
    assert session.runtime.epd is None
    refused(session.run("EPD SYSTEMS"), "needs an EPD")


def test_reset_ends_the_epd(session, client):
    session.run(epd_block())
    session.reset()
    assert session.runtime.epd is None


def test_a_later_session_picks_up_what_was_built(session, client, tmp_path):
    """EPD SYSTEMS onwards work from the database, not from memory."""
    build(session, client)
    later = Session(client=client)
    out = tmp_path / "r.csv"
    r = later.run('DATABASE FAMILY "ecoinvent"\n' + epd_block()
                  + "EPD SYSTEMS\nEPD CHECK\nEPD CALCULATE\nEPD DATA QUALITY\n"
                  + f'EPD REPORT "{out}"')
    assert r.ok, r.errors
    rows = read_report(out)
    nets = rows[rows.index(["Module D: net flows"]) + 2]
    assert nets == ["Steel scrap", "0.8", "kg", "80.0"]


# ── end to end ───────────────────────────────────────────────

@pytest.fixture
def finished(session, client, tmp_path):
    """A small EPD (A1 to A3, C1 to C4, D): built, checked, calculated
    and reported."""
    build(session, client)
    out = tmp_path / "results.csv"
    r = session.run("EPD SYSTEMS\nEPD CHECK\nEPD CALCULATE\nEPD DATA QUALITY\n"
                    f'EPD REPORT "{out}" LOCATION BASED')
    assert r.ok, r.errors
    return session, r, read_report(out)


def test_end_to_end_results(finished):
    session, r, rows = finished
    results = table(rows, "Results (market-based electricity)")
    assert len(results) == 38
    gwp = results[EPD_GWP]
    assert list(gwp) == ["A1", "A2", "A3", "A1-A3", "C1", "C2", "C3", "C4", "D"]
    assert gwp["A1"] == pytest.approx(1.1 * 2.0)            # steel
    assert gwp["A2"] == pytest.approx(0.2 * 0.12)           # lorry
    assert gwp["A3"] == pytest.approx(2 * 0.25)             # GB electricity
    assert gwp["A1-A3"] == pytest.approx(gwp["A1"] + gwp["A2"] + gwp["A3"])
    assert gwp["C1"] == 0 and gwp["C3"] == 0
    assert gwp["C2"] == pytest.approx(0.05 * 0.12)
    assert gwp["C4"] == pytest.approx(0.2 * 0.05)
    assert gwp["D"] == pytest.approx(-0.5 * 2.0)


def test_indicators_are_in_the_methods_order(finished, client):
    _, _, rows = finished
    method = next(m for m in client.store["ImpactMethod"].values()
                  if m.name == EPD_METHOD)
    wanted = [ref.name for ref in method.impact_categories]
    assert list(table(rows, "Results (market-based electricity)")) == wanted


def test_module_d_is_in_no_total(finished):
    _, r, rows = finished
    header = rows[rows.index(["Results (market-based electricity)"]) + 1]
    assert header[-1] == "D"
    assert [h for h in header if "-" in h] == ["A1-A3"]     # the only total
    assert not any("total" in h.lower() for h in header)
    results = table(rows, "Results (market-based electricity)")
    for values in results.values():
        assert values["A1-A3"] == pytest.approx(
            values["A1"] + values["A2"] + values["A3"], abs=1e-12)
    note = next(r for r in rows if r and r[0] == "Totals")
    assert "not part of any total" in note[1]
    assert "never part of a total" in r.text


def test_the_report_header(finished):
    _, _, rows = finished
    head = {r[0]: r[1] for r in rows[:rows.index([])] if len(r) > 1}
    assert head["Product"] == "Test block"
    assert head["EPD type"] == TYPE_GATE_CD
    assert head["Declared unit"] == "1 kg"
    assert head["Method"] == EPD_METHOD
    assert head["Impact categories"] == "38"
    assert head["Database family"] == "ecoinvent"
    assert head["olcaBASIC version"] == "0.4.0"
    assert head["Date"] == "12/11/2026"                      # DD/MM/YYYY
    assert head["Programme"] == "International EPD System (GPI 5.1.0)"
    assert head["PCR"] == "Test PCR 1.0"
    assert head["Database"] == "synthetic 1"
    assert head["Biogenic carbon in the product"] == "No"
    assert head["Model check"].startswith("Passed on 12/11/2026")
    assert "A.5.4" in head["Programme statement"]


def test_the_report_declares_the_electricity(finished):
    _, _, rows = finished
    start = rows.index(["Electricity in processes under direct control"])
    assert rows[start + 1][-1] == f"{EPD_GWP} (kg CO2 eq. per kWh)"
    bridge, approach, source, country, region, per_kwh = rows[start + 2]
    assert bridge == "BRIDGE | Electricity | kWh"
    assert (approach, source, country) == ("Residual mix", "Test mix", "GB")
    assert float(per_kwh) == pytest.approx(0.25)     # from running the bridge


def test_the_report_lists_net_flows_and_cutoffs(session, client, tmp_path):
    out = tmp_path / "r.csv"
    block = epd_block(extra='  CUTOFF A3 "Lubricants", 0.2%\n')
    r = session.run(block + bridges(client) + MODULES
                    + "EPD SYSTEMS\nEPD CHECK\nEPD CALCULATE\nEPD DATA QUALITY\n"
                    + f'EPD REPORT "{out}"')
    assert r.ok, r.errors
    rows = read_report(out)
    cut = rows.index(["Cut-offs declared"])
    assert rows[cut + 2] == ["A3", "Lubricants", "0.2"]
    net = rows.index(["Module D: net flows"])
    assert rows[net + 2] == ["Steel scrap", "0.8", "kg", "80.0"]
    assert ["Results"] in rows                     # no second table asked for


def test_location_based_results_are_a_second_table(finished):
    _, _, rows = finished
    main = table(rows, "Results (market-based electricity)")
    second = table(rows, "Location-based results (consumption mixes for all "
                         "electricity)")
    assert second[EPD_GWP]["A3"] == pytest.approx(2 * 0.40)   # DE mix
    assert main[EPD_GWP]["A3"] == pytest.approx(2 * 0.25)
    assert second[EPD_GWP]["A1"] == main[EPD_GWP]["A1"]


def test_location_based_needs_a_second_provider(session, client, tmp_path):
    build(session, client, location_based=False)
    session.run("EPD SYSTEMS\nEPD CHECK\nEPD CALCULATE\nEPD DATA QUALITY")
    r = session.run(f'EPD REPORT "{tmp_path / "r.csv"}" LOCATION BASED')
    refused(r, "LOCATION BASED", "BRIDGE | Electricity | kWh",
            "LOCATION BASED PROVIDER")


def test_the_report_without_a_programme(session, client, tmp_path):
    out = tmp_path / "r.csv"
    r = session.run(epd_block(programme=False) + bridges(client) + MODULES
                    + f'EPD SYSTEMS\nEPD CHECK\nEPD CALCULATE\nEPD REPORT "{out}"')
    assert r.ok, r.errors
    rows = read_report(out)
    assert ["Programme", "None named: EN 15804+A2 rules only"] in rows
    assert len(table(rows, "Results")) == 38


def test_the_exemption_is_justified_in_the_report(session, client, tmp_path):
    out = tmp_path / "r.csv"
    short = MODULES[:MODULES.index("MODULE C1")]
    r = session.run(epd_block(modules="A1, A2, A3", extra=EXEMPT)
                    + bridges(client) + short
                    + "EPD SYSTEMS\nEPD CHECK\nEPD CALCULATE\nEPD DATA QUALITY\n"
                    + f'EPD REPORT "{out}"')
    assert r.ok, r.errors
    rows = read_report(out)
    head = {r[0]: r[1] for r in rows if len(r) == 2}
    assert head["EPD type"] == TYPE_GATE
    assert "clause 5.2" in head["Modules C1 to C4 and D"]
    assert head["Integrated with other products"] == "Cast into the structure"
    assert head["End of life scenarios"] == "See the EPD of the structure"
    assert rows[rows.index(["Results"]) + 1][2:] == ["A1", "A2", "A3", "A1-A3"]


def test_structured_results_come_back_through_the_session(finished):
    _, r, _ = finished
    calls = {d["call"]: d["result"] for d in r.data}
    assert calls["epd_calculate"]["modules"]["A3"][EPD_GWP] == pytest.approx(0.5)
    assert calls["epd_calculate"]["A1-A3"][EPD_GWP] == pytest.approx(2.724)
    assert calls["epd_data_quality"]["passed"] is True
    assert calls["epd_report"]["location_based"]["A3"][EPD_GWP] == pytest.approx(0.8)


# ── EPD DATA QUALITY ─────────────────────────────────────────

def dq(session):
    r = session.run("EPD SYSTEMS\nEPD CHECK\nEPD CALCULATE\nEPD DATA QUALITY")
    return r, session.runtime.epd.dq


def test_rows_above_the_threshold_and_the_share_of_primary_data(session, client):
    build(session, client)
    r, data = dq(session)
    assert r.ok, r.errors
    total = 1.1 * 2.0 + 0.2 * 0.12 + 2 * 0.25
    rows = {row["process"]: row for row in data["rows"]}
    assert set(rows) == {"BRIDGE | Steel | kg", "BRIDGE | Electricity | kWh"}
    steel = rows["BRIDGE | Steel | kg"]
    assert steel["share_of_gwp"] == pytest.approx(100 * 2.2 / total)
    assert (steel["source_type"], steel["source"], steel["year"],
            steel["category"]) == ("Database", "synthetic 1", 2024, "SECONDARY")
    assert steel["primary_share"] == 0
    assert data["others"]["count"] == 1                 # the lorry, under 10%
    # primary: the electricity and the lorry
    assert data["primary_share"] == pytest.approx(100 * (0.5 + 0.024) / total)
    assert data["primary_share_text"] == "19.2%"
    assert data["indicator"] == EPD_GWP


def test_a_stated_share_of_primary_data_is_used(session, client):
    build(session, client, steel_data='DATA SECONDARY SOURCE "EPD" PROVIDER '
                                      '"S-P-00000" YEAR 2023 SHARE 75%')
    _, data = dq(session)
    total = 2.2 + 0.024 + 0.5
    assert data["primary_share"] == pytest.approx(
        100 * (0.75 * 2.2 + 0.524) / total)


def test_a_share_above_the_cap_is_reported_as_more_than(session, client):
    build(session, client, steel_data='DATA PRIMARY SOURCE "EPD" PROVIDER '
                                      '"S-P-00000" YEAR 2023')
    r, data = dq(session)
    assert data["primary_share"] == pytest.approx(100.0)
    assert data["primary_share_text"] == ">90%"
    assert "A1-A3: >90%" in r.text


def test_proxy_data_above_the_limit_is_an_error(session, client):
    build(session, client, steel_data='DATA PROXY SOURCE "Database" PROVIDER '
                                      '"synthetic 1" YEAR 2019 REASON "Other alloy"')
    r, data = dq(session)
    refused(r, "EPD DATA QUALITY found", "no override")
    assert not data["passed"]
    assert any("Proxy data gives" in e and "limit is 10%" in e and "A.5.1" in e
               for e in data["errors"])
    assert "ERROR: Proxy data gives" in r.text


def test_a_little_proxy_data_passes(session, client):
    session.run(epd_block() + bridges(client))
    extra = f'''BRIDGE "Minor steel", kg
  PROVIDER "{STEEL}"
  DATA PROXY SOURCE "Database" PROVIDER "synthetic 1" YEAR 2019 REASON "Other alloy"
END BRIDGE
'''
    modules = MODULES.replace(
        '    INPUT USE PROCESS "BRIDGE | Steel | kg", 1.1, kg\n',
        '    INPUT USE PROCESS "BRIDGE | Steel | kg", 1.1, kg\n'
        '    INPUT USE PROCESS "BRIDGE | Minor steel | kg", 0.05, kg\n')
    assert session.run(extra + modules).ok
    r, data = dq(session)
    assert r.ok, r.errors
    worst = max(p["share"] for p in data["proxy"])
    assert 0 < worst < 10
    assert "Proxy data: at most" in r.text


def test_primary_data_older_than_five_years_is_an_error(session, client):
    build(session, client)
    session.run('''EDIT PROCESS "A2 | Transport to factory"
  DATA PRIMARY SOURCE "Collected" PROVIDER "EPD owner" YEAR 2020
END EDIT''')
    r, data = dq(session)
    assert not r.ok
    assert any("primary data from 2020 is 6 years old" in e and "A.5.2" in e
               for e in data["errors"])


def test_primary_data_five_years_old_passes(session, client):
    build(session, client)
    session.run('''EDIT PROCESS "A2 | Transport to factory"
  DATA PRIMARY SOURCE "Collected" PROVIDER "EPD owner" YEAR 2021
END EDIT''')
    r, _ = dq(session)
    assert r.ok, r.errors


def test_old_secondary_data_is_an_error_and_counts_as_proxy(session, client):
    build(session, client, steel_data='DATA SECONDARY SOURCE "Database" '
                                      'PROVIDER "synthetic 0" YEAR 2015')
    r, data = dq(session)
    assert not r.ok
    assert any("reference year 2015 is 11 years old" in e and "A.5.3" in e
               for e in data["errors"])
    steel = next(row for row in data["rows"]
                 if row["process"] == "BRIDGE | Steel | kg")
    assert steel["category"] == "PROXY"
    assert any("Proxy data gives" in e for e in data["errors"])


def test_secondary_data_ten_years_old_passes(session, client):
    build(session, client, steel_data='DATA SECONDARY SOURCE "Database" '
                                      'PROVIDER "synthetic 0" YEAR 2016')
    r, _ = dq(session)
    assert r.ok, r.errors


def test_the_coverage_list(session, client):
    build(session, client)
    _, data = dq(session)
    cover = {c["process"]: c["indicators"] for c in data["coverage"]}
    # 0.4.0: the coverage runs over the 20 impact indicators only, not
    # over all 38 categories of the method
    assert data["impact_indicators"] == 20
    assert data["indicators_reported"] == 38
    assert cover["BRIDGE | Steel | kg"] >= 15
    assert all(1 <= n <= 20 for n in cover.values())
    assert "A1: Raw material supply" not in cover        # totals carry nothing


def test_the_parts_add_up_to_the_module_totals(session, client):
    build(session, client)
    dq(session)
    epd = session.runtime.epd
    for code in epd.d["modules"]:
        split = epd._parts(code, epd._system_of(code), 0)
        for cat, total in split["totals"].items():
            assert sum(p["values"].get(cat, 0.0) for p in split["parts"]) \
                == pytest.approx(total, abs=1e-12), (code, cat)


def test_the_programmes_wording_is_not_reproduced(session, client):
    build(session, client)
    r, _ = dq(session)
    assert "has to carry the programme's statement" in r.text
    assert "A.5.4" in r.text
    assert "simplified indicator" not in r.text


def test_data_quality_needs_the_gwp_indicator(session, client):
    client.add_method("EN15804+A2 (unnamed)",
                      {f"Category {n:02d}": "unit" for n in range(38)})
    r = session.run(epd_block(method="EN15804+A2 (unnamed)"))
    assert r.ok
    assert session.runtime.epd.gwp_indicator == ""
    session.runtime.epd.results = {"A1": {}}
    refused(session.run("EPD DATA QUALITY"), "GWP-GHG", "GWP INDICATOR")


def test_the_gwp_indicator_can_be_named(session, client):
    client.add_method("EN15804+A2 (unnamed)",
                      {f"Category {n:02d}": "unit" for n in range(38)})
    r = session.run(epd_block(method="EN15804+A2 (unnamed)",
                              extra='  GWP INDICATOR "Category 03"\n'))
    assert r.ok and session.runtime.epd.gwp_indicator == "Category 03"


# ── templates ────────────────────────────────────────────────

def test_three_templates_ship():
    assert templates.names() == ["bridges_common", "epd_skeleton",
                                 "sensitivity_epd"]


@pytest.mark.parametrize("name", ["bridges_common", "epd_skeleton",
                                  "sensitivity_epd"])
def test_every_template_parses_and_is_plain_text(name):
    text = templates.read(name)
    assert parse(text)
    assert "—" not in text and "–" not in text


def test_the_skeleton_passes_a_dry_run():
    text = templates.read("epd_skeleton")
    r = Session(offline=True).run(text, dry_run=True)
    assert r.errors == [], r.errors


def test_the_skeleton_defines_an_epd_with_every_mandatory_module(session):
    text = templates.read("epd_skeleton")
    block = text[text.index('EPD "Product name"'):text.index("END EPD") + 7]
    r = session.run(block)
    assert r.ok, r.errors
    assert session.runtime.epd.d["modules"] == FULL.split(", ")


def test_new_from_template_copies_the_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = Session(offline=True).run(
        'NEW FROM TEMPLATE "epd_skeleton" AS "my_epd.baslca"')
    assert r.ok, r.errors
    assert (tmp_path / "my_epd.baslca").read_text(encoding="utf-8") \
        == templates.read("epd_skeleton")


def test_new_from_template_adds_the_extension(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Session(offline=True).run('NEW FROM TEMPLATE "bridges_common" AS "bridges"')
    assert (tmp_path / "bridges.baslca").exists()


def test_new_from_template_does_not_write_over_a_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mine.baslca").write_text("PRINT 1", encoding="utf-8")
    r = Session(offline=True).run(
        'NEW FROM TEMPLATE "epd_skeleton" AS "mine.baslca"')
    refused(r, "already exists")
    assert (tmp_path / "mine.baslca").read_text(encoding="utf-8") == "PRINT 1"


def test_an_unknown_template_lists_the_real_ones(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = Session(offline=True).run('NEW FROM TEMPLATE "nonsense" AS "x.baslca"')
    refused(r, "no template called 'nonsense'", "epd_skeleton")


def test_new_alone_is_still_refused_as_before(session):
    r = session.run("NEW")
    assert not r.ok and "NEW is not supported" in r.errors[0]["message"]


# ── language details ─────────────────────────────────────────

def test_epd_and_module_are_still_usable_as_variable_names(session):
    r = session.run("LET epd = 2\nLET module = 3\nPRINT epd * module")
    assert r.ok and "6" in r.text
    r = session.run("epd = 5\nmodule = epd + 1\nPRINT module")
    assert r.ok and "6" in r.text


def test_epd_alone_says_what_it_needs():
    with pytest.raises(ParseError, match="needs a name, or a command"):
        parse("EPD")


def test_a_line_is_given_twice():
    with pytest.raises(ParseError, match="METHOD is given twice") as e:
        parse(epd_block(extra=f'  METHOD "{EPD_METHOD}"\n'))
    assert e.value.line == 10


def test_an_unknown_line_in_the_block_lists_what_is_allowed():
    with pytest.raises(ParseError, match="expected PROGRAMME, PCR"):
        parse(epd_block(extra="  COLOUR blue\n"))


def test_dry_run_checks_the_block_without_openlca():
    s = Session(offline=True)
    r = s.run(epd_block(modules="A1, A2, A3"), dry_run=True)
    assert not r.ok
    assert "C1 to C4 and D" in r.errors[0]["message"]
    assert r.errors[0]["line"] == 8


def test_dry_run_checks_modules_against_the_block():
    s = Session(offline=True)
    r = s.run(epd_block() + 'MODULE A4\n  TOTAL "x"\nEND MODULE\n'
              'MODULE A1\nEND MODULE', dry_run=True)
    messages = " ".join(e["message"] for e in r.errors)
    assert "MODULE A4 is not declared" in messages
    assert "MODULE A1 has no TOTAL line" in messages


def test_dry_run_wants_an_epd_before_the_commands():
    r = Session(offline=True).run("EPD SYSTEMS", dry_run=True)
    assert "needs an EPD" in r.errors[0]["message"]


def test_help_epd_comes_from_the_registry(session):
    text = session.run("HELP EPD").text
    for word in ("EPD SYSTEMS", "EPD CHECK", "EPD CALCULATE",
                 "EPD DATA QUALITY", "EPD REPORT", "MODULE",
                 "NEW FROM TEMPLATE", "BIOGENIC CARBON"):
        assert word in text


def test_user_facing_text_has_no_dashes_or_standard_text(finished):
    _, r, rows = finished
    flat = r.text + " ".join(" ".join(row) for row in rows)
    assert "—" not in flat and "–" not in flat


# ── EPD SAVE: the EPD as openLCA's own Epd entity ────────────

import olca_schema as o  # noqa: E402


def stored(client, cls, name):
    found = client.by_name(cls, name)
    assert len(found) == 1, f"{len(found)} {cls.__name__} called {name}"
    return found[0]


def test_save_is_refused_before_the_report(session, client):
    build(session, client)
    refused(session.run("EPD SAVE"), "EPD SAVE refused",
            "EPD REPORT has not been run", 'EPD REPORT "file.csv"')
    assert session.run("EPD SYSTEMS\nEPD CHECK\nEPD CALCULATE\n"
                       "EPD DATA QUALITY").ok
    refused(session.run("EPD SAVE"), "EPD SAVE refused",
            "has not passed since the results were last calculated")
    assert not client.store["Epd"] and not client.store["Result"]


def test_save_writes_the_epd_and_a_result_per_module(finished, client):
    session, _, rows = finished
    r = session.run("EPD SAVE")
    assert r.ok, r.errors
    epd = stored(client, o.Epd, "Test block")
    assert epd.category == FOLDER
    assert [m.name for m in epd.modules] == ["A1", "A2", "A3", "C1", "C2",
                                             "C3", "C4", "D"]
    assert all(m.multiplier == 1.0 for m in epd.modules)
    # the product is the output of manufacturing, in the declared unit
    assert epd.product.flow.name == "A3: Manufacturing"
    assert (epd.product.amount, epd.product.unit.name) == (1.0, "kg")
    assert epd.product.flow_property.name == "Mass"
    report = table(rows, "Results (market-based electricity)")
    for module in epd.modules:
        result = client.store["Result"][module.result.id]
        assert result.name == f"Test block | {module.name}"
        assert result.category == f"{FOLDER}/Results"
        assert result.impact_method.name == EPD_METHOD
        assert len(result.impact_results) == 38
        gwp = next(i.amount for i in result.impact_results
                   if i.indicator.name == EPD_GWP)
        assert gwp == pytest.approx(report[EPD_GWP][module.name], abs=1e-12)
        assert sum(1 for f in result.flow_results if f.is_ref_flow) == 1
    assert "International EPD System (GPI 5.1.0)" in epd.description
    assert "12/11/2026" in epd.description
    assert "EPD saved in openLCA: Test block (8 modules" in r.text
    assert client.undisposed() == 0
    saved = r.data[-1]
    assert saved["call"] == "epd_save" and saved["result"]["modules"] == 8


def test_save_can_be_read_back_with_show_and_find(finished):
    session, _, _ = finished
    assert session.run("EPD SAVE").ok
    text = session.run('SHOW EPD "Test block"').text
    assert "Test block | A3" in text and "Declared amount: 1 kg" in text
    assert "Test block" in session.run("FIND EPD").text
    assert "Test block | D" in session.run('FIND RESULT "Test block"').text


def test_save_does_not_write_over_an_epd_without_replace(finished, client):
    session, _, _ = finished
    assert session.run("EPD SAVE").ok
    first = stored(client, o.Epd, "Test block").id
    results = set(client.store["Result"])
    refused(session.run("EPD SAVE"), "is in the database already",
            "EPD SAVE REPLACE")
    r = session.run("EPD SAVE REPLACE")
    assert r.ok and "EPD replaced in openLCA" in r.text
    assert stored(client, o.Epd, "Test block").id == first
    assert set(client.store["Result"]) == results      # replaced, not added


def test_save_takes_who_and_when(finished, client):
    session, _, _ = finished
    assert session.run('''
SET PROCESS FOLDER "00: Test EPD"
MAKE ACTOR "Synthetic maker"
END ACTOR
MAKE ACTOR "Synthetic verifier"
END ACTOR
MAKE SOURCE "Synthetic PCR"
END SOURCE''').ok
    r = session.run('EPD SAVE MANUFACTURER "Synthetic maker" VERIFIER '
                    '"Synthetic verifier" PCR "Synthetic PCR" REGISTRATION '
                    '"TEST-0001" VALID FROM "12/11/2026" VALID UNTIL '
                    '"11/11/2031"')
    assert r.ok, r.errors
    epd = stored(client, o.Epd, "Test block")
    assert epd.manufacturer.name == "Synthetic maker"
    assert epd.verifier.name == "Synthetic verifier"
    assert epd.pcr.name == "Synthetic PCR"
    assert epd.registration_id == "TEST-0001"
    assert (epd.valid_from, epd.valid_until) == ("2026-11-12", "2031-11-11")


@pytest.mark.parametrize("options,message", [
    ('MANUFACTURER "Nobody"', "No actor is called 'Nobody'"),
    ('PCR "Nothing"', "No source is called 'Nothing'"),
    ('VALID FROM "soon"', "is not a date"),
    ('VALID FROM "12/11/2026" VALID UNTIL "11/11/2026"',
     "VALID UNTIL is not after VALID FROM"),
])
def test_save_refusals_write_no_epd(finished, client, options, message):
    session, _, _ = finished
    refused(session.run(f"EPD SAVE {options}"), message)
    assert not client.store["Epd"]


def test_save_parse_errors():
    with pytest.raises(ParseError, match="doesn't take 'COLOUR'"):
        parse("EPD SAVE COLOUR")
    with pytest.raises(ParseError, match="VERIFIER needs a value"):
        parse("EPD SAVE VERIFIER")
    with pytest.raises(ParseError, match="given twice"):
        parse('EPD SAVE VERIFIER "a" VERIFIER "b"')


def test_save_is_refused_when_the_model_changed_after_the_report(
        finished, client):
    session, _, _ = finished
    # a change behind olcaBASIC's back: the electricity bought doubles
    proc = stored(client, o.Process, "A3 | Manufacturing")
    bought = [p for p in proc.parameters if p.value == 2]
    assert len(bought) == 1
    bought[0].value = 4
    refused(session.run("EPD SAVE"), "Module A3", "The model has changed",
            "EPD REPORT again")
    assert not client.store["Epd"]
    assert client.undisposed() == 0


def test_a_rebuild_after_the_report_needs_the_report_again(finished, client):
    session, _, _ = finished
    assert session.run("EPD SYSTEMS").ok
    refused(session.run("EPD SAVE"), "EPD REPORT has not been run")


def test_status_shows_the_report_step(finished):
    session, _, _ = finished
    assert "EPD REPORT: passed" in session.run("EPD STATUS").text


def test_each_module_system_has_its_module_as_an_analysis_group(
        finished, client):
    session, _, _ = finished
    for code, own in (("A1", {"A1: Raw material supply",
                              "A1 | Steel supply"}),
                      ("A3", {"A3: Manufacturing", "A3 | Manufacturing"}),
                      ("C1", {"C1: Deconstruction"})):
        total = next(n for n in own if n.startswith(code + ":"))
        system = stored(client, o.ProductSystem, total)
        assert [g.name for g in system.analysis_groups] == [code]
        assert {r.name for r in system.analysis_groups[0].processes} == own


def test_results_by_group_read_the_module_group(finished, client):
    session, _, _ = finished
    r = session.run(f'CALCULATE "A3: Manufacturing" USING "{EPD_METHOD}"\n'
                    f'RESULT IMPACTS BY GROUP CATEGORY "{EPD_GWP}"')
    assert r.ok, r.errors
    rows = {row["group"]: row["amount"]
            for row in r.data[-1]["result"]["rows"]}
    assert rows["A3"] == pytest.approx(2 * 0.25)
    session.run("CLOSE RESULT ALL")


def test_running_systems_again_leaves_the_groups_as_they_are(finished,
                                                             client):
    session, _, _ = finished
    client.calls.clear()
    assert session.run("EPD SYSTEMS").ok
    assert not [c for c in client.calls if c[:2] == ("put", "ProductSystem")]
