"""Runs olcaBASIC code against a live openLCA for the live tests."""

import os


class LiveRunner:
    """One Session on the live openLCA for a whole test module.

    run(code) executes a program and returns the structured result of
    its last engine call. An error fails the test with the text
    olcaBASIC produced.
    """

    def __init__(self, port: int = None):
        from olcabasic import Session
        self.port = port or int(os.getenv("OLCA_PORT", "8080"))
        self.session = Session(port=self.port)
        if not self.session.connected:
            raise RuntimeError(
                f"could not connect to openLCA on port {self.port}")

    @property
    def engine(self):
        return self.session.engine

    def run(self, code: str):
        result = self.session.run(code)
        assert result.ok, f"{result.errors}\n{result.text}"
        return result.data[-1]["result"] if result.data else None
