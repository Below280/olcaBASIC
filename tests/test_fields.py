"""The wider fields of processes, flows and product systems: written by
the language, read back with SHOW, and used by the calculation.

All data here is synthetic.
"""

import pytest
import olca_schema as o

from fake_client import ELECTRICITY, STEEL
from olcabasic import Session
from olcabasic.engine.fields import (DOCUMENT_FIELDS, make_uncertainty,
                                     parse_date)
from test_interpreter_lca import SETUP, process

EF = "EF v3.1"
FOSSIL = "Climate change: fossil"


@pytest.fixture
def client(client):
    """The synthetic database plus what the new fields point at: two
    currencies, two actors, two sources and a social indicator."""
    eur = o.Currency(id="cur-eur", name="Euro", code="EUR",
                     conversion_factor=1.0)
    eur.ref_currency = o.Ref(id="cur-eur", name="Euro")
    gbp = o.Currency(id="cur-gbp", name="Pound Sterling", code="GBP",
                     conversion_factor=1.25,
                     ref_currency=o.Ref(id="cur-eur", name="Euro"))
    for cur in (eur, gbp):
        client.store["Currency"][cur.id] = cur
    for name in ("Test author", "Test reviewer"):
        client.store["Actor"][name] = o.Actor(id=name, name=name)
    for name in ("Test report", "Test standard"):
        client.store["Source"][name] = o.Source(id=name, name=name)
    client.store["SocialIndicator"]["si"] = o.SocialIndicator(
        id="si", name="Test working hours")
    return client


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


def exchange(client, proc_name, flow_part):
    proc = process(client, proc_name)
    found = [ex for ex in proc.exchanges
             if flow_part in client._flow_name(ex.flow.id)]
    assert len(found) == 1, found
    return found[0]


PLAIN = f'''
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  INPUT USE PROCESS "{ELECTRICITY}", 2, kWh LOCATION "GB"
  INPUT USE PROCESS "{STEEL}", 0.5, kg
  OUTPUT "Carbon dioxide, fossil", 0.1, kg TO AIR
END PROCESS
'''


# ── uncertainty: the rules for the numbers ───────────────────

@pytest.mark.parametrize("kind,values,fragment", [
    ("LOGNORMAL", [2, 1.0], "above 1"),
    ("LOGNORMAL", [2, 0.9], "above 1"),
    ("LOGNORMAL", [0, 1.2], "geometric mean"),
    ("NORMAL", [5, 0], "standard deviation must be above 0"),
    ("NORMAL", [5, -1], "standard deviation must be above 0"),
    ("TRIANGLE", [3, 2, 4], "minimum <= mode <= maximum"),
    ("TRIANGLE", [1, 5, 4], "minimum <= mode <= maximum"),
    ("TRIANGLE", [2, 2, 2], "minimum below maximum"),
    ("UNIFORM", [4, 4], "minimum below maximum"),
    ("UNIFORM", [5, 4], "minimum below maximum"),
    ("NORMAL", [5], "takes 2 numbers"),
    ("BETA", [1, 2], "Unknown uncertainty distribution"),
])
def test_uncertainty_numbers_are_checked(kind, values, fragment):
    made, error = make_uncertainty(kind, values)
    assert made is None and fragment in error


def test_uncertainty_objects():
    u, _ = make_uncertainty("LOGNORMAL", [2.5, 1.2])
    assert u.distribution_type == o.UncertaintyType.LOG_NORMAL_DISTRIBUTION
    assert (u.geom_mean, u.geom_sd) == (2.5, 1.2)
    u, _ = make_uncertainty("TRIANGLE", [1, 2, 3])
    assert (u.minimum, u.mode, u.maximum) == (1, 2, 3)
    u, _ = make_uncertainty("TRIANGLE", [1, 1, 3])     # mode at an end
    assert u is not None


def test_uncertainty_on_exchanges_is_written(session, client):
    ok(session, f'''
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  INPUT USE PROCESS "{ELECTRICITY}", 2, kWh LOCATION "GB" UNCERTAINTY LOGNORMAL 2, 1.2 BASE UNCERTAINTY 0.0006
  INPUT USE PROCESS "{STEEL}", 0.5, kg UNCERTAINTY TRIANGLE 0.4, 0.5, 0.7
  OUTPUT "Carbon dioxide, fossil", 0.1, kg TO AIR UNCERTAINTY UNIFORM 0.05, 0.15
END PROCESS''')
    elec = exchange(client, "Gadget", "electricity")
    assert elec.uncertainty.distribution_type == \
        o.UncertaintyType.LOG_NORMAL_DISTRIBUTION
    assert (elec.uncertainty.geom_mean, elec.uncertainty.geom_sd) == (2, 1.2)
    assert elec.base_uncertainty == 0.0006
    steel = exchange(client, "Gadget", "steel")
    assert (steel.uncertainty.minimum, steel.uncertainty.mode,
            steel.uncertainty.maximum) == (0.4, 0.5, 0.7)
    co2 = exchange(client, "Gadget", "Carbon dioxide")
    assert (co2.uncertainty.minimum, co2.uncertainty.maximum) == (0.05, 0.15)
    assert exchange(client, "Gadget", "Gadget").uncertainty is None


def test_bad_uncertainty_stops_the_block_before_anything_is_written(
        session, client):
    e = err(session, f'''
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  INPUT USE PROCESS "{STEEL}", 0.5, kg UNCERTAINTY LOGNORMAL 0.5, 0.8
END PROCESS''')
    assert e["line"] == 4 and "above 1" in e["message"]
    assert client.by_name(o.Process, "Gadget") == []
    assert client.by_name(o.Flow, "Gadget") == []


def test_uncertainty_takes_variables(session, client):
    ok(session, f'''
LET spread = 1.3
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  INPUT USE PROCESS "{STEEL}", 0.5, kg UNCERTAINTY LOGNORMAL 0.5, spread
END PROCESS''')
    assert exchange(client, "Gadget", "steel").uncertainty.geom_sd == 1.3


def test_uncertainty_needs_a_distribution(session):
    e = err(session, f'''
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  INPUT USE PROCESS "{STEEL}", 0.5, kg UNCERTAINTY 0.5, 0.8
END PROCESS''')
    assert "UNCERTAINTY needs a distribution" in e["message"]
    assert "LOGNORMAL gm, gsd" in e["hint"]


def test_uncertainty_on_a_local_parameter(session, client):
    ok(session, f'''
MAKE PROCESS "Gadget"
  LET yield = 0.9 UNCERTAINTY NORMAL 0.9, 0.05
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  INPUT USE PROCESS "{STEEL}", 0.5 / yield, kg
END PROCESS''')
    param = next(p for p in process(client, "Gadget").parameters
                 if p.name == "yield")
    assert (param.uncertainty.mean, param.uncertainty.sd) == (0.9, 0.05)


