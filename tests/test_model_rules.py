"""
The remaining places where a model could be built wrongly without an
error (second rebuild, design 3.1). Each is a refusal with a line and a
hint, and leaves the database as it was.

    1  every background input goes through a bridge   (test_enforcement.py)
    2  a PROCESS block run again must still match the stored process
    3  a product system is stale after one of its processes changes
    4  one EPD module may not use another module's process  (test_epd.py)
    5  an OUTPUT line does not create a flow by itself
    6  a new elementary flow must have a characterisation factor
    7  Monte Carlo needs uncertainty
    8  allocation needs factors
"""

import pytest
import olca_schema as o

from olcabasic import Session
from test_interpreter_lca import (B_ELEC, B_ELEC_DE, B_STEEL, B_WATER,
                                  BRIDGES, SETUP, WIDGET)

EF = "EF v3.1"


@pytest.fixture
def session(client):
    return Session(client=client)


def err(result):
    assert not result.ok, result.text
    return result.errors[0]


def snapshot(client):
    """What the database holds, to show a refusal wrote nothing."""
    return {kind: {uid: e.to_dict() for uid, e in table.items()}
            for kind, table in client.store.items()}


def line_of(code: str, text: str) -> int:
    for n, line in enumerate(code.splitlines(), 1):
        if text in line:
            return n
    raise AssertionError(f"{text!r} is not in the program")


def widget(**changes):
    """The Widget block, with lines swapped: widget(steel='0.9')."""
    lines = {
        "elec": f'  INPUT USE PROCESS "{B_ELEC}", elec, kWh',
        "steel": f'  INPUT USE PROCESS "{B_STEEL}", 0.8, kg',
        "co2": '  OUTPUT "Carbon dioxide, fossil", 0.5, kg TO AIR',
        "extra": None, "head": None,
    }
    lines.update(changes)
    body = "\n".join(v for v in lines.values() if v)
    return (SETUP + BRIDGES + 'LET elec = 2.5\nMAKE PROCESS "Widget"\n'
            + '  OUTPUT MAKE FLOW "Widget", 1, kg, PRODUCT\n'
            + body + "\nEND PROCESS\n")


# ── rule 2: a block run again must match ─────────────────────

def test_an_identical_block_is_a_quiet_no_op(session, client):
    assert session.run(widget()).ok
    before = snapshot(client)
    r = session.run(widget())
    assert r.ok, r.errors
    assert "Process exists and matches this block: Widget" in r.text
    assert not [w for w in r.warnings if "Widget" in w["message"]
                and w["level"] == "warning"]
    assert snapshot(client) == before


@pytest.mark.parametrize("changes, said", [
    ({"steel": f'  INPUT USE PROCESS "{B_STEEL}", 0.9, kg'},
     'INPUT "BRIDGE | steel | kg": amount is 0.8 in the database and 0.9 '
     'in the block.'),
    ({"steel": f'  INPUT USE PROCESS "{B_STEEL}", elec * 2, kg'},
     'INPUT "BRIDGE | steel | kg": amount is 0.8 in the database and '
     "'(elec*2.0)' in the block."),
    ({"steel": None},
     'INPUT "BRIDGE | steel | kg" is in the database and not in the block.'),
    ({"extra": f'  INPUT USE PROCESS "{B_WATER}", 3, kg'},
     'INPUT "BRIDGE | water | kg" is in the block and not in the database.'),
    ({"elec": f'  INPUT USE PROCESS "{B_ELEC_DE}", elec, kWh'},
     "is in the block and not in the database."),
    ({"co2": '  OUTPUT "Carbon dioxide, fossil", 0.7, kg TO AIR'},
     'OUTPUT "Carbon dioxide, fossil": amount is 0.5 in the database and '
     '0.7 in the block.'),
    ({"steel": f'  INPUT USE PROCESS "{B_STEEL}", 0.8, kg '
               f'UNCERTAINTY NORMAL 0.8, 0.1'},
     "uncertainty is nothing in the database and NORMAL 0.8, 0.1 in the "
     "block."),
    ({"steel": f'  INPUT USE PROCESS "{B_STEEL}", 0.8, kg COMMENT "new"'},
     "comment is nothing in the database and 'new' in the block."),
    ({"head": '  LET scrap = 0.1'},
     "Parameter scrap is in the block and not in the database."),
    ({"head": '  DESCRIPTION "A changed description"'},
     "The DESCRIPTION differs from the one in the database."),
    ({"head": '  INFRASTRUCTURE'},
     "Infrastructure is False in the database and True in the block."),
])
def test_a_changed_block_is_refused_and_lists_the_difference(
        session, client, changes, said):
    assert session.run(widget()).ok
    before = snapshot(client)
    code = widget(**changes)
    e = err(session.run(code))
    assert e["line"] == line_of(code, 'MAKE PROCESS "Widget"')
    assert "differs from this block" in e["message"]
    assert said in e["message"], e["message"]
    assert 'EDIT PROCESS "Widget"' in e["hint"]
    assert 'DELETE PROCESS "Widget"' in e["hint"]
    assert snapshot(client) == before


