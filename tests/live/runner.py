"""Runs olcaBASIC code against a live openLCA for the live tests."""

import os


class LiveRunner:
    """One connection to openLCA for a whole test module.

    run(code) executes a program and returns the structured result of
    its last calculation command. Errors fail the test with the text
    olcaBASIC printed.
    """

    def __init__(self, port: int = None):
        self.port = port or int(os.getenv("OLCA_PORT", "8080"))
        from olcabasic.bridge import LCABridge
        from olcabasic.interpreter import Interpreter
        self.bridge = LCABridge(port=self.port)
        if not self.bridge.connect():
            raise RuntimeError(
                f"could not connect to openLCA on port {self.port}")
        self.interp = Interpreter(self.bridge)

    @property
    def engine(self):
        return self.bridge.lca

    def run(self, code: str):
        self.interp.runtime.last_results = None
        self.interp.run_program(code)
        return self.interp.runtime.last_results