def test_uncertainty_on_a_global_parameter(session, client):
    ok(session, f'''
LET steel_kg = 0.5 UNCERTAINTY UNIFORM 0.4, 0.6
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  INPUT USE PROCESS "{STEEL}", steel_kg, kg
END PROCESS''')
    param = client.by_name(o.Parameter, "steel_kg")[0]
    assert (param.uncertainty.minimum, param.uncertainty.maximum) == (0.4, 0.6)
    # given later, it reaches the parameter that already exists
    ok(session, "LET steel_kg = 0.5 UNCERTAINTY NORMAL 0.5, 0.02")
    param = client.by_name(o.Parameter, "steel_kg")[0]
    assert param.uncertainty.sd == 0.02
    ok(session, "LET steel_kg = 0.5 UNCERTAINTY NONE")
    assert client.by_name(o.Parameter, "steel_kg")[0].uncertainty is None


def test_uncertainty_on_a_calculated_variable_is_refused(session):
    e = err(session, "LET a = 2\nLET b = a * 2 UNCERTAINTY NORMAL 4, 1")
    assert e["line"] == 2 and "calculated from other variables" in e["message"]


def test_montecarlo_draws_from_the_distributions(session, client):
    ok(session, f'''
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  INPUT USE PROCESS "{STEEL}", 0.5, kg UNCERTAINTY UNIFORM 0.4, 0.6
END PROCESS
SYSTEM "Gadget"''')
    r = ok(session, f'MONTECARLO "Gadget" USING "{EF}" RUNS 200')
    stats = r.data[-1]["result"]["statistics"][FOSSIL]
    # 0.4 to 0.6 kg of steel at 2.0 per kg
    assert 0.8 <= stats["min"] < stats["max"] <= 1.2
    assert stats["std_dev"] > 0
    assert stats["mean"] == pytest.approx(1.0, abs=0.05)


# ── avoided products ─────────────────────────────────────────

AVOIDED = f'''
MAKE PROCESS "Heat plant"
  OUTPUT MAKE FLOW "Test heat", 1, MJ, PRODUCT
  OUTPUT USE PROCESS "{ELECTRICITY}", 0.1, kWh LOCATION "GB" AVOIDED
  INPUT USE PROCESS "{STEEL}", 0.5, kg
END PROCESS
SYSTEM "Heat plant"
'''


def test_avoided_product_is_written_and_credits_the_result(session, client):
    ok(session, AVOIDED)
    ex = exchange(client, "Heat plant", "electricity")
    assert ex.is_avoided_product is True and ex.is_input is False
    r = ok(session, f'CALCULATE "Heat plant" USING "{EF}"')
    fossil = next(i for i in r.data[-1]["result"]["impacts"]
                  if i["category"] == FOSSIL)
    # 0.5 kg steel x 2.0, less 0.1 kWh of electricity x 0.25
    assert fossil["amount"] == pytest.approx(0.5 * 2.0 - 0.1 * 0.25)


def test_the_reference_product_cannot_be_avoided(session, client):
    e = err(session, '''
MAKE PROCESS "Odd"
  OUTPUT MAKE FLOW "Odd", 1, kg, PRODUCT AVOIDED
END PROCESS''')
    assert e["line"] == 3
    assert "reference product cannot be an avoided product" in e["message"]
    assert client.by_name(o.Process, "Odd") == []
    assert client.by_name(o.Flow, "Odd") == []


def test_an_input_cannot_be_avoided(session):
    e = err(session, f'''
MAKE PROCESS "Odd"
  OUTPUT MAKE FLOW "Odd", 1, kg, PRODUCT
  INPUT USE PROCESS "{STEEL}", 0.5, kg AVOIDED
END PROCESS''')
    assert e["line"] == 4 and "AVOIDED is for a product" in e["message"]
    e = err(session, '''
MAKE PROCESS "Odd"
  OUTPUT MAKE FLOW "Odd", 1, kg, PRODUCT
  OUTPUT "Carbon dioxide, fossil", 1, kg TO AIR AVOIDED
END PROCESS''')
    assert "elementary" in e["message"] + e["hint"]


# ── costs ────────────────────────────────────────────────────

COSTED = f'''
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT COST 10 CURRENCY "EUR"
  INPUT USE PROCESS "{ELECTRICITY}", 2, kWh LOCATION "GB" COST 0.4 CURRENCY "GBP"
  INPUT USE PROCESS "{STEEL}", 0.5, kg COST 1.5 CURRENCY "Euro"
END PROCESS
SYSTEM "Gadget"
'''


def test_costs_are_written(session, client):
    ok(session, COSTED)
    elec = exchange(client, "Gadget", "electricity")
    assert elec.cost_value == 0.4 and elec.currency.name == "Pound Sterling"
    assert exchange(client, "Gadget", "steel").currency.name == "Euro"
    assert exchange(client, "Gadget", "Gadget").cost_value == 10


def test_costs_reach_the_result(session):
    ok(session, COSTED)
    r = ok(session, f'CALCULATE "Gadget" USING "{EF}" WITH COSTS\n'
                    f'RESULT COSTS')
    # 0.4 GBP x 1.25 + 1.5 EUR, less 10 EUR of revenue
    assert r.data[-1]["result"]["rows"][0]["amount"] == pytest.approx(
        0.4 * 1.25 + 1.5 - 10)


def test_cost_needs_a_currency_that_exists(session, client):
    e = err(session, f'''
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  INPUT USE PROCESS "{STEEL}", 0.5, kg COST 1.5 CURRENCY "XXX"
END PROCESS''')
    assert e["line"] == 4 and "No currency is called 'XXX'" in e["message"]
    assert "MAKE CURRENCY" in e["hint"]
    assert client.by_name(o.Process, "Gadget") == []
    assert client.by_name(o.Flow, "Gadget") == []
    e = err(session, f'''
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  INPUT USE PROCESS "{STEEL}", 0.5, kg COST 1.5
END PROCESS''')
    assert "COST needs a currency" in e["message"]


def test_cost_formula(session, client):
    ok(session, f'''
MAKE PROCESS "Gadget"
  LET price = 3
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  INPUT USE PROCESS "{STEEL}", 0.5, kg COST FORMULA "0.5 * price" CURRENCY "EUR"
END PROCESS''')
    assert exchange(client, "Gadget", "steel").cost_formula == "0.5 * price"


