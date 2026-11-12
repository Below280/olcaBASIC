"""Session: output capture, persistent state, the lock, dry run and
structured errors."""

import threading
import time

import pytest
import olca_schema as o

from fake_client import ELECTRICITY, STEEL, seed_ecoinvent_like
from olcabasic import RunResult, Session
from test_interpreter_lca import (B_STEEL, BRIDGES, SETUP, WIDGET,
                                  WIDGET_FOSSIL)


def line_of(program: str, text: str) -> int:
    """The line a piece of text is on (1-based)."""
    return program[:program.index(text)].count("\n") + 1


@pytest.fixture
def session(client):
    return Session(client=client)


# ── RunResult ────────────────────────────────────────────────

def test_run_returns_a_run_result(session):
    r = session.run('PRINT "hello"')
    assert isinstance(r, RunResult)
    assert r.ok and bool(r) and r.text == "  hello"
    assert r.data == [] and r.errors == [] and r.warnings == []
    assert r.to_dict() == {"ok": True, "text": "  hello", "data": [],
                           "errors": [], "warnings": []}


def test_text_is_what_the_terminal_would_show(session, run):
    code = 'LET a = 2\nPRINT a * 3\nFIND PROCESS "test steel"\nPWD'
    assert session.run(code).text + "\n" == run(code)


def test_nothing_is_printed(session, capsys):
    session.run(WIDGET + 'CALCULATE "Widget" USING "EF v3.1"')
    assert capsys.readouterr().out == ""


def test_data_holds_structured_results(session):
    r = session.run(WIDGET + 'CALCULATE "Widget" USING "EF v3.1"')
    assert r.ok
    calls = [(d["command"], d["call"]) for d in r.data]
    assert ("PROCESS", "create_process") in calls
    assert ("SYSTEM", "create_system") in calls
    calc = r.data[-1]
    assert calc["command"] == "CALCULATE"
    assert calc["line"] == WIDGET.count("\n") + 1
    fossil = next(i for i in calc["result"]["impacts"]
                  if i["category"] == "Climate change: fossil")
    assert fossil["amount"] == pytest.approx(WIDGET_FOSSIL)


def test_every_kind_of_result_reaches_data(session):
    session.run(WIDGET)
    r = session.run('''
VALIDATE "Widget"
CONTRIBUTION "Widget" USING "IPCC 2021" TOP 3
INVENTORY "Widget" USING "EF v3.1"
MONTECARLO "Widget" USING "IPCC 2021" RUNS 3
SENSITIVITY ON "Widget" USING "IPCC 2021" BY 10%
  VARY elec
END SENSITIVITY
SCENARIO "S"
  LET elec = 4
END SCENARIO
RUN SCENARIOS ON "Widget" USING "IPCC 2021"
TREE "Widget" USING "EF v3.1" CATEGORY "Climate change"
SHOW PROCESS "Widget"
PRINT DATABASE
FIND FLOW "test water"''')
    assert r.ok, r.errors
    assert [d["command"] for d in r.data] == [
        "VALIDATE", "CONTRIBUTION", "INVENTORY", "MONTE CARLO", "SENSITIVITY",
        "RUN SCENARIOS", "TREE", "SHOW", "PRINT", "FIND"]


def test_warnings_and_notes_are_structured(session):
    session.run(WIDGET)
    r = session.run(WIDGET)
    warning = next(w for w in r.warnings if w["level"] == "warning")
    assert "process 'Widget' already exists" in warning["message"]
    assert warning["line"] == line_of(WIDGET, 'MAKE PROCESS "Widget"')
    assert any(w["level"] == "note" for w in r.warnings)
    assert "WARNING: process 'Widget' already exists" in r.text


# ── state persists across run calls ──────────────────────────

def test_variables_persist(session):
    session.run("LET mass = 12")
    assert session.run("PRINT mass * 2").text == "  24"
    assert session.variables["mass"] == 12.0


def test_folders_confirm_and_subs_persist(session, client):
    session.run('CONFIRM DELETE ON\nSET PROCESS FOLDER "00: Kept"\n'
                'SUB hello()\nPRINT "hi"\nEND SUB')
    r = session.run(f'''hello
MAKE PROCESS "Kept"
  OUTPUT MAKE FLOW "Kept", 1, kg, PRODUCT
END PROCESS
DELETE PROCESS "Kept"''')
    assert r.ok, r.errors
    assert "hi" in r.text and "Deleted: Kept" in r.text


def test_scenarios_and_results_persist(session):
    session.run(WIDGET + 'SCENARIO "Low"\n  LET elec = 1\nEND SCENARIO')
    r = session.run('RUN SCENARIOS ON "Widget" USING "IPCC 2021"')
    assert r.ok and "Low" in r.data[-1]["result"]["results"]
    assert "Low" in session.run("PRINT RESULTS").text
    assert session.last_results is not None


