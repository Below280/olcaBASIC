"""
Session: one openLCA connection, one engine, and the state of the
olcaBASIC programs run on it.

    from olcabasic import Session

    s = Session(port=8080)            # or Session(offline=True)
    r = s.run('FIND PROCESS "cement"')
    r.ok          # bool
    r.text        # what a terminal user would have seen
    r.data        # structured results (dicts) from engine calls
    r.errors      # [{line, message, hint}]
    r.warnings    # [{line, message, level}]

State persists between run() calls: variables, folders, scenarios, the
last results and CONFIRM DELETE. run() holds a lock for its whole
duration, so two programs can never write to openLCA at once (openLCA
corrupts product systems that are created concurrently).
"""

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .bridge import LCABridge
from .errors import BasicError, error_dict
from .interpreter import Interpreter
from .output import RecordingSink
from .parser import ParseError, parse
from .runtime import Runtime
from . import dryrun


@dataclass
class RunResult:
    """What one Session.run() call produced."""

    ok: bool = True
    text: str = ""
    data: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "text": self.text, "data": self.data,
                "errors": self.errors, "warnings": self.warnings}

    def __bool__(self) -> bool:
        return self.ok


class Session:
    """One connection to openLCA and the state that goes with it."""

    def __init__(self, port: int = 8080, offline: bool = False,
                 client=None, engine=None):
        """port: openLCA's IPC port.
        offline: no connection at all; BASIC still runs, anything that
        needs openLCA is refused.
        client / engine: use an existing olca_ipc.Client (or anything
        with the same methods) or an existing Engine."""
        self.port = port
        self.offline = offline
        self.lock = threading.RLock()
        self.runtime = Runtime()
        self.bridge: Optional[LCABridge] = None
        if engine is None and client is not None:
            from .engine import Engine
            engine = Engine(client)
        if engine is not None:
            self.bridge = LCABridge(port=port, engine=engine)
        self.interpreter = Interpreter(self.bridge, out=RecordingSink(),
                                       runtime=self.runtime)
        if not offline and self.bridge is None:
            self.connect()

    # ── connection ───────────────────────────────────────────

    def connect(self) -> bool:
        """Connect (or reconnect) to openLCA. Returns True if it answers.
        Called on creation and again by run() while there is no
        connection, so openLCA can be started after the Session."""
        if self.offline:
            return False
        if self.connected:
            return True
        bridge = LCABridge(port=self.port)
        if bridge.connect():
            self.bridge = bridge
            self.interpreter.bridge = bridge
            return True
        return False

    @property
    def connected(self) -> bool:
        return self.bridge is not None and self.bridge.connected

    @property
    def engine(self):
        """The Engine, or None when there is no connection."""
        return self.bridge.engine if self.bridge is not None else None

    @property
    def client(self):
        """The olca_ipc.Client the engine uses, or None."""
        engine = self.engine
        return engine.client if engine is not None else None

    # ── running programs ─────────────────────────────────────

    def run(self, code: str, dry_run: bool = False,
            filename: str = "") -> RunResult:
        """Run olcaBASIC code. The program stops at its first error.

        dry_run=True parses the program and checks what can be checked
        without openLCA (names, blocks, files, things that would need
        an answer from the keyboard). Nothing is executed.
        """
        with self.lock:
            sink = RecordingSink()
            interp = self.interpreter
            interp.out = sink
            errors: List[Dict] = []
            try:
                source = interp._process_includes(code, filename)
                statements = parse(source)
            except ParseError as e:
                errors.append(error_dict(e.message, e.line, e.hint))
                sink.write(f"Parse error: {e}")
                return self._result(sink, errors)
            except BasicError as e:
                errors.append(e.as_dict())
                sink.write(f"  Error: {e}")
                return self._result(sink, errors)

            if dry_run:
                report = dryrun.check(statements, self.runtime,
                                      connected=self.connected)
                sink.lines.extend(report.text_lines())
                sink.line = 0
                sink.data("DRY RUN", "dry_run", report.summary())
                sink.warnings.extend(report.warnings)
                return self._result(sink, report.errors)

            if not self.offline and not self.connected:
                self.connect()

            interp._stop_requested = False
            for stmt in statements:
                if stmt is None:
                    continue
                if interp._stop_requested:
                    break
                try:
                    interp._execute(stmt)
                except BasicError as e:
                    errors.append(e.as_dict())
                    sink.write(f"  Error: {e}")
                    break
                except Exception as e:  # engine or openLCA failure
                    line = sink.line or getattr(stmt, "line", 0)
                    errors.append(error_dict(str(e) or type(e).__name__, line))
                    sink.write(f"  Error: Line {line}: {e}")
                    break
            if not errors and not all(
                    type(st).__name__ in ("SaveProgramStmt", "HelpStmt",
                                          "LoadStmt", "ListStmt",
                                          "RunMemoryStmt")
                    for st in statements):
                self.runtime.program_history.append(code)
            return self._result(sink, errors)

    @staticmethod
    def _result(sink: RecordingSink, errors: List[Dict]) -> RunResult:
        return RunResult(ok=not errors, text=sink.text(), data=sink.results,
                         errors=errors, warnings=sink.warnings)

    def reset(self) -> None:
        """Clear the session's state: variables, SUBs, folders,
        scenarios, last results, CONFIRM DELETE. The database is not
        touched and the connection stays open."""
        with self.lock:
            self.runtime.reset()

    # ── state, for callers that want to look ─────────────────

    @property
    def variables(self) -> Dict[str, Any]:
        return self.runtime.get_global_vars()

    @property
    def last_results(self):
        return self.runtime.last_results
