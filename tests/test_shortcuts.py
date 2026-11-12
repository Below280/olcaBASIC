"""The shortcut suite through a Session: the rules hold without the MCP
(the same cases run through olcabasic_run in B280-olca-MCP)."""

import pytest

import shortcut_cases as sc
from olcabasic import Session
from olcabasic.workflows.epd import EpdWorkflow


@pytest.fixture(autouse=True)
def fixed_date(monkeypatch):
    monkeypatch.setattr(EpdWorkflow, "today", staticmethod(lambda: sc.TODAY))


@pytest.mark.parametrize("case", sc.CASES, ids=[c.key for c in sc.CASES])
def test_the_shortcut_is_refused_and_nothing_is_written(case):
    client = sc.database(case.database)
    session = Session(client=client)
    try:
        sc.play(case, client, session,
                lambda code: session.run(code).to_dict())
    finally:
        session.close()
    assert client.undisposed() == 0


def test_every_rule_has_a_case():
    covered = {case.rule for case in sc.CASES}
    assert covered == set(sc.RULES)
    assert len({case.key for case in sc.CASES}) == len(sc.CASES)