def test_several_differences_are_all_listed(session, client):
    assert session.run(widget()).ok
    e = err(session.run(widget(
        steel=f'  INPUT USE PROCESS "{B_STEEL}", 1.1, kg',
        co2='  OUTPUT "Carbon dioxide, fossil", 0.6, kg TO AIR')))
    assert "in 2 places" in e["message"]
    assert "1.1 in the block" in e["message"]
    assert "0.6 in the block" in e["message"]


def test_a_block_that_no_longer_matches_after_an_edit_is_refused(
        session, client):
    """The database changed, not the block: the same rule."""
    assert session.run(widget()).ok
    r = session.run(f'EDIT PROCESS "Widget"\n'
                    f'  UPDATE INPUT "{B_STEEL}", 1.5, kg\nEND EDIT')
    assert r.ok, r.errors
    e = err(session.run(widget()))
    assert "amount is 1.5 in the database and 0.8 in the block" in e["message"]


def test_after_delete_the_changed_block_builds(session, client):
    assert session.run(widget()).ok
    changed = widget(steel=f'  INPUT USE PROCESS "{B_STEEL}", 0.9, kg')
    assert not session.run(changed).ok
    r = session.run('CONFIRM DELETE ON\nDELETE PROCESS "Widget"\n' + changed)
    assert r.ok, r.errors
    proc = client.by_name(o.Process, "Widget")[0]
    assert any(p.value == 0.9 for p in proc.parameters)


def test_a_changed_data_line_is_refused(session, client):
    data = '  DATA PRIMARY SOURCE "Meter" PROVIDER "Site" YEAR 2024'
    assert session.run(widget(head=data)).ok
    assert session.run(widget(head=data)).ok
    e = err(session.run(widget(head=data.replace("2024", "2025"))))
    assert "DATA ... YEAR: 2024 in the database and 2025 in the block" \
        in e["message"]


def test_parameterise_does_not_make_the_block_differ(session, client):
    """PARAMETERISE turns amounts into parameters and changes no value."""
    assert session.run(widget()).ok
    r = session.run('PARAMETERISE PROCESS "Widget" CONFIRM')
    assert r.ok, r.errors
    r = session.run(widget())
    assert r.ok, r.errors


# ── rule 5: OUTPUT does not create a flow ────────────────────

def test_an_output_that_matches_no_flow_is_refused(session, client):
    before = snapshot(client)
    code = SETUP + '''MAKE PROCESS "Mill"
  OUTPUT MAKE FLOW "Flour", 1, kg, PRODUCT
  OUTPUT "Bran", 0.2, kg
END PROCESS'''
    e = err(session.run(code))
    assert e["line"] == line_of(code, 'OUTPUT "Bran"')
    assert "No flow is called 'Bran'" in e["message"]
    assert 'OUTPUT MAKE FLOW "Bran", amount, kg' in e["hint"]
    # nothing was written: not the process, not the product flow
    assert snapshot(client) == before