def test_reset_clears_state_not_the_database(session, client):
    session.run(WIDGET)
    session.reset()
    assert session.variables == {}
    assert not session.runtime.confirm_delete
    assert not session.run("PRINT elec").ok
    assert len(client.by_name(o.Process, "Widget")) == 1


def test_two_sessions_do_not_share_state(client):
    a, b = Session(client=client), Session(client=client)
    a.run("LET x = 1")
    assert not b.run("PRINT x").ok


# ── offline and connection ───────────────────────────────────

def test_offline_session_runs_basic_and_refuses_the_rest():
    s = Session(offline=True)
    assert not s.connected and s.engine is None and s.client is None
    assert s.run("PRINT 2 + 2").text == "  4"
    r = s.run('PRINT "before"\nFIND PROCESS "cement"\nPRINT "after"')
    assert not r.ok
    assert r.errors == [{
        "line": 2, "message": "Not connected to openLCA.",
        "hint": "Open a database in openLCA, start the IPC server (Tools > "
                "Developer Tools > IPC Server), then run this again."}]
    assert "before" in r.text and "after" not in r.text


def test_session_exposes_engine_and_client(session, client):
    assert session.connected
    assert session.client is client
    assert session.engine.get_database_info()["status"] == "connected"


def test_session_without_openlca_reports_not_connected():
    s = Session(port=1)          # nothing listens there
    assert not s.connected
    r = s.run('PRINT DATABASE')
    assert not r.ok and r.errors[0]["message"] == "Not connected to openLCA."


# ── the lock ─────────────────────────────────────────────────

def test_run_holds_the_lock_for_its_whole_duration(session, client):
    """A second run() waits for the first, so engine calls from two
    programs never interleave."""
    session.run(WIDGET)
    original = client.calculate
    active, overlaps = [0], []

    def slow_calculate(setup):
        active[0] += 1
        overlaps.append(active[0])
        time.sleep(0.05)
        try:
            return original(setup)
        finally:
            active[0] -= 1

    client.calculate = slow_calculate
    results = []

    def worker():
        results.append(session.run('CALCULATE "Widget" USING "EF v3.1"'))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(r.ok for r in results) and len(results) == 4
    assert max(overlaps) == 1


def test_lock_is_held_while_running_and_free_afterwards(session, client):
    seen = []
    original = client.get_descriptors

    def spy(model_type):
        other = threading.Thread(
            target=lambda: seen.append(session.lock.acquire(blocking=False)))
        other.start()
        other.join()
        return original(model_type)

    client.get_descriptors = spy
    session.run('FIND PROCESS "test steel"')
    assert seen and not any(seen)
    assert session.lock.acquire(blocking=False)
    session.lock.release()


def test_lock_is_reentrant_for_the_owner(session):
    with session.lock:
        assert session.run("PRINT 1").ok


# ── structured errors ────────────────────────────────────────

def test_error_has_line_message_and_hint(session):
    r = session.run('PRINT 1\nPRINT missing')
    assert not r.ok
    assert r.errors == [{
        "line": 2, "message": "'missing' is not a defined variable.",
        "hint": 'If you meant a name, put it in quotes: "missing"'}]
    assert "Error: Line 2:" in r.text


def test_parse_error_is_structured(session):
    r = session.run('PRINT 1\nLET process = 5')
    assert not r.ok and r.errors[0]["line"] == 2
    assert "reserved word" in r.errors[0]["message"]
    assert r.text.startswith("Parse error: Line 2:")


def test_program_stops_at_the_first_error(session):
    r = session.run('PRINT "a"\nPRINT nope\nPRINT "b"')
    assert len(r.errors) == 1 and '"b"' not in r.text and "  b" not in r.text


def test_error_inside_process_block_reports_its_own_line(session):
    program = SETUP + BRIDGES + f'''MAKE PROCESS "Lines"
  OUTPUT MAKE FLOW "Lines", 1, kg, PRODUCT
  INPUT USE PROCESS "{B_STEEL}", 1, kg
  INPUT USE PROCESS "no such process", 1, kg
END PROCESS'''
    r = session.run(program)
    # the INPUT line, not the line the block starts on
    assert r.errors[0]["line"] == line_of(program, "no such process")
    assert "No process found matching 'no such process'" in r.errors[0]["message"]
    assert "FIND PROCESS" in r.errors[0]["hint"]


def test_failed_process_block_creates_nothing(session, client):
    session.run(SETUP + '''MAKE PROCESS "Atomic"
  OUTPUT MAKE FLOW "Atomic", 1, kg, PRODUCT
  INPUT USE PROCESS "no such process", 1, kg
END PROCESS''')
    assert client.by_name(o.Flow, "Atomic") == []
    assert client.by_name(o.Process, "Atomic") == []


