"""PARAMETERISE PROCESS: fixed amounts of a database process become
parameters. It is irreversible, so it is refused without CONFIRM."""

import olca_schema as o
import pytest

from fake_client import ELECTRICITY, seed_ecoinvent_like
from olcabasic import Session
from olcabasic.parser import ParseError, parse

MIX = "test grid mix, two sources"
METHOD = "IPCC 2021"
GWP = "Climate change: fossil - Global warming potential (GWP100)"


def _provider(client, location):
    return next(p for p in client.store["Process"].values()
                if p.name == ELECTRICITY and p.location is not None
                and client._location_code(p.location) == location)


@pytest.fixture
def client():
    """The synthetic database plus a 'market mix' with two fixed shares
    and one emission."""
    c = seed_ecoinvent_like()
    elec = next(f for f in c.store["Flow"].values()
                if f.name == "test electricity, medium voltage")
    co2 = next(f for f in c.store["Flow"].values()
               if f.name == "Carbon dioxide, fossil")
    out = c.add_flow("test grid mix", "Energy", category="D:Test supply")
    kwh = c._unit_ref("kWh")
    kg = c._unit_ref("kg")

    def ref(flow):
        return o.Ref(id=flow.id, name=flow.name, ref_type=o.RefType.Flow)

    def link(n, location, share):
        p = _provider(c, location)
        return o.Exchange(
            internal_id=n, amount=share, is_input=True, flow=ref(elec),
            unit=kwh, is_quantitative_reference=False,
            default_provider=o.Ref(id=p.id, name=p.name,
                                   ref_type=o.RefType.Process))
    proc = o.Process(
        id="mix-0001", name=MIX, category="D:Test supply",
        process_type=o.ProcessType.UNIT_PROCESS, last_internal_id=4,
        exchanges=[
            o.Exchange(internal_id=1, amount=1.0, is_input=False,
                       flow=ref(out), unit=kwh,
                       is_quantitative_reference=True),
            link(2, "GB", 0.6), link(3, "DE", 0.4),
            o.Exchange(internal_id=4, amount=0.001, is_input=False,
                       flow=ref(co2), unit=kg,
                       is_quantitative_reference=False),
        ])
    c.put(proc)
    return c


@pytest.fixture
def session(client):
    return Session(client=client)


def mix(client):
    return client.store["Process"]["mix-0001"]


def gwp(session):
    r = session.run(f'CALCULATE "{MIX}" USING "{METHOD}"')
    assert r.ok, r.errors
    return next(i["amount"] for i in r.data[-1]["result"]["impacts"]
                if i["category"] == GWP)


def test_it_is_refused_without_confirm(session, client):
    r = session.run(f'PARAMETERISE PROCESS "{MIX}"')
    assert not r.ok
    err = r.errors[0]
    assert "refused without CONFIRM" in err["message"]
    assert "2 fixed amounts" in err["message"]
    assert "cannot be undone" in err["message"]
    assert "Back up the database" in err["hint"]
    assert f'PARAMETERISE PROCESS "{MIX}" CONFIRM' in err["hint"]
    assert not mix(client).parameters
    assert all(not ex.amount_formula for ex in mix(client).exchanges)


def test_with_confirm_the_amounts_become_parameters(session, client):
    r = session.run(f'PARAMETERISE PROCESS "{MIX}" CONFIRM')
    assert r.ok, r.errors
    assert any("cannot be undone" in w["message"] for w in r.warnings)
    assert "2 fixed amounts replaced with parameters" in r.text
    proc = mix(client)
    values = sorted(p.value for p in proc.parameters)
    assert values == [0.4, 0.6]
    linked = [ex for ex in proc.exchanges if ex.default_provider]
    names = {p.name for p in proc.parameters}
    assert {ex.amount_formula for ex in linked} == names
    assert len(names) == 2
    for p in proc.parameters:
        assert p.is_input_parameter
        assert p.parameter_scope == o.ParameterScope.PROCESS_SCOPE