def test_no_cost_on_an_elementary_flow(session):
    e = err(session, '''
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  OUTPUT "Carbon dioxide, fossil", 1, kg TO AIR COST 2 CURRENCY "EUR"
END PROCESS''')
    assert "costs on product and waste flows only" in e["message"]


# ── exchange site ────────────────────────────────────────────

def test_site_sets_the_exchange_location_not_the_provider(session, client):
    ok(session, f'''
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  INPUT USE PROCESS "{ELECTRICITY}", 2, kWh LOCATION "GB" SITE "DE"
  OUTPUT "Carbon dioxide, fossil", 0.1, kg TO AIR SITE "GB"
END PROCESS''')
    elec = exchange(client, "Gadget", "electricity")
    assert elec.location.name == "Germany"
    provider = client.store["Process"][elec.default_provider.id]
    assert client._location_code(provider.location) == "GB"
    assert exchange(client, "Gadget",
                    "Carbon dioxide").location.name == "United Kingdom"


def test_site_must_be_a_known_location(session, client):
    e = err(session, f'''
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  INPUT USE PROCESS "{STEEL}", 0.5, kg SITE "Atlantis"
END PROCESS''')
    assert e["line"] == 4 and "No location" in e["message"]
    assert client.by_name(o.Process, "Gadget") == []


# ── allocation ───────────────────────────────────────────────

SAWMILL = f'''
MAKE PROCESS "Sawmill"
  OUTPUT MAKE FLOW "Test boards", 1, kg, PRODUCT
  OUTPUT MAKE FLOW "Test chips", 0.4, kg
  INPUT USE PROCESS "{ELECTRICITY}", 2, kWh LOCATION "GB"
  OUTPUT "Carbon dioxide, fossil", 0.1, kg TO AIR
  DEFAULT ALLOCATION PHYSICAL
  ALLOCATION PHYSICAL
    "Test boards", 0.7
    "Test chips", 0.3
  END ALLOCATION
  ALLOCATION ECONOMIC
    "Test boards", 0.9
    "Test chips", 0.1
  END ALLOCATION
END PROCESS
SYSTEM "Sawmill"
'''


def factors(client, name, kind):
    return {(f.product.name, f.exchange.internal_id if f.exchange else None):
            f.value for f in process(client, name).allocation_factors
            if f.allocation_type == kind}


def test_allocation_factors_are_written(session, client):
    ok(session, SAWMILL)
    proc = process(client, "Sawmill")
    assert proc.default_allocation_method == \
        o.AllocationType.PHYSICAL_ALLOCATION
    assert factors(client, "Sawmill", o.AllocationType.PHYSICAL_ALLOCATION) \
        == {("Test boards", None): 0.7, ("Test chips", None): 0.3}
    assert factors(client, "Sawmill", o.AllocationType.ECONOMIC_ALLOCATION) \
        == {("Test boards", None): 0.9, ("Test chips", None): 0.1}


def test_allocation_changes_the_result(session):
    ok(session, SAWMILL)
    whole = 2 * 0.25 + 0.1          # electricity and the direct emission

    def fossil(option):
        r = ok(session, f'CALCULATE "Sawmill" USING "{EF}" {option}')
        return next(i["amount"] for i in r.data[-1]["result"]["impacts"]
                    if i["category"] == FOSSIL)

    assert fossil("ALLOCATE NONE") == pytest.approx(whole)
    assert fossil("ALLOCATE PHYSICAL") == pytest.approx(0.7 * whole)
    assert fossil("ALLOCATE ECONOMIC") == pytest.approx(0.9 * whole)
    assert fossil("") == pytest.approx(0.7 * whole)       # the default


@pytest.mark.parametrize("block,fragment", [
    ('"Test boards", 0.7\n"Test chips", 0.2', "add up to 0.9, not 1"),
    ('"Test boards", 0.7\n"Test chips", 0.4', "add up to 1.1, not 1"),
    ('"Test boards", 1.0', "No PHYSICAL share is given for: 'Test chips'"),
    ('"Test boards", 0.7\n"Test planks", 0.3', "is not a product of this process"),
    ('"Test boards", 1.2\n"Test chips", -0.2', "between 0 and 1"),
    ('"Test boards", 0.5\n"Test boards", 0.5', "two PHYSICAL factors"),
    ('"Test boards", 0.7 FOR INPUT "x"\n"Test chips", 0.3', "per product, not per exchange"),
])
def test_allocation_shares_are_checked(session, client, block, fragment):
    lines = "\n    ".join(block.split("\n"))
    e = err(session, f'''
MAKE PROCESS "Sawmill"
  OUTPUT MAKE FLOW "Test boards", 1, kg, PRODUCT
  OUTPUT MAKE FLOW "Test chips", 0.4, kg
  ALLOCATION PHYSICAL
    {lines}
  END ALLOCATION
END PROCESS''')
    assert fragment in e["message"], e
    assert e["line"] in (6, 7)
    assert client.by_name(o.Process, "Sawmill") == []
    assert client.by_name(o.Flow, "Test boards") == []


def test_shares_within_the_tolerance_pass(session, client):
    ok(session, '''
MAKE PROCESS "Sawmill"
  OUTPUT MAKE FLOW "Test boards", 1, kg, PRODUCT
  OUTPUT MAKE FLOW "Test chips", 0.4, kg
  ALLOCATION PHYSICAL
    "Test boards", 0.3333333
    "Test chips", 0.6666667
  END ALLOCATION
END PROCESS''')
    assert len(process(client, "Sawmill").allocation_factors) == 2


def test_causal_allocation_is_per_exchange(session, client):
    ok(session, f'''
MAKE PROCESS "Sawmill"
  OUTPUT MAKE FLOW "Test boards", 1, kg, PRODUCT
  OUTPUT MAKE FLOW "Test chips", 0.4, kg
  INPUT USE PROCESS "{ELECTRICITY}", 2, kWh LOCATION "GB"
  OUTPUT "Carbon dioxide, fossil", 0.1, kg TO AIR
  ALLOCATION CAUSAL
    "Test boards", 0.8 FOR INPUT "test electricity, medium voltage"
    "Test chips", 0.2 FOR INPUT "test electricity, medium voltage"
    "Test boards", 0.5 FOR OUTPUT "Carbon dioxide, fossil"
    "Test chips", 0.5 FOR OUTPUT "Carbon dioxide, fossil"
  END ALLOCATION
END PROCESS''')
    got = factors(client, "Sawmill", o.AllocationType.CAUSAL_ALLOCATION)
    assert got == {("Test boards", 3): 0.8, ("Test chips", 3): 0.2,
                   ("Test boards", 4): 0.5, ("Test chips", 4): 0.5}


