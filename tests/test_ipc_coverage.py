"""Every method of openLCA's IPC server is reached by a command.

The authoritative list is olcabasic.engine.ipc_methods.IPC_METHODS (read
from the server's request handlers). The registry says which methods
each command uses."""

import inspect
import re

import olca_ipc.ipc as ipc_client
import pytest

from olcabasic import registry
from olcabasic.engine.ipc_methods import CLIENT_MISNAMED, IPC_METHODS

METHOD = re.compile(r'"((?:data|result|export|runtime)/[a-z/\-]+)"')


def client_methods() -> set:
    """Every JSON-RPC method name in the installed olca-ipc client."""
    return set(METHOD.findall(inspect.getsource(ipc_client)))


def test_every_method_the_client_calls_is_in_the_list():
    unknown = client_methods() - set(IPC_METHODS) - set(CLIENT_MISNAMED)
    assert unknown == set(), (
        f"the installed olca-ipc calls methods the list does not have: "
        f"{sorted(unknown)}")


def test_misnamed_client_methods_point_at_real_ones():
    for wrong, right in CLIENT_MISNAMED.items():
        assert wrong not in IPC_METHODS
        assert right in IPC_METHODS


def test_the_list_names_real_client_functions():
    for method, entry in IPC_METHODS.items():
        if entry.client is None:
            continue
        assert (hasattr(ipc_client.Client, entry.client)
                or hasattr(ipc_client.Result, entry.client)), method


def test_ipc_use_names_registered_commands_and_listed_methods():
    names = {c.name for c in registry.COMMANDS}
    for command, methods in registry.IPC_USE.items():
        assert command in names, f"IPC_USE names no command: {command}"
        for m in methods:
            assert m in IPC_METHODS, f"{command} uses unknown method {m}"


def test_every_ipc_method_is_used_by_a_command():
    used = {m for c in registry.COMMANDS for m in c.ipc}
    missing = sorted(set(IPC_METHODS) - used)
    assert missing == [], f"no command reaches: {missing}"