def test_output_make_flow_still_creates_it(session, client):
    r = session.run(SETUP + '''MAKE PROCESS "Mill"
  OUTPUT MAKE FLOW "Flour", 1, kg, PRODUCT
  OUTPUT MAKE FLOW "Bran", 0.2, kg
END PROCESS''')
    assert r.ok, r.errors
    assert len(client.by_name(o.Flow, "Bran")) == 1


# ── rule 3: stale product systems ────────────────────────────

BUILT = widget() + 'SYSTEM "Widget"\nVALIDATE "Widget"\n'
CALC = f'CALCULATE "Widget" USING "{EF}"'
REBUILD = 'CONFIRM DELETE ON\nDELETE SYSTEM "Widget"\nSYSTEM "Widget"\n'


def stale(session, code=CALC):
    e = err(session.run(code))
    assert "is out of date" in e["message"], e["message"]
    assert 'DELETE SYSTEM "Widget"' in e["hint"]
    assert 'VALIDATE "Widget"' in e["hint"]
    return e


@pytest.mark.parametrize("change, why", [
    (f'EDIT PROCESS "Widget"\n  UPDATE INPUT "{B_STEEL}", 1.5, kg\nEND EDIT',
     "EDIT PROCESS"),
    (f'LINK PROCESS "{B_WATER}" TO PROCESS "Widget" WITH 3, kg', "LINK"),
    ('MOVE PROCESS "Widget" TO "00: Test/Moved"', "MOVE"),
])
def test_a_changed_process_makes_its_systems_stale(session, client, change,
                                                   why):
    assert session.run(BUILT).ok
    assert session.run(CALC).ok
    r = session.run(change)
    assert r.ok, r.errors
    assert 'product system "Widget" contains \'Widget\' and is now out of ' \
           'date' in r.text
    e = stale(session)
    assert e["line"] == 1 and f"({why})" in e["message"]
    # the result that was open no longer matches the model and is gone
    assert session.open_results == []


def test_parameterise_makes_its_systems_stale(session, client):
    """(Widget has nothing left to parameterise: olcaBASIC built it. A
    process with fixed amounts is in test_parameterise.py, which checks
    the same refusal.)"""
    assert session.run(BUILT).ok
    r = session.run('PARAMETERISE PROCESS "Widget" CONFIRM')
    assert r.ok and "Nothing to parameterise" in r.text
    assert session.run(CALC).ok              # nothing changed: not stale


def test_every_calculating_command_refuses_a_stale_system(session, client):
    assert session.run(BUILT).ok
    assert session.run(f'EDIT PROCESS "Widget"\n'
                       f'  UPDATE INPUT "{B_STEEL}", 1.5, kg\nEND EDIT').ok
    for code in (
            CALC,
            f'CONTRIBUTION "Widget" USING "{EF}"',
            f'INVENTORY "Widget" USING "{EF}"',
            f'MONTECARLO "Widget" USING "{EF}" RUNS 3',
            f'SENSITIVITY ON "Widget" USING "{EF}" BY 10%\n  VARY elec\n'
            f'END SENSITIVITY',
            f'SCENARIO "S"\n  LET elec = 3\nEND SCENARIO\n'
            f'RUN SCENARIOS ON "Widget" USING "{EF}"',
            f'TREE "Widget" USING "{EF}" CATEGORY "Climate change"'):
        stale(session, code)


def test_a_stale_system_must_be_rebuilt_and_validated(session, client):
    assert session.run(BUILT).ok
    assert session.run(f'EDIT PROCESS "Widget"\n'
                       f'  UPDATE INPUT "{B_STEEL}", 1.5, kg\nEND EDIT').ok
    # SYSTEM on its own reuses the old system: still stale
    assert session.run('SYSTEM "Widget"').ok
    stale(session)
    # rebuilt, but not validated yet
    assert session.run(REBUILD).ok
    e = err(session.run(CALC))
    assert "has not passed VALIDATE since" in e["message"]
    assert 'VALIDATE "Widget"' in e["hint"]
    # validated: the calculation runs, on the changed process
    r = session.run('VALIDATE "Widget"\n' + CALC)
    assert r.ok, r.errors
    fossil = next(i["amount"] for i in r.data[-1]["result"]["impacts"]
                  if "fossil" in i["category"])
    assert fossil == pytest.approx(2.5 * 0.25 + 1.5 * 2.0 + 0.5)