def test_causal_shares_must_add_up_per_exchange(session):
    e = err(session, f'''
MAKE PROCESS "Sawmill"
  OUTPUT MAKE FLOW "Test boards", 1, kg, PRODUCT
  OUTPUT MAKE FLOW "Test chips", 0.4, kg
  INPUT USE PROCESS "{ELECTRICITY}", 2, kWh LOCATION "GB"
  ALLOCATION CAUSAL
    "Test boards", 0.8 FOR INPUT "test electricity, medium voltage"
    "Test chips", 0.3 FOR INPUT "test electricity, medium voltage"
  END ALLOCATION
END PROCESS''')
    assert "for 'test electricity, medium voltage' add up to 1.1" in e["message"]
    e = err(session, '''
MAKE PROCESS "Sawmill"
  OUTPUT MAKE FLOW "Test boards", 1, kg, PRODUCT
  ALLOCATION CAUSAL
    "Test boards", 1
  END ALLOCATION
END PROCESS''')
    assert "causal factor is given per exchange" in e["message"]
    assert "FOR INPUT" in e["hint"]


def test_an_avoided_product_takes_no_share(session):
    e = err(session, f'''
MAKE PROCESS "Sawmill"
  OUTPUT MAKE FLOW "Test boards", 1, kg, PRODUCT
  OUTPUT MAKE FLOW "Test chips", 0.4, kg AVOIDED
  ALLOCATION PHYSICAL
    "Test boards", 0.7
    "Test chips", 0.3
  END ALLOCATION
END PROCESS''')
    assert "'Test chips' is not a product of this process" in e["message"]


def test_allocation_grammar(session):
    assert "ALLOCATION needs a method" in err(session, '''
MAKE PROCESS "S"
  OUTPUT MAKE FLOW "S", 1, kg, PRODUCT
  ALLOCATION
  END ALLOCATION
END PROCESS''')["message"]
    assert "two ALLOCATION PHYSICAL blocks" in err(session, '''
MAKE PROCESS "S"
  OUTPUT MAKE FLOW "S", 1, kg, PRODUCT
  ALLOCATION PHYSICAL
    "S", 1
  END ALLOCATION
  ALLOCATION PHYSICAL
    "S", 1
  END ALLOCATION
END PROCESS''')["message"]
    assert "is not a method" in err(session, '''
MAKE PROCESS "S"
  OUTPUT MAKE FLOW "S", 1, kg, PRODUCT
  DEFAULT ALLOCATION SOMEHOW
END PROCESS''')["message"]
    assert "has no factors" in err(session, '''
MAKE PROCESS "S"
  OUTPUT MAKE FLOW "S", 1, kg, PRODUCT
  ALLOCATION ECONOMIC
  END ALLOCATION
END PROCESS''')["message"]


# ── documentation ────────────────────────────────────────────

DOCUMENTED = '''
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  DOCUMENT
    COMPLETENESS "All inputs above 1% by mass"
    COMPLIANCE "Test standard" COMMENT "Checked" ASPECT "Overall" "Fully compliant"
    COPYRIGHT YES
    CREATED "12/11/2026"
    DATA COLLECTION "Site records"
    DATA SELECTION "One year of production"
    DATA TREATMENT "Averaged over the year"
    DOCUMENTOR "Test author"
    FLOW COMPLETENESS "Climate change" "All relevant flows quantified"
    GENERATOR "Test author"
    GEOGRAPHY "One site in the north"
    INTENDED APPLICATION "A test"
    INVENTORY METHOD "Attributional"
    MODELLING CONSTANTS "None"
    OWNER "Test author"
    PROJECT "Synthetic project"
    PUBLICATION "Test report"
    RESTRICTIONS "None"
    REVIEW "Independent review" REVIEWER "Test reviewer" DETAILS "Passed" REPORT "Test report" SCOPE "Raw data" METHOD "Sample tests" ASSESSMENT "Overall quality" "Good"
    SAMPLING "Every batch"
    SOURCE "Test report"
    SOURCE "Test standard"
    TECHNOLOGY "A test technology"
    TIME "The year 2025"
    USE ADVICE "For tests only"
    VALID FROM "2025-01-01"
    VALID UNTIL "31/12/2030"
  END DOCUMENT
END PROCESS
'''


def test_every_documentation_field_can_be_written(session, client):
    ok(session, DOCUMENTED)
    doc = process(client, "Gadget").process_documentation
    for field_name in DOCUMENT_FIELDS:
        assert getattr(doc, field_name) not in (None, [], ""), field_name
    assert len(DOCUMENT_FIELDS) == 26
    assert doc.creation_date == "2026-11-12"
    assert doc.valid_from == "2025-01-01" and doc.valid_until == "2030-12-31"
    assert doc.is_copyright_protected is True
    assert doc.data_documentor.name == "Test author"
    assert doc.publication.name == "Test report"
    assert [s.name for s in doc.sources] == ["Test report", "Test standard"]
    review = doc.reviews[0]
    assert review.review_type == "Independent review"
    assert [a.name for a in review.reviewers] == ["Test reviewer"]
    assert review.report.name == "Test report" and review.details == "Passed"
    assert review.scopes[0].name == "Raw data"
    assert review.scopes[0].methods == ["Sample tests"]
    assert (review.assessment[0].aspect, review.assessment[0].value) == (
        "Overall quality", "Good")
    decl = doc.compliance_declarations[0]
    assert decl.system.name == "Test standard" and decl.comment == "Checked"
    assert decl.aspects[0].value == "Fully compliant"
    assert doc.flow_completeness[0].aspect == "Climate change"


def test_show_document_reads_every_field_back(session):
    ok(session, DOCUMENTED)
    r = ok(session, 'SHOW PROCESS "Gadget" DOCUMENT')
    for line in DOCUMENTED.split("DOCUMENT\n")[1].split("  END")[0].splitlines():
        want = (line.strip().replace('"12/11/2026"', '"2026-11-12"')
                .replace('"31/12/2030"', '"2030-12-31"'))
        assert want in r.text, want
    data = r.data[-1]["result"]["document"]
    assert set(data) == set(DOCUMENT_FIELDS)


@pytest.mark.parametrize("line,fragment", [
    ('OWNER "Nobody"', "No actor is called 'Nobody'"),
    ('PUBLICATION "Lost report"', "No source is called 'Lost report'"),
    ('SOURCE "Lost report"', "No source is called 'Lost report'"),
    ('VALID FROM "next year"', "is not a date"),
    ('VALID FROM "31/02/2025"', "is not a real date"),
    ('REVIEW "x" REVIEWER "Nobody"', "No actor is called 'Nobody'"),
    ('COMPLIANCE "Lost standard"', "No source is called 'Lost standard'"),
])
def test_documentation_values_are_checked(session, client, line, fragment):
    e = err(session, f'''
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  DOCUMENT
    TIME "2025"
    {line}
  END DOCUMENT
END PROCESS''')
    assert fragment in e["message"] and e["line"] == 6
    assert client.by_name(o.Process, "Gadget") == []
    assert client.by_name(o.Flow, "Gadget") == []


