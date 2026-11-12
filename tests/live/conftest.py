"""Fixtures shared by the live tests: one Session on the live openLCA,
the baseline captured from the database that is open, and the reference
model, built once for the whole run and removed at the end."""

import os

import pytest

from live_support import matching_baseline
from runner import LiveRunner


@pytest.fixture(scope="session")
def runner():
    r = LiveRunner()
    yield r
    r.session.close()


@pytest.fixture(scope="session")
def baseline(runner):
    return matching_baseline(runner.engine)


@pytest.fixture(scope="session")
def names(baseline):
    return baseline["live_test_names"]


@pytest.fixture(scope="session")
def tol(baseline):
    return baseline["meta"].get("tolerance_rel", 1e-6)


@pytest.fixture(scope="session")
def live(runner, baseline, names):
    """Build the reference model once, hand over the runner, clean up."""
    runner.run(baseline["program_template"].format(**names))
    yield runner
    # Clean up: the system and the process. The product flow stays
    # unless OLCA_LIVE_DELETE_FLOW=1: DELETE FLOW reads every process
    # to make sure nothing uses the flow, which takes more than half an
    # hour on a database of 26,000 processes. The flow is reused by the
    # next run.
    code = (f'CLOSE RESULT ALL\nCONFIRM DELETE ON\n'
            f'DELETE SYSTEM "{names["name"]}"\n'
            f'DELETE PROCESS "{names["name"]}"')
    if os.getenv("OLCA_LIVE_DELETE_FLOW") == "1":
        code += f'\nDELETE FLOW "{names["name"]}"'
    runner.run(code)