def test_a_declaration_or_a_description_does_not_make_a_system_stale(
        session, client):
    assert session.run(BUILT).ok
    r = session.run('EDIT PROCESS "Widget"\n'
                    '  DATA PRIMARY SOURCE "Meter" PROVIDER "Site" YEAR 2024\n'
                    'END EDIT\n'
                    'EDIT PROCESS "Widget"\n  SET DESCRIPTION "Words"\n'
                    'END EDIT\n'
                    'EDIT PROCESS "Widget"\n  DOCUMENT\n'
                    '    TECHNOLOGY "A press"\n  END DOCUMENT\nEND EDIT')
    assert r.ok, r.errors
    assert "out of date" not in r.text
    assert session.run(CALC).ok


def test_only_the_systems_that_hold_the_process_are_stale(session, client):
    assert session.run(BUILT).ok
    other = SETUP + f'''MAKE PROCESS "Gadget"
  OUTPUT MAKE FLOW "Gadget", 1, kg, PRODUCT
  INPUT USE PROCESS "{B_STEEL}", 2, kg
END PROCESS
SYSTEM "Gadget"
'''
    assert session.run(other).ok
    assert session.run(f'EDIT PROCESS "Gadget"\n'
                       f'  UPDATE INPUT "{B_STEEL}", 3, kg\nEND EDIT').ok
    assert session.run(CALC).ok
    e = err(session.run(f'CALCULATE "Gadget" USING "{EF}"'))
    assert "'Gadget' is out of date" in e["message"]


def test_editing_a_bridge_makes_every_system_through_it_stale(session,
                                                              client):
    assert session.run(BUILT).ok
    r = session.run(f'EDIT PROCESS "{B_STEEL}"\n'
                    f'  UPDATE INPUT "test steel, low-alloyed", 1.2, kg\n'
                    f'END EDIT')
    assert r.ok, r.errors
    stale(session)


# ── rule 6: a new elementary flow needs a factor ─────────────

GAS = '  OUTPUT MAKE FLOW "Mystery gas", 0.1, kg TO AIR'


def test_a_new_emission_without_a_factor_is_refused(session, client):
    code = widget(extra=GAS) + 'SYSTEM "Widget"\n' + CALC
    e = err(session.run(code))
    assert e["line"] == line_of(code, "CALCULATE")
    assert f"'{EF}' has no characterisation factor for 'Mystery gas'" \
        in e["message"]
    assert "which this program created" in e["message"]
    assert 'IGNORE FACTORS "Mystery gas"' in e["hint"]
    assert client.undisposed() == 0


def test_every_calculating_command_checks_the_factors(session, client):
    assert session.run(widget(extra=GAS) + 'SYSTEM "Widget"\n').ok
    for code in (f'CONTRIBUTION "Widget" USING "{EF}"',
                 f'INVENTORY "Widget" USING "{EF}"',
                 f'MONTECARLO "Widget" USING "{EF}" RUNS 3',
                 f'TREE "Widget" USING "{EF}" CATEGORY "Climate change"'):
        e = err(session.run(code))
        assert "no characterisation factor for 'Mystery gas'" in e["message"]


def test_ignore_factors_accepts_it_and_the_output_says_so(session, client):
    assert session.run(widget(extra=GAS) + 'SYSTEM "Widget"\n').ok
    r = session.run(CALC + ' IGNORE FACTORS "Mystery gas"')
    assert r.ok, r.errors
    assert "'Mystery gas' has no characterisation factor in 'EF v3.1' and " \
           "adds nothing to these results (accepted with IGNORE FACTORS)" \
        in r.text
    # accepted for the session and this method: later commands run,
    # and say so again
    r = session.run(f'CONTRIBUTION "Widget" USING "{EF}"')
    assert r.ok, r.errors
    assert "accepted with IGNORE FACTORS" in r.text
    # another method has not been accepted
    e = err(session.run('CALCULATE "Widget" USING "IPCC 2021"'))
    assert "'IPCC 2021' has no characterisation factor" in e["message"]