def test_document_grammar(session):
    e = err(session, '''
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  DOCUMENT
    WEATHER "wet"
  END DOCUMENT
END PROCESS''')
    assert "'WEATHER' is not a documentation field" in e["message"]
    assert "VALID UNTIL" in e["hint"] and e["line"] == 5
    e = err(session, '''
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  DOCUMENT
    TIME "2024"
    TIME "2025"
  END DOCUMENT
END PROCESS''')
    assert "given twice" in e["message"] and e["line"] == 6
    e = err(session, '''
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  DOCUMENT
    TIME "2024"
END PROCESS''')
    assert "missing END DOCUMENT" in e["message"]


def test_dates():
    assert parse_date("12/11/2026") == ("2026-11-12", None)
    assert parse_date("2026-11-12") == ("2026-11-12", None)
    assert parse_date("2026-11-12T00:00:00") == ("2026-11-12", None)
    assert parse_date("11/31/2026")[0] is None       # not month first


# ── social aspects ───────────────────────────────────────────

def test_social_aspects_are_written(session, client):
    ok(session, '''
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  SOCIAL SCHEMA "Test Process Quality System"
  SOCIAL "Test working hours", "48 h per week", MEDIUM RISK ACTIVITY 2.5 COMMENT "From the audit" SOURCE "Test report" QUALITY (1,2,3,4)
END PROCESS''')
    proc = process(client, "Gadget")
    a = proc.social_aspects[0]
    assert a.social_indicator.name == "Test working hours"
    assert a.raw_amount == "48 h per week"
    assert a.risk_level == o.RiskLevel.MEDIUM_RISK
    assert a.activity_value == 2.5 and a.comment == "From the audit"
    assert a.source.name == "Test report" and a.quality == "(1;2;3;4)"
    assert proc.social_dq_system.name == "Test Process Quality System"
    r = ok(session, 'SHOW PROCESS "Gadget" SOCIAL')
    assert ('SOCIAL "Test working hours", "48 h per week", MEDIUM RISK '
            'ACTIVITY 2.5') in r.text


@pytest.mark.parametrize("line,fragment", [
    ('SOCIAL "No such indicator", "1", LOW RISK',
     "No social indicator is called"),
    ('SOCIAL "Test working hours", "1", QUITE BAD', "is not a risk level"),
    ('SOCIAL "Test working hours", "1", LOW RISK SOURCE "Lost report"',
     "No source is called"),
    ('SOCIAL SCHEMA "No such system"', "not found"),
])
def test_social_values_are_checked(session, client, line, fragment):
    e = err(session, f'''
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  {line}
END PROCESS''')
    assert fragment in e["message"] and e["line"] == 4
    assert client.by_name(o.Process, "Gadget") == []


def test_risk_levels_are_listed(session):
    e = err(session, '''
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  SOCIAL "Test working hours", "1", QUITE BAD
END PROCESS''')
    assert "VERY HIGH RISK" in e["hint"] and "NO DATA" in e["hint"]


# ── type, infrastructure, process pedigree ───────────────────

def test_type_infrastructure_and_process_pedigree(session, client):
    ok(session, '''
MAKE PROCESS "Gadget"
  TYPE LCI RESULT
  INFRASTRUCTURE
  PROCESS SCHEMA "Test Process Quality System"
  PROCESS PEDIGREE (1,2,3,4)
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
END PROCESS''')
    proc = process(client, "Gadget")
    assert proc.process_type == o.ProcessType.LCI_RESULT
    assert proc.is_infrastructure_process is True
    assert proc.dq_entry == "(1;2;3;4)"


def test_unit_is_the_default_type(session, client):
    ok(session, PLAIN)
    proc = process(client, "Gadget")
    assert proc.process_type == o.ProcessType.UNIT_PROCESS
    assert not proc.is_infrastructure_process


def test_process_pedigree_needs_a_schema_and_the_right_count(session):
    e = err(session, '''
MAKE PROCESS "Gadget"
  PROCESS PEDIGREE (1,2,3,4)
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
END PROCESS''')
    assert "needs a data quality system" in e["message"]
    assert "PROCESS SCHEMA" in e["hint"]


def test_type_grammar(session):
    assert "is not a process type" in err(session, '''
MAKE PROCESS "Gadget"
  TYPE SYSTEM
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
END PROCESS''')["message"]


# ── SHOW reads it all back ───────────────────────────────────

def test_show_process_fields(session):
    ok(session, COSTED.replace("SYSTEM \"Gadget\"", ""))
    ok(session, f'''
EDIT PROCESS "Gadget"
  UPDATE INPUT "{STEEL}" UNCERTAINTY LOGNORMAL 0.5, 1.3 SITE "DE"
  TYPE LCI RESULT
END EDIT''')
    r = ok(session, 'SHOW PROCESS "Gadget" FIELDS')
    assert "TYPE LCI RESULT" in r.text
    assert "UNCERTAINTY LOGNORMAL 0.5, 1.3" in r.text
    assert 'SITE "Germany"' in r.text
    assert 'COST 10.000000 CURRENCY "Euro"' in r.text
    data = r.data[-1]["result"]
    steel = next(e for e in data["exchanges"] if "steel" in e["flow"])
    assert steel["uncertainty"] == {"kind": "LOGNORMAL", "values": [0.5, 1.3],
                                    "text": "LOGNORMAL 0.5, 1.3"}
    assert steel["cost"]["currency"] == "Euro" and steel["site"] == "Germany"
    plain = ok(session, 'SHOW PROCESS "Gadget"')
    assert "Also set: uncertainty on 1 amount, 3 costs, 1 exchange site" \
        in plain.text
    assert 'SHOW PROCESS "Gadget" FIELDS shows them' in plain.text


def test_show_process_says_nothing_extra_for_a_plain_process(session):
    ok(session, PLAIN)
    assert "Also set" not in ok(session, 'SHOW PROCESS "Gadget"').text
    assert "no allocation factors" in ok(
        session, 'SHOW PROCESS "Gadget" ALLOCATION').text
    assert "no social aspects" in ok(
        session, 'SHOW PROCESS "Gadget" SOCIAL').text
    assert "no documentation fields" in ok(
        session, 'SHOW PROCESS "Gadget" DOCUMENT').text


