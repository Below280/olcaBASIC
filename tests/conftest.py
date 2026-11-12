"""Shared fixtures for the olcaBASIC test suite."""

import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "live"))

from fake_client import FakeClient, seed_ecoinvent_like  # noqa: E402


def _ipc_answering(port: int = 8080) -> bool:
    try:
        with socket.create_connection(("localhost", port), timeout=1):
            return True
    except OSError:
        return False


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: needs openLCA with its IPC server on localhost:8080 "
        "(run with: pytest -m live)")
    config.addinivalue_line(
        "markers", "slow: a live test that takes several minutes")


def pytest_collection_modifyitems(config, items):
    port = int(os.getenv("OLCA_PORT", "8080"))
    wanted = "live" in (config.getoption("-m") or "")
    up = _ipc_answering(port) if wanted else False
    for item in items:
        if "live" not in item.keywords:
            continue
        if not wanted:
            item.add_marker(pytest.mark.skip(
                reason="live test: run with pytest -m live"))
        elif not up:
            item.add_marker(pytest.mark.skip(
                reason=f"no openLCA IPC server answering on localhost:{port}"))


@pytest.fixture
def client() -> FakeClient:
    """A fake openLCA client holding the synthetic database."""
    return seed_ecoinvent_like()


@pytest.fixture
def empty_client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def engine(client):
    from olcabasic.engine import Engine
    return Engine(client)


@pytest.fixture
def bridge(engine):
    from olcabasic.bridge import LCABridge
    return LCABridge(engine=engine)


@pytest.fixture
def interp(bridge):
    from olcabasic.interpreter import Interpreter
    return Interpreter(bridge)


@pytest.fixture
def run(interp, capsys):
    """run(code) executes a program and returns what it printed."""
    def _run(code: str) -> str:
        capsys.readouterr()
        interp.run_program(code)
        return capsys.readouterr().out
    return _run


@pytest.fixture
def offline_interp():
    from olcabasic.interpreter import Interpreter
    return Interpreter(None)