def test_ignore_factors_needs_something_to_ignore(session, client):
    assert session.run(widget(extra=GAS) + 'SYSTEM "Widget"\n').ok
    e = err(session.run(CALC + ' IGNORE FACTORS "Carbon dioxide, fossil"'))
    assert "there is nothing to ignore" in e["message"]
    assert "not an elementary flow this program created" in e["message"]
    assert '"Mystery gas"' in e["hint"]


def test_a_flow_from_an_earlier_session_is_still_checked(client):
    """The flow carries the tag olcaBASIC, so a second session that
    runs the same program finds it."""
    first = Session(client=client)
    assert first.run(widget(extra=GAS) + 'SYSTEM "Widget"\n').ok
    first.close()
    flow = client.by_name(o.Flow, "Mystery gas")[0]
    assert flow.tags == ["olcaBASIC"]
    second = Session(client=client)
    assert second.run(widget(extra=GAS)).ok        # identical: no-op
    e = err(second.run(CALC))
    assert "no characterisation factor for 'Mystery gas'" in e["message"]
    second.close()


def test_a_factor_in_the_method_lets_it_through(session, client):
    assert session.run(widget(extra=GAS) + 'SYSTEM "Widget"\n').ok
    r = session.run('''MAKE METHOD "Own method"
  CATEGORY "Mystery" UNIT "kg gas eq"
    FACTOR "Mystery gas", 2
  END CATEGORY
END METHOD
CALCULATE "Widget" USING "Own method"''')
    assert r.ok, r.errors
    amount = r.data[-1]["result"]["impacts"][0]["amount"]
    assert amount == pytest.approx(0.2)


def test_existing_emissions_are_not_checked(session, client):
    """Only flows olcaBASIC created: a database flow the method does
    not characterise is the method's business."""
    code = widget(extra='  OUTPUT "Phosphate", 0.01, kg TO WATER')
    r = session.run(code + 'SYSTEM "Widget"\nCALCULATE "Widget" USING '
                           '"IPCC 2021"')
    assert r.ok, r.errors


# ── rule 7: Monte Carlo needs uncertainty ────────────────────

MC = f'MONTECARLO "Widget" USING "{EF}" RUNS 5'


def test_montecarlo_with_nothing_uncertain_is_refused(session, client):
    code = widget() + 'SYSTEM "Widget"\n' + MC
    e = err(session.run(code))
    assert e["line"] == line_of(code, "MONTECARLO")
    assert "nothing in 'Widget' is uncertain" in e["message"]
    assert "two trial runs gave the same results" in e["message"]
    assert "UNCERTAINTY LOGNORMAL gm, gsd" in e["hint"]
    # two trial runs, not five, and the simulation was disposed
    assert client.results[-1]._run == 2
    assert client.undisposed() == 0


def test_montecarlo_runs_when_the_background_is_uncertain(session, client):
    """Nothing uncertain in the foreground, but the trial runs differ:
    the database has its own uncertainty."""
    client.mc_jitter = 0.05
    r = session.run(widget() + 'SYSTEM "Widget"\n' + MC)
    assert r.ok, r.errors
    assert r.data[-1]["result"]["iterations"] == 5


def test_montecarlo_runs_with_uncertainty_on_an_exchange(session, client):
    r = session.run(widget(
        steel=f'  INPUT USE PROCESS "{B_STEEL}", 0.8, kg '
              f'UNCERTAINTY TRIANGLE 0.6, 0.8, 1.0')
        + 'SYSTEM "Widget"\n' + MC)
    assert r.ok, r.errors
    stats = r.data[-1]["result"]["statistics"]
    assert any(s["std_dev"] > 0 for s in stats.values())


