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
