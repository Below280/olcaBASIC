"""
Live tests: the rules that stop a wrong model (second rebuild, design
3.1) against a real openLCA.

    pytest -m live

One small model in the folder "00: olcaBASIC live rules": a process
with two products, electricity through a bridge (the provider is taken
from the private baseline program) and an emission that olcaBASIC
creates, which no method characterises.

The system and the process are deleted at the end. The flows, the
bridge and the global parameter stay and are reused by the next run
(see test_live_baseline.py for why).
"""

import re

import pytest

from test_live_baseline import close

pytestmark = pytest.mark.live

FOLDER = "00: olcaBASIC live rules"
NAME = "olcaBASIC live rules product"
CO = "olcaBASIC live rules co-product"
GAS = "olcaBASIC live rules gas"
PARAM = "olcabasic_live_rules_kwh"
BRIDGE_SHORT = "olcaBASIC live rules electricity"
BRIDGE = f"BRIDGE | {BRIDGE_SHORT} | kWh"


def block(amount="2"):
    return f'''MAKE PROCESS "{NAME}"
  OUTPUT MAKE FLOW "{NAME}", 1, kg, PRODUCT
  OUTPUT MAKE FLOW "{CO}", 0.5, kg
  INPUT USE PROCESS "{BRIDGE}", {amount}, kWh
  OUTPUT MAKE FLOW "{GAS}", 0.1, kg TO AIR
END PROCESS
'''


REBUILD = (f'CLOSE RESULT ALL\nCONFIRM DELETE ON\nDELETE SYSTEM "{NAME}"\n'
           f'SYSTEM "{NAME}"\n')


@pytest.fixture(scope="module")
def model(runner, baseline):
    m = re.search(r'USE PROCESS "([^"]+)".*kWh LOCATION "([^"]+)"',
                  baseline["program_template"])
    if not m:
        pytest.skip("the baseline program has no electricity input to use")
    name, location = m.groups()
    method = next(iter(baseline["calculate"]))
    cleanup = (f'CLOSE RESULT ALL\nCONFIRM DELETE ON\n'
               f'DELETE SYSTEM "{NAME}"\nDELETE PROCESS "{NAME}"')
    runner.session.run(cleanup)
    if runner.engine.database_family not in ("ecoinvent", "flcac"):
        runner.run('DATABASE FAMILY "ecoinvent"')
    head = f'''SET PROCESS FOLDER "{FOLDER}"
SET FLOW FOLDER "{FOLDER}"
BRIDGE "{BRIDGE_SHORT}", kWh
  PROVIDER "{name}" LOCATION "{location}"
END BRIDGE
'''
    r = runner.session.run(head + block() + f'SYSTEM "{NAME}"\n'
                           f'VALIDATE "{NAME}"\n')
    assert r.ok, f"{r.errors}\n{r.text}"
    yield {"method": method, "head": head}
    runner.session.run(cleanup)


def refused(runner, code):
    r = runner.session.run(code)
    assert not r.ok, r.text
    return r.errors[0]


def gwp(result, model):
    """The first impact that is not zero."""
    return next(i["amount"] for i in result["impacts"]
                if abs(i["amount"]) > 1e-12)


def test_the_new_emission_is_tagged_and_has_no_factor(runner, model):
    import olca_schema as o
    client = runner.engine.client
    flow = next(d for d in client.get_descriptors(o.Flow) if d.name == GAS)
    assert "olcaBASIC" in (client.get(o.Flow, flow.id).tags or [])
    e = refused(runner, f'CALCULATE "{NAME}" USING "{model["method"]}" '
                        f'ALLOCATE NONE')
    assert f"no characterisation factor for '{GAS}'" in e["message"]
    assert f'IGNORE FACTORS "{GAS}"' in e["hint"]
    assert runner.session.open_results == []


def test_ignore_factors_lets_it_run_and_says_so(runner, model):
    r = runner.session.run(
        f'CALCULATE "{NAME}" USING "{model["method"]}" ALLOCATE NONE '
        f'IGNORE FACTORS "{GAS}"')
    assert r.ok, r.errors
    assert "accepted with IGNORE FACTORS" in r.text
    model["base"] = gwp(r.data[-1]["result"], model)
    assert model["base"] > 0


def test_allocation_without_factors_is_refused(runner, model):
    for kind in ("PHYSICAL", "ECONOMIC"):
        e = refused(runner, f'CALCULATE "{NAME}" USING "{model["method"]}" '
                            f'ALLOCATE {kind}')
        assert f"'{NAME}' has 2 products" in e["message"]
        assert f"no {kind} allocation factors" in e["message"]


def test_an_identical_block_is_a_no_op_and_a_changed_one_is_refused(
        runner, model):
    r = runner.session.run(model["head"] + block())
    assert r.ok, r.errors
    assert f"Process exists and matches this block: {NAME}" in r.text
    e = refused(runner, model["head"] + block("3"))
    assert "differs from this block in 1 place" in e["message"]
    assert "amount is 2 in the database and 3 in the block" in e["message"]
    # nothing was marked: the process did not change
    assert runner.session.run(
        f'CALCULATE "{NAME}" USING "{model["method"]}" ALLOCATE NONE').ok


def test_montecarlo_takes_two_trial_runs_first(runner, model):
    """Nothing in this foreground is uncertain. The background data
    decides: with uncertainty in it the runs go ahead, without it the
    command is refused. Either way the simulation is disposed."""
    r = runner.session.run(
        f'MONTECARLO "{NAME}" USING "{model["method"]}" RUNS 3 ALLOCATE NONE')
    if r.ok:
        got = r.data[-1]["result"]
        assert got["iterations"] == 3
        assert any(s["std_dev"] > 0 for s in got["statistics"].values())
    else:
        assert "nothing in" in r.errors[0]["message"]
        assert "UNCERTAINTY" in r.errors[0]["hint"]


def test_an_edit_makes_the_system_stale_until_rebuilt_and_validated(
        runner, model):
    r = runner.session.run(f'EDIT PROCESS "{NAME}"\n'
                           f'  UPDATE INPUT "{BRIDGE}", 4, kWh\nEND EDIT')
    assert r.ok, r.errors
    assert "is now out of date" in r.text
    calc = f'CALCULATE "{NAME}" USING "{model["method"]}" ALLOCATE NONE'
    e = refused(runner, calc)
    assert "is out of date" in e["message"] and "EDIT PROCESS" in e["message"]
    assert runner.session.run(REBUILD).ok
    e = refused(runner, calc)
    assert "has not passed VALIDATE since" in e["message"]
    r = runner.session.run(f'VALIDATE "{NAME}"\n{calc}')
    assert r.ok, r.errors
    # twice the electricity, twice the impact (the gas adds nothing)
    assert close(gwp(r.data[-1]["result"], model), 2 * model["base"], 1e-6)