def test_engine_refusal_in_a_block_names_the_exchange_line(session, client):
    program = SETUP + BRIDGES + f'''MAKE PROCESS "Units"
  OUTPUT MAKE FLOW "Units", 1, kg, PRODUCT
  INPUT USE PROCESS "{B_STEEL}", 1, kWh
END PROCESS'''
    r = session.run(program)
    assert r.errors[0]["line"] == line_of(program, "1, kWh")
    assert "unit 'kWh' isn't available" in r.errors[0]["message"]
    # the flow made on line 6 is still there, and the error says so
    assert len(client.by_name(o.Flow, "Units")) == 1
    assert 'stay in the database ("Units")' in r.errors[0]["hint"]


def test_undefined_variable_inside_a_block_reports_its_line(session):
    program = SETUP + BRIDGES + f'''MAKE PROCESS "Vars"
  OUTPUT MAKE FLOW "Vars", 1, kg, PRODUCT
  INPUT USE PROCESS "{B_STEEL}", undefined_amount, kg
END PROCESS'''
    r = session.run(program)
    assert r.errors[0]["line"] == line_of(program, "undefined_amount")
    assert "'undefined_amount' is not a defined variable" in r.errors[0]["message"]


def test_error_inside_edit_block_reports_its_own_line(session):
    session.run(WIDGET)
    r = session.run('''EDIT PROCESS "Widget"
  SET DESCRIPTION "x"
  REMOVE INPUT "not there"
END EDIT''')
    assert r.errors[0]["line"] == 3
    r = session.run(f'''EDIT PROCESS "Widget"
  SET DESCRIPTION "x"

  ADD INPUT USE PROCESS "missing process", 1, kg
END EDIT''')
    assert r.errors[0]["line"] == 4


def test_error_inside_scenario_block_reports_its_own_line(session):
    r = session.run('''LET a = 1
LET b = a * 2
SCENARIO "S"
  LET a = 2
  LET b = 5
END SCENARIO''')
    assert r.errors[0]["line"] == 5
    assert "'b' is calculated from a" in r.errors[0]["message"]
    assert r.errors[0]["hint"] == "Change a instead."


def test_error_inside_sensitivity_block_reports_its_own_line(session):
    session.run(WIDGET + "LET double = elec * 2")
    r = session.run('''SENSITIVITY ON "Widget" USING "IPCC 2021" BY 10%
  VARY elec
  VARY double
END SENSITIVITY''')
    assert r.errors[0]["line"] == 3
    assert "'double' is calculated from elec" in r.errors[0]["message"]


def test_engine_errors_carry_the_statement_line(session):
    session.run(WIDGET)
    r = session.run('PRINT 1\nCALCULATE "Widget" USING "No such method"')
    assert r.errors == [{
        "line": 2, "message": "No impact method is called 'No such method'.",
        "hint": "PRINT METHODS lists every impact method in the database."}]


def test_unexpected_exception_becomes_an_error(session, client):
    session.run(WIDGET)
    client.fail_next["calculate"] = RuntimeError("openLCA went away")
    r = session.run('CALCULATE "Widget" USING "EF v3.1"')
    assert not r.ok and r.errors[0]["message"] == "openLCA went away"
    assert r.errors[0]["line"] == 1


def test_nothing_can_be_asked_in_a_session(session):
    session.run(WIDGET + "CONFIRM DELETE OFF")
    r = session.run('DELETE PROCESS "Widget"')
    assert not r.ok
    assert "nobody is there to give one" in r.errors[0]["message"]
    assert r.errors[0]["hint"] == "Put CONFIRM DELETE ON before the DELETE line."
    r = session.run('INPUT "How many?", n')
    assert not r.ok and "needs an answer from the keyboard" in r.errors[0]["message"]
    r = session.run("NAVIGATE")
    assert not r.ok and "NAVIGATE PROCESSES" in r.errors[0]["hint"]


def test_split_hint():
    from olcabasic.errors import split_hint
    assert split_hint("One sentence only") == ("One sentence only", "")
    assert split_hint("It broke. Do this instead.") == (
        "It broke.", "Do this instead.")
    assert split_hint("No 'a. B' here. Try FIND.") == (
        "No 'a. B' here.", "Try FIND.")
    assert split_hint("It isn't there. Look again.") == (
        "It isn't there.", "Look again.")
    assert split_hint("Use 1.5 kg") == ("Use 1.5 kg", "")


# ── dry run ──────────────────────────────────────────────────

def test_dry_run_touches_nothing(session, client):
    before = len(client.calls)
    r = session.run(WIDGET + 'CALCULATE "Widget" USING "EF v3.1"', dry_run=True)
    assert r.ok
    assert len(client.calls) == before
    assert client.by_name(o.Process, "Widget") == []
    assert "elec" not in session.variables