def test_uncertainty_that_changes_nothing_still_runs_and_says_so(session,
                                                                 client):
    """Both conditions are needed for the refusal. A parameter with a
    distribution that no amount depends on is uncertainty in the
    foreground, so the runs go ahead, and the result says they were
    all the same."""
    r = session.run(widget(
        head='  LET scrap = 0.1 UNCERTAINTY UNIFORM 0.05, 0.15')
        + 'SYSTEM "Widget"\n' + MC)
    assert r.ok, r.errors
    result = r.data[-1]["result"]
    assert result["iterations"] == 5
    assert "zero variance" in result["warning"]


def test_montecarlo_runs_with_an_uncertain_global(session, client):
    code = widget().replace("LET elec = 2.5",
                            "LET elec = 2.5 UNCERTAINTY UNIFORM 2, 3")
    r = session.run(code + 'SYSTEM "Widget"\n' + MC)
    assert r.ok, r.errors


# ── rule 8: allocation needs factors ─────────────────────────

CO = '  OUTPUT MAKE FLOW "Offcut", 0.2, kg'
SHARES = '''  ALLOCATION {kind}
    "Widget", 0.9
    "Offcut", 0.1
  END ALLOCATION'''


@pytest.mark.parametrize("kind", ["PHYSICAL", "ECONOMIC"])
def test_allocation_without_factors_is_refused(session, client, kind):
    code = (widget(extra=CO) + 'SYSTEM "Widget"\n'
            + CALC + f' ALLOCATE {kind}')
    e = err(session.run(code))
    assert e["line"] == line_of(code, "CALCULATE")
    assert "'Widget' has 2 products (\"Widget\", \"Offcut\")" in e["message"]
    assert f"no {kind} allocation factors" in e["message"]
    assert f"ALLOCATION {kind}" in e["hint"] and "ALLOCATE NONE" in e["hint"]
    assert client.undisposed() == 0


@pytest.mark.parametrize("kind", ["PHYSICAL", "ECONOMIC"])
def test_allocation_with_factors_runs(session, client, kind):
    code = (widget(extra=CO + "\n" + SHARES.format(kind=kind))
            + 'SYSTEM "Widget"\n' + CALC + f' ALLOCATE {kind}')
    r = session.run(code)
    assert r.ok, r.errors


def test_factors_for_the_other_method_do_not_count(session, client):
    code = (widget(extra=CO + "\n" + SHARES.format(kind="PHYSICAL"))
            + 'SYSTEM "Widget"\n' + CALC + ' ALLOCATE ECONOMIC')
    e = err(session.run(code))
    assert "no ECONOMIC allocation factors" in e["message"]


def test_no_allocation_and_single_products_are_not_checked(session, client):
    r = session.run(widget(extra=CO) + 'SYSTEM "Widget"\n'
                    + CALC + ' ALLOCATE NONE')
    assert r.ok, r.errors
    assert session.run(REBUILD.replace("Widget", "Widget")).ok
    single = Session(client=client)
    r = single.run(f'CALCULATE "Widget" USING "{EF}" ALLOCATE NONE')
    assert r.ok, r.errors
    single.close()


def test_the_default_method_of_a_process_is_checked_too(session, client):
    """ALLOCATE left out means 'as set in each process': a process set
    to physical allocation with no physical factors is the same gap."""
    code = (widget(extra=CO + "\n  DEFAULT ALLOCATION PHYSICAL\n"
                   + SHARES.format(kind="ECONOMIC"))
            + 'SYSTEM "Widget"\n' + CALC)
    e = err(session.run(code))
    assert "no PHYSICAL allocation factors" in e["message"]


def test_other_commands_check_allocation_too(session, client):
    assert session.run(widget(extra=CO) + 'SYSTEM "Widget"\n').ok
    e = err(session.run(f'CONTRIBUTION "Widget" USING "{EF}" '
                        f'ALLOCATE PHYSICAL'))
    assert "no PHYSICAL allocation factors" in e["message"]
