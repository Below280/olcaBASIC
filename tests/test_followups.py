"""Follow-ups to 0.4.0 agreed with Tom on 12/11/2026: USE FLOW
ambiguity, LOAD, EPD type names, no EPD CHECK SKIP under a programme,
PARAMETERISE ... ALL with two confirmations."""

import pytest
import olca_schema as o

from olcabasic import Session
from test_interpreter_lca import SETUP


@pytest.fixture
def session(client):
    return Session(client=client)


def err(result):
    assert not result.ok, result.text
    return result.errors[0]


def _twin_flows(client, name="shared blend"):
    a = client.add_flow(name, "Mass", category="00: Supplier A/Flows")
    b = client.add_flow(name, "Mass", category="00: Supplier B/Flows")
    return a, b


def _process_using(flow_ref, extra=""):
    return SETUP + f'''MAKE PROCESS "Mixer"
  OUTPUT MAKE FLOW "Mix", 1, kg, PRODUCT
  INPUT USE FLOW "{flow_ref}", 2, kg{extra}
END PROCESS'''


def _input_flow_id(client):
    proc = client.by_name(o.Process, "Mixer")[0]
    return [e for e in proc.exchanges if e.is_input][0].flow.id


# ── USE FLOW: a shared name is an error, FOLDER or UUID picks ────────

def test_use_flow_shared_name_is_an_error_listing_folder_and_uuid(session, client):
    a, b = _twin_flows(client)
    e = err(session.run(_process_using("shared blend")))
    assert e["line"] == 7
    assert "matches 2 flows" in e["message"]
    for f in (a, b):
        assert f.id in e["message"] and f.category in e["message"]
    assert "FOLDER" in e["hint"] and "UUID" in e["hint"]
    assert not client.by_name(o.Process, "Mixer")


def test_use_flow_folder_picks_one(session, client):
    a, b = _twin_flows(client)
    r = session.run(_process_using("shared blend", ' FOLDER "00: Supplier B"'))
    assert r.ok, r.errors
    assert _input_flow_id(client) == b.id


def test_use_flow_uuid_picks_one(session, client):
    a, b = _twin_flows(client)
    r = session.run(_process_using(a.id))
    assert r.ok, r.errors
    assert _input_flow_id(client) == a.id


def test_use_flow_folder_with_no_such_flow_is_an_error(session, client):
    _twin_flows(client)
    e = err(session.run(_process_using("shared blend", ' FOLDER "00: Nowhere"')))
    assert "No flow called 'shared blend' in '00: Nowhere'" in e["message"]
    assert not client.by_name(o.Process, "Mixer")


def test_use_flow_twins_inside_the_folder_are_still_an_error(session, client):
    client.add_flow("shared blend", "Mass", category="00: Supplier A/Flows")
    client.add_flow("shared blend", "Mass", category="00: Supplier A/Old")
    e = err(session.run(_process_using("shared blend", ' FOLDER "00: Supplier A"')))
    assert "matches 2 flows in '00: Supplier A'" in e["message"]


def test_folder_on_use_process_is_refused(session, client):
    r = session.run(SETUP + '''MAKE PROCESS "Mixer"
  OUTPUT MAKE FLOW "Mix", 1, kg, PRODUCT
  INPUT USE PROCESS "anything", 2, kg FOLDER "00: Somewhere"
END PROCESS''')
    e = err(r)
    assert "FOLDER picks between flows" in e["message"]


def test_unique_flow_name_still_resolves(session, client):
    only = client.add_flow("lonely blend", "Mass", category="00: Supplier A/Flows")
    r = session.run(_process_using("lonely blend"))
    assert r.ok, r.errors
    assert _input_flow_id(client) == only.id


# ── LOAD, LIST, RUN: the program in memory, as on a BBC Micro ───────

PROGRAM = 'LET x = 6\nPRINT "x is", x * 7\n'


def _file(tmp_path, text=PROGRAM, name="prog.baslca"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p).replace("\\", "/")


def test_load_puts_the_program_in_memory_without_running_it(session, tmp_path):
    f = _file(tmp_path)
    r = session.run(f'LOAD "{f}"')
    assert r.ok, r.errors
    assert "Loaded" in r.text and "2 lines" in r.text
    assert "x is" not in r.text
    assert not session.runtime.has_var("x")


def test_list_shows_the_loaded_program(session, tmp_path):
    session.run(f'LOAD "{_file(tmp_path)}"')
    r = session.run("LIST")
    assert "1  LET x = 6" in r.text and '2  PRINT "x is", x * 7' in r.text


def test_run_on_its_own_runs_the_program_in_memory(session, tmp_path):
    session.run(f'LOAD "{_file(tmp_path)}"')
    r = session.run("RUN")
    assert r.ok, r.errors
    assert "42" in r.text


def test_load_list_run_do_not_add_to_the_program(session, tmp_path):
    session.run(f'LOAD "{_file(tmp_path)}"')
    session.run("LIST")
    session.run("RUN")
    out = tmp_path / "saved.baslca"
    session.run(f'SAVE "{str(out).replace(chr(92), "/")}"')
    assert out.read_text(encoding="utf-8") == PROGRAM


def test_load_replaces_what_was_in_memory(session, tmp_path):
    session.run('PRINT "typed earlier"')
    session.run(f'LOAD "{_file(tmp_path)}"')
    assert "typed earlier" not in session.run("LIST").text


def test_load_of_a_broken_file_leaves_memory_alone(session, tmp_path):
    session.run(f'LOAD "{_file(tmp_path)}"')
    bad = _file(tmp_path, 'GOTO 10\n', "bad.baslca")
    e = err(session.run(f'LOAD "{bad}"'))
    assert "was not loaded" in e["message"] and "has not changed" in e["hint"]
    assert "LET x = 6" in session.run("LIST").text


def test_load_missing_file(session, tmp_path):
    e = err(session.run(f'LOAD "{tmp_path}/none.baslca"'.replace("\\", "/")))
    assert "File not found" in e["message"]


def test_run_with_nothing_in_memory(session):
    e = err(session.run("RUN"))
    assert "no program in memory" in e["message"] and "LOAD" in e["hint"]


def test_list_with_nothing_in_memory(session):
    assert "No program in memory" in session.run("LIST").text