def test_show_allocation(session):
    ok(session, SAWMILL)
    text = ok(session, 'SHOW PROCESS "Sawmill" ALLOCATION').text
    assert 'ALLOCATION PHYSICAL' in text and '"Test boards", 0.7' in text
    assert 'ALLOCATION ECONOMIC' in text and '"Test chips", 0.1' in text


# ── EDIT PROCESS ─────────────────────────────────────────────

def test_edit_sets_and_removes_exchange_fields(session, client):
    ok(session, PLAIN)
    r = ok(session, f'''
EDIT PROCESS "Gadget"
  UPDATE INPUT "{STEEL}" UNCERTAINTY NORMAL 0.5, 0.05 COST 2 CURRENCY "EUR" SITE "GB"
END EDIT''')
    assert "uncertainty set to NORMAL 0.5, 0.05" in r.text
    assert "cost set to 2 Euro" in r.text
    steel = exchange(client, "Gadget", "steel")
    assert steel.uncertainty.sd == 0.05 and steel.cost_value == 2
    ok(session, f'''
EDIT PROCESS "Gadget"
  UPDATE INPUT "{STEEL}" UNCERTAINTY NONE NO COST NO SITE
END EDIT''')
    steel = exchange(client, "Gadget", "steel")
    assert steel.uncertainty is None and steel.cost_value is None
    assert steel.currency is None and steel.location is None


def test_edit_can_change_an_amount_and_its_uncertainty_together(
        session, client):
    ok(session, PLAIN)
    ok(session, f'''
EDIT PROCESS "Gadget"
  UPDATE INPUT "{STEEL}", 0.6, kg UNCERTAINTY UNIFORM 0.5, 0.7
END EDIT''')
    steel = exchange(client, "Gadget", "steel")
    assert steel.amount == 0.6 and steel.uncertainty.maximum == 0.7


def test_edit_added_exchanges_carry_their_fields(session, client):
    ok(session, PLAIN)
    ok(session, f'''
EDIT PROCESS "Gadget"
  ADD OUTPUT MAKE FLOW "Test offcuts", 0.2, kg AVOIDED COST 1 CURRENCY "EUR"
  ADD INPUT USE PROCESS "{STEEL}", 0.1, kg UNCERTAINTY UNIFORM 0.05, 0.15
END EDIT''')
    offcuts = exchange(client, "Gadget", "offcuts")
    assert offcuts.is_avoided_product and offcuts.cost_value == 1
    proc = process(client, "Gadget")
    steel = [ex for ex in proc.exchanges
             if "steel" in client._flow_name(ex.flow.id)]
    assert [ex.uncertainty is not None for ex in steel] == [False, True]


def test_edit_refuses_before_writing_anything(session, client):
    ok(session, PLAIN)
    e = err(session, f'''
EDIT PROCESS "Gadget"
  ADD OUTPUT MAKE FLOW "Test offcuts", 0.2, kg
  UPDATE INPUT "{STEEL}", 0.9, kg UNCERTAINTY LOGNORMAL 0.5, 0.5
END EDIT''')
    assert e["line"] == 4 and "above 1" in e["message"]
    assert client.by_name(o.Flow, "Test offcuts") == []
    assert exchange(client, "Gadget", "steel").amount_formula   # unchanged
    assert len(process(client, "Gadget").exchanges) == 4


def test_edit_allocation_replaces_and_removes(session, client):
    ok(session, SAWMILL)
    ok(session, '''
EDIT PROCESS "Sawmill"
  ALLOCATION PHYSICAL
    "Test boards", 0.6
    "Test chips", 0.4
  END ALLOCATION
  REMOVE ALLOCATION ECONOMIC
  DEFAULT ALLOCATION NONE
END EDIT''')
    assert factors(client, "Sawmill", o.AllocationType.PHYSICAL_ALLOCATION) \
        == {("Test boards", None): 0.6, ("Test chips", None): 0.4}
    assert factors(client, "Sawmill",
                   o.AllocationType.ECONOMIC_ALLOCATION) == {}
    assert process(client, "Sawmill").default_allocation_method == \
        o.AllocationType.NO_ALLOCATION
    ok(session, 'EDIT PROCESS "Sawmill"\n  REMOVE ALLOCATION\nEND EDIT')
    assert not process(client, "Sawmill").allocation_factors


def test_edit_allocation_sees_added_products(session, client):
    ok(session, PLAIN)
    ok(session, '''
EDIT PROCESS "Gadget"
  ADD OUTPUT MAKE FLOW "Test swarf", 0.1, kg
  ALLOCATION PHYSICAL
    "Gadget", 0.95
    "Test swarf", 0.05
  END ALLOCATION
END EDIT''')
    assert len(process(client, "Gadget").allocation_factors) == 2


def test_edit_document_sets_only_what_it_names(session, client):
    ok(session, DOCUMENTED)
    ok(session, '''
EDIT PROCESS "Gadget"
  DOCUMENT
    TIME "The year 2026"
    COPYRIGHT NO
  END DOCUMENT
END EDIT''')
    doc = process(client, "Gadget").process_documentation
    assert doc.time_description == "The year 2026"
    assert doc.is_copyright_protected is False
    assert doc.geography_description == "One site in the north"


def test_edit_social_type_and_parameter_uncertainty(session, client):
    ok(session, PLAIN)
    name = next(p.name for p in process(client, "Gadget").parameters
                if "stee" in p.name)
    ok(session, f'''
EDIT PROCESS "Gadget"
  SOCIAL "Test working hours", 40, LOW RISK
  TYPE LCI RESULT
  INFRASTRUCTURE YES
  UPDATE PARAM {name} UNCERTAINTY UNIFORM 0.4, 0.6
  ADD PARAM extra = 2 UNCERTAINTY NORMAL 2, 0.1
END EDIT''')
    proc = process(client, "Gadget")
    assert proc.social_aspects[0].raw_amount == "40"
    assert proc.process_type == o.ProcessType.LCI_RESULT
    assert proc.is_infrastructure_process
    by = {p.name: p for p in proc.parameters}
    assert by[name].uncertainty.maximum == 0.6
    assert by["extra"].uncertainty.sd == 0.1
    ok(session, '''
EDIT PROCESS "Gadget"
  REMOVE SOCIAL "Test working hours"
  INFRASTRUCTURE NO
  TYPE UNIT
END EDIT''')
    proc = process(client, "Gadget")
    assert proc.social_aspects == [] and not proc.is_infrastructure_process
    assert proc.process_type == o.ProcessType.UNIT_PROCESS
    e = err(session, 'EDIT PROCESS "Gadget"\n  REMOVE SOCIAL "Test working hours"\nEND EDIT')
    assert "no social aspect" in e["message"]


