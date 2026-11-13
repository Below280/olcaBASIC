"""Raw connection errors from the HTTP library are told plainly."""

from olcabasic import Session
from olcabasic.errors import BasicError, error_dict, explain_connection


RESET = ("('Connection aborted.', ConnectionResetError(10054, 'An existing "
         "connection was forcibly closed by the remote host', None, 10054, "
         "None))")
REFUSED = ("HTTPConnectionPool(host='localhost', port=8080): Max retries "
           "exceeded with url: / (Caused by NewConnectionError('Failed to "
           "establish a new connection: [WinError 10061] No connection "
           "could be made because the target machine actively refused "
           "it'))")


def test_a_dropped_connection_points_at_memory():
    message, hint = explain_connection(RESET)
    assert message.startswith("openLCA closed the connection")
    assert "out of memory" in hint and "Configuration" in hint


def test_a_refused_connection_says_the_server_is_not_answering():
    message, hint = explain_connection(REFUSED)
    assert message == "openLCA's IPC server is not answering."
    assert "IPC server is running" in hint


def test_other_messages_are_left_alone():
    assert explain_connection("No process called 'X'.", "h") == (
        "No process called 'X'.", "h")


def test_error_dict_and_basic_error_use_it():
    d = error_dict(RESET, 3)
    assert d["line"] == 3 and "out of memory" in d["hint"]
    e = BasicError(RESET, 2)
    assert "forcibly" not in str(e) and "out of memory" in e.hint


def test_a_session_reports_a_dropped_connection_plainly(client):
    session = Session(client=client)

    def boom(*a, **k):
        raise ConnectionResetError(RESET)
    client.get_descriptors = boom
    client.get_all = boom
    r = session.run('FIND PROCESS "anything"')
    assert not r.ok
    assert r.errors[0]["message"].startswith("openLCA closed the connection")
    assert "forcibly" not in r.text