def test_dry_run_summary(session):
    r = session.run(WIDGET + 'CALCULATE "Widget" USING "EF v3.1"', dry_run=True)
    summary = r.data[0]["result"]
    assert r.data[0]["command"] == "DRY RUN"
    assert summary["statements"] == 12      # five of them are bridges
    assert summary["would_write"][-2:] == ['MAKE PROCESS "Widget"',
                                           'SYSTEM "Widget"']
    assert len(summary["would_write"]) == 7
    assert summary["would_calculate"] == ["CALCULATE"]
    assert "Nothing was sent to openLCA" in r.text


def test_dry_run_reports_parse_errors(session):
    r = session.run('PRINT 1\nCALCULATE "W"', dry_run=True)
    assert not r.ok and r.errors[0]["line"] == 2
    assert "Expected USING" in r.errors[0]["message"]


@pytest.mark.parametrize("code,line,needle", [
    ("PRINT 1\nPRINT nope", 2, "'nope' is not a defined variable"),
    ("mystery 1, 2", 1, "SUB 'mystery' is not defined"),
    ("PRINT nofunc(1)", 1, "Unknown function: nofunc"),
    ('DELETE PROCESS "X"', 1, "DELETE would stop and ask"),
    ('INPUT "n?", n', 1, "INPUT waits for the keyboard"),
    ("NAVIGATE", 1, "shows a menu"),
    ('RUN "no_such_file.baslca"', 1, "File not found: no_such_file.baslca"),
    ('RUN SCENARIOS ON "W" USING "M"', 1, "No scenarios defined"),
    ('LET a = 1\nLET b = a * 2\nSCENARIO "S"\n  LET b = 3\nEND SCENARIO', 4,
     "'b' is calculated from other variables"),
    ('LET a = 1\nLET b = a * 2\nSENSITIVITY ON "W" USING "M" BY 5\n  VARY a\n'
     '  VARY b\nEND SENSITIVITY', 5, "can't be varied"),
    ('CALCULATE "W" USING "M" ALLOCATE MAGIC', 1, "Unknown allocation method"),
    ('PROCESS "P"\n  INPUT "a", 1, kg\nEND PROCESS', 1, "has no reference product"),
    ('PROCESS "P"\n  OUTPUT MAKE FLOW "a", 1, kg, PRODUCT\n'
     '  OUTPUT MAKE FLOW "b", 1, kg, PRODUCT\nEND PROCESS', 3,
     "2 exchanges marked PRODUCT"),
    ('SENSITIVITY ON "W" USING "M" BY 5\nEND SENSITIVITY', 1, "nothing to vary"),
])
def test_dry_run_checks(session, code, line, needle):
    r = session.run(code, dry_run=True)
    assert not r.ok
    assert any(e["line"] == line and needle in e["message"] for e in r.errors), r.errors
    assert all(e["hint"] or "File not found" in e["message"] for e in r.errors)


def test_dry_run_knows_what_the_session_already_defined(session):
    session.run('LET mass = 2\nCONFIRM DELETE ON\nSUB hello()\nPRINT 1\nEND SUB')
    r = session.run('PRINT mass\nhello\nDELETE PROCESS "X"', dry_run=True)
    assert r.ok, r.errors


def test_dry_run_looks_inside_loops_and_subs(session):
    r = session.run('FOR i = 1 TO 2\n  PRINT ghost\nNEXT', dry_run=True)
    assert r.errors[0]["line"] == 2
    r = session.run('FOR i = 1 TO 2\n  PRINT i\nNEXT', dry_run=True)
    assert r.ok


def test_dry_run_offline_warns_about_commands_that_need_openlca():
    s = Session(offline=True)
    r = s.run('PRINT 1\nFIND PROCESS "x"', dry_run=True)
    assert r.ok
    assert r.warnings == [{"line": 2, "level": "warning",
                           "message": "FIND needs a connection to openLCA, "
                                      "and this session has none."}]


# ── the REPL still prints ────────────────────────────────────

def test_interpreter_prints_by_default(interp, capsys):
    interp.run_program('PRINT "to the terminal"')
    assert capsys.readouterr().out == "  to the terminal\n"


def test_print_sink_and_recording_sink_see_the_same_text(client):
    from olcabasic.bridge import LCABridge
    from olcabasic.engine import Engine
    from olcabasic.interpreter import Interpreter
    from olcabasic.output import RecordingSink
    sink = RecordingSink()
    interp = Interpreter(LCABridge(engine=Engine(client)), out=sink)
    interp.run_program('PRINT "x"\nPWD\nHELP')
    printed_by_session = Session(client=seed_ecoinvent_like()).run(
        'PRINT "x"\nPWD\nHELP').text
    assert sink.text() == printed_by_session