def test_edit_with_nothing_still_says_so(session):
    ok(session, PLAIN)
    assert "Nothing to change" in ok(
        session, 'EDIT PROCESS "Gadget"\nEND EDIT').text


# ── flows ────────────────────────────────────────────────────

def test_make_flow_fields(session, client):
    ok(session, 'MAKE FLOW "Test formalin", kg, PRODUCT CAS "50-00-0" '
                'FORMULA "CH2O" SYNONYMS "methanal; formol" '
                'DESCRIPTION "A test chemical" LOCATION "GB" INFRASTRUCTURE')
    flow = client.by_name(o.Flow, "Test formalin")[0]
    assert (flow.cas, flow.formula, flow.synonyms) == (
        "50-00-0", "CH2O", "methanal; formol")
    assert flow.description == "A test chemical"
    assert flow.location.name == "United Kingdom"
    assert flow.is_infrastructure_flow is True
    r = ok(session, 'SHOW FLOW "Test formalin" FIELDS')
    assert "50-00-0" in r.text and "CH2O" in r.text and "YES" in r.text
    assert r.data[-1]["result"]["synonyms"] == "methanal; formol"


def test_make_flow_fields_are_not_forced_on_an_existing_flow(session, client):
    ok(session, 'MAKE FLOW "Test formalin", kg, PRODUCT CAS "50-00-0"')
    r = ok(session, 'MAKE FLOW "Test formalin", kg, PRODUCT CAS "1-1-1"')
    assert "were not written" in r.text
    assert client.by_name(o.Flow, "Test formalin")[0].cas == "50-00-0"


def test_edit_flow_fields(session, client):
    ok(session, 'MAKE FLOW "Test formalin", kg, PRODUCT CAS "50-00-0" LOCATION "GB"')
    r = ok(session, '''
EDIT FLOW "Test formalin"
  SET CAS "50-00-1"
  SET FORMULA "CH2O"
  SET SYNONYMS "methanal"
  SET LOCATION NONE
  SET INFRASTRUCTURE YES
END EDIT''')
    assert "cas set to '50-00-1'" in r.text and "location removed" in r.text
    flow = client.by_name(o.Flow, "Test formalin")[0]
    assert (flow.cas, flow.formula, flow.synonyms) == ("50-00-1", "CH2O",
                                                       "methanal")
    assert flow.location is None and flow.is_infrastructure_flow
    e = err(session, 'EDIT FLOW "Test formalin"\n  SET LOCATION "Atlantis"\nEND EDIT')
    assert "No location" in e["message"]


# ── product systems: linking, parameter sets, groups ─────────

def test_linking_options(session, client):
    ok(session, PLAIN + '''
SYSTEM "Gadget"
  LINKING IGNORE_DEFAULTS
  PREFER SYSTEM PROCESSES
  CUTOFF 0.001
END SYSTEM''')
    call = next(c for c in client.calls if c[0] == "create_product_system")
    assert call
    config = client.linking_configs[-1]
    assert config.provider_linking == o.ProviderLinking.IGNORE_DEFAULTS
    assert config.prefer_unit_processes is False and config.cutoff == 0.001


def test_only_link_providers_is_only_defaults(session, client):
    ok(session, PLAIN + 'SYSTEM "Gadget"\n  LINKING ONLY_LINK_PROVIDERS\nEND SYSTEM')
    assert client.linking_configs[-1].provider_linking == \
        o.ProviderLinking.ONLY_DEFAULTS
    assert client.linking_configs[-1].prefer_unit_processes is True


def test_cutoff_is_a_fraction(session):
    e = err(session, PLAIN + 'SYSTEM "Gadget"\n  CUTOFF 5\nEND SYSTEM')
    assert "fraction from 0 to below 1" in e["message"]


SYSTEM_WITH_SETS = f'''
LET steel_kg = 0.5
MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  INPUT USE PROCESS "{ELECTRICITY}", 2, kWh LOCATION "GB"
  INPUT USE PROCESS "{STEEL}", steel_kg, kg
END PROCESS
SYSTEM "Gadget"
  PARAMETER SET "Light" BASELINE
    steel_kg = 0.4
  END PARAMETER SET
  PARAMETER SET "Heavy" DESCRIPTION "A thicker casing"
    steel_kg = 1
  END PARAMETER SET
  ANALYSIS GROUP "Energy"
    "{ELECTRICITY}" LOCATION "GB"
  END ANALYSIS GROUP
  ANALYSIS GROUP "Materials" COLOUR "#2e0a4a"
    "{STEEL}"
  END ANALYSIS GROUP
END SYSTEM
'''


def fossil_of(r):
    return next(i["amount"] for i in r.data[-1]["result"]["impacts"]
                if i["category"] == FOSSIL)


def test_parameter_sets_and_groups_are_stored(session, client):
    ok(session, SYSTEM_WITH_SETS)
    system = client.by_name(o.ProductSystem, "Gadget")[0]
    sets = {s.name: s for s in system.parameter_sets}
    assert sets["Light"].is_baseline and not sets["Heavy"].is_baseline
    assert sets["Heavy"].description == "A thicker casing"
    assert [(r.name, r.value, r.context) for r in sets["Heavy"].parameters] \
        == [("steel_kg", 1.0, None)]
    groups = {g.name: g for g in system.analysis_groups}
    assert len(groups["Energy"].processes) == 1
    assert groups["Materials"].color == "#2e0a4a"


def test_the_baseline_set_is_what_a_plain_calculate_uses(session):
    ok(session, SYSTEM_WITH_SETS)
    assert fossil_of(ok(session, f'CALCULATE "Gadget" USING "{EF}"')) == \
        pytest.approx(2 * 0.25 + 0.4 * 2.0)
    assert fossil_of(ok(session, f'CALCULATE "Gadget" USING "{EF}" '
                                 f'PARAMETER SET "Heavy"')) == \
        pytest.approx(2 * 0.25 + 1 * 2.0)
    e = err(session, f'CALCULATE "Gadget" USING "{EF}" PARAMETER SET "Lost"')
    assert "has no parameter set called 'Lost'" in e["message"]
    assert '"Heavy"' in e["hint"] and '"Light"' in e["hint"]