def test_elementary_flows_and_the_reference_are_left_alone(session, client):
    r = session.run(f'PARAMETERISE PROCESS "{MIX}" CONFIRM')
    proc = mix(client)
    qref = next(ex for ex in proc.exchanges if ex.is_quantitative_reference)
    emission = next(ex for ex in proc.exchanges if ex.internal_id == 4)
    assert not qref.amount_formula and not emission.amount_formula
    assert "1 elementary flows are left as fixed amounts" in r.text
    assert r.data[-1]["result"]["elementary_left"] == 1


def test_results_are_unchanged_until_a_parameter_is_varied(session, client):
    assert session.run(f'SYSTEM "{MIX}"').ok
    before = gwp(session)
    assert before > 0
    assert session.run(f'PARAMETERISE PROCESS "{MIX}" CONFIRM').ok
    assert gwp(session) == pytest.approx(before)
    gb = next(p.name for p in mix(client).parameters if p.value == 0.6)
    r = session.run(f'''SENSITIVITY ON "{MIX}" USING "{METHOD}" BY 50%
  VARY {gb}
END SENSITIVITY''')
    assert r.ok, r.errors
    assert gb in r.text


def test_a_second_run_finds_nothing_to_do(session, client):
    session.run(f'PARAMETERISE PROCESS "{MIX}" CONFIRM')
    r = session.run(f'PARAMETERISE PROCESS "{MIX}" CONFIRM')
    assert r.ok
    assert "Nothing to parameterise" in r.text
    assert len(mix(client).parameters) == 2


def test_a_shared_name_needs_a_location(session, client):
    r = session.run(f'PARAMETERISE PROCESS "{ELECTRICITY}" CONFIRM')
    assert not r.ok
    assert "matches 3 processes" in r.errors[0]["message"]
    assert "LOCATION" in r.errors[0]["hint"]


def test_a_location_picks_one_and_a_bare_dataset_has_nothing_to_change(
        session, client):
    r = session.run(f'PARAMETERISE PROCESS "{ELECTRICITY}" LOCATION "GB" CONFIRM')
    assert r.ok, r.errors
    assert "Nothing to parameterise" in r.text


def test_a_uuid_works(session, client):
    r = session.run('PARAMETERISE PROCESS "mix-0001" CONFIRM')
    assert r.ok, r.errors
    assert len(mix(client).parameters) == 2


def test_an_unknown_process_is_an_error(session):
    r = session.run('PARAMETERISE PROCESS "no such process" CONFIRM')
    assert not r.ok
    assert "No process is called" in r.errors[0]["message"]
    assert "FIND PROCESS" in r.errors[0]["hint"]


def test_the_american_spelling_is_an_alias(session, client):
    assert session.run(f'PARAMETERIZE PROCESS "{MIX}" CONFIRM').ok
    assert len(mix(client).parameters) == 2


def test_dry_run_refuses_without_confirm_and_writes_nothing(session, client):
    r = session.run(f'PARAMETERISE PROCESS "{MIX}"', dry_run=True)
    assert not r.ok and "refused without CONFIRM" in r.errors[0]["message"]
    r = session.run(f'PARAMETERISE PROCESS "{MIX}" CONFIRM', dry_run=True)
    assert r.ok
    assert not mix(client).parameters


def test_it_needs_a_name():
    with pytest.raises(ParseError, match="needs the name or UUID"):
        parse("PARAMETERISE PROCESS")


def test_the_word_is_not_reserved(session):
    r = session.run("LET parameterise = 3\nPRINT parameterise + 1")
    assert r.ok and "4" in r.text


def test_the_engine_reports_without_writing(client):
    from olcabasic.engine import Engine
    plan = Engine(client).parameterise_process("mix-0001", dry_run=True)
    assert plan["parameterised"] == 2 and plan["written"] is False
    assert [p["value"] for p in plan["parameters"]] == [0.6, 0.4]
    assert not mix(client).parameters
