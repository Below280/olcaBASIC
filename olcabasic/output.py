"""
Output sinks.

The interpreter never prints. It writes to a sink:

- PrintSink prints to the terminal and asks questions with input().
  The REPL and `olcabasic run file.baslca` use it.
- RecordingSink keeps the text, the structured results, and the
  warnings and notes of one run. Session uses it; nothing is printed and
  nothing can be asked.
"""

from typing import Any, Dict, List


class NoInteraction(Exception):
    """Raised when a program needs an answer and nobody can give one."""


class OutputSink:
    """Where the interpreter's output goes."""

    #: line of the statement being executed (set by the interpreter)
    line: int = 0
    #: True if ask() can reach a person
    interactive: bool = False

    def write(self, text: str = "") -> None:
        raise NotImplementedError

    def ask(self, prompt: str) -> str:
        raise NoInteraction(prompt)

    def data(self, command: str, call: str, result: Any) -> None:
        """A structured result from an engine call."""

    def clear_screen(self) -> None:
        """CLEAR: only a terminal has a screen to clear."""


class PrintSink(OutputSink):
    """The terminal."""

    interactive = True

    def write(self, text: str = "") -> None:
        print(text)

    def ask(self, prompt: str) -> str:
        return input(prompt)

    def clear_screen(self) -> None:
        import os
        os.system("cls" if os.name == "nt" else "clear")


class RecordingSink(OutputSink):
    """Keeps one run's output for Session.run()."""

    interactive = False

    def __init__(self):
        self.lines: List[str] = []
        self.results: List[Dict] = []
        self.warnings: List[Dict] = []
        self.line = 0

    def write(self, text: str = "") -> None:
        text = str(text)
        self.lines.append(text)
        stripped = text.lstrip()
        for level, prefix in (("warning", "WARNING:"), ("note", "NOTE:")):
            if stripped.startswith(prefix):
                self.warnings.append({
                    "line": self.line,
                    "message": stripped[len(prefix):].strip(),
                    "level": level,
                })

    def data(self, command: str, call: str, result: Any) -> None:
        self.results.append({"command": command, "line": self.line,
                             "call": call, "result": result})

    def text(self) -> str:
        return "\n".join(self.lines)