def test_run_scenarios_from_system(session):
    ok(session, SYSTEM_WITH_SETS)
    r = ok(session, f'RUN SCENARIOS ON "Gadget" USING "{EF}" FROM SYSTEM')
    results = r.data[-1]["result"]["results"]
    assert set(results) == {"Light", "Heavy"}
    by = {name: next(i["amount"] for i in rows if i["category"] == FOSSIL)
          for name, rows in results.items()}
    assert by["Light"] == pytest.approx(1.3)
    assert by["Heavy"] == pytest.approx(2.5)
    assert "Light" in r.text and "Heavy" in r.text


def test_run_scenarios_from_system_needs_sets(session):
    ok(session, PLAIN + 'SYSTEM "Gadget"')
    e = err(session, f'RUN SCENARIOS ON "Gadget" USING "{EF}" FROM SYSTEM')
    assert "has no parameter sets stored on it" in e["message"]


def test_groups_feed_result_by_group(session):
    ok(session, SYSTEM_WITH_SETS)
    r = ok(session, f'CALCULATE "Gadget" USING "{EF}" PARAMETER SET "Heavy"\n'
                    f'RESULT IMPACTS BY GROUP CATEGORY "{FOSSIL}"')
    by = {row["group"]: row["amount"] for row in r.data[-1]["result"]["rows"]}
    assert by["Energy"] == pytest.approx(0.5)
    assert by["Materials"] == pytest.approx(2.0)


def test_show_system_sets_and_groups(session):
    ok(session, SYSTEM_WITH_SETS)
    text = ok(session, 'SHOW SYSTEM "Gadget" SETS').text
    assert 'PARAMETER SET "Light" BASELINE' in text
    assert "steel_kg = 0.4" in text and 'PARAMETER SET "Heavy"' in text
    text = ok(session, 'SHOW SYSTEM "Gadget" GROUPS').text
    assert 'ANALYSIS GROUP "Energy"' in text and STEEL in text


def test_edit_system(session, client):
    ok(session, SYSTEM_WITH_SETS)
    r = ok(session, f'''
EDIT SYSTEM "Gadget"
  PARAMETER SET "Heavy" BASELINE
    steel_kg = 2
  END PARAMETER SET
  REMOVE ANALYSIS GROUP "Materials"
  ANALYSIS GROUP "Energy"
    "{ELECTRICITY}" LOCATION "GB"
    "{STEEL}"
  END ANALYSIS GROUP
  SET DESCRIPTION "Edited"
END EDIT''')
    assert "parameter set 'Heavy' replaced (1 parameter, baseline)" in r.text
    assert "parameter set 'Light' is no longer the baseline" in r.text
    assert "analysis group 'Materials' removed" in r.text
    system = client.by_name(o.ProductSystem, "Gadget")[0]
    assert [s.name for s in system.parameter_sets if s.is_baseline] == ["Heavy"]
    assert [g.name for g in system.analysis_groups] == ["Energy"]
    assert len(system.analysis_groups[0].processes) == 2
    assert system.description == "Edited"
    ok(session, 'EDIT SYSTEM "Gadget"\n  REMOVE PARAMETER SET "Light"\nEND EDIT')
    assert [s.name for s in client.by_name(
        o.ProductSystem, "Gadget")[0].parameter_sets] == ["Heavy"]


@pytest.mark.parametrize("body,fragment,line", [
    ('PARAMETER SET "A"\n  nothing_kg = 1\nEND PARAMETER SET',
     "has no parameter 'nothing_kg'", 3),
    ('PARAMETER SET "A" BASELINE\n  steel_kg = 1\nEND PARAMETER SET\n'
     'PARAMETER SET "B" BASELINE\n  steel_kg = 2\nEND PARAMETER SET',
     "Only one parameter set can be the BASELINE", 2),
    ('ANALYSIS GROUP "G"\n  "No such process"\nEND ANALYSIS GROUP',
     "No process called 'No such process'", 3),
    ('ANALYSIS GROUP "G"\nEND ANALYSIS GROUP', "names no process", 2),
    ('REMOVE PARAMETER SET "Lost"', "has no parameter set 'Lost'", 1),
    ('REMOVE ANALYSIS GROUP "Lost"', "has no analysis group 'Lost'", 1),
    (f'ANALYSIS GROUP "Other"\n  "{STEEL}"\nEND ANALYSIS GROUP',
     "already in the analysis group 'Materials'", 3),
])
def test_edit_system_refusals(session, client, body, fragment, line):
    ok(session, SYSTEM_WITH_SETS)
    before = client.by_name(o.ProductSystem, "Gadget")[0].to_dict()
    e = err(session, f'EDIT SYSTEM "Gadget"\n{body}\nEND EDIT')
    assert fragment in e["message"], e
    assert e["line"] == line
    assert client.by_name(o.ProductSystem, "Gadget")[0].to_dict() == before


def test_a_process_shared_by_name_needs_a_location_in_a_group(session):
    ok(session, f'''
MAKE PROCESS "Two grids"
  OUTPUT MAKE FLOW "Two grids", 1, kg, PRODUCT
  INPUT USE PROCESS "{ELECTRICITY}", 1, kWh LOCATION "GB"
  INPUT USE PROCESS "{ELECTRICITY}", 1, kWh LOCATION "DE"
END PROCESS
SYSTEM "Two grids"''')
    e = err(session, f'''
EDIT SYSTEM "Two grids"
  ANALYSIS GROUP "Power"
    "{ELECTRICITY}"
  END ANALYSIS GROUP
END EDIT''')
    assert "matches 2 processes" in e["message"] and "LOCATION" in e["hint"]


def test_a_parameter_of_one_process_only(session, client):
    ok(session, PLAIN + 'SYSTEM "Gadget"')
    name = next(p.name for p in process(client, "Gadget").parameters
                if "stee" in p.name)
    ok(session, f'''
EDIT SYSTEM "Gadget"
  PARAMETER SET "More steel"
    {name} = 1 IN PROCESS "Gadget"
  END PARAMETER SET
END EDIT''')
    redef = client.by_name(o.ProductSystem, "Gadget")[0] \
        .parameter_sets[0].parameters[0]
    assert redef.context.name == "Gadget" and redef.value == 1
    r = ok(session, f'CALCULATE "Gadget" USING "{EF}" PARAMETER SET "More steel"')
    assert fossil_of(r) == pytest.approx(2 * 0.25 + 1 * 2.0 + 0.1)
    e = err(session, f'''
EDIT SYSTEM "Gadget"
  PARAMETER SET "Odd"
    {name} = 1 IN PROCESS "Another"
  END PARAMETER SET
END EDIT''')
    assert "No process called 'Another'" in e["message"]


def test_dry_run_accepts_the_new_blocks(session):
    r = session.run(DOCUMENTED + SAWMILL + SYSTEM_WITH_SETS, dry_run=True)
    assert r.ok, r.errors
