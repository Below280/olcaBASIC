"""
Interactive REPL for olcaBASIC.

Provides the '>' prompt, command history, and multi-line
block handling (PROCESS/END PROCESS, etc.).
"""

import sys
from typing import Optional
from .interpreter import Interpreter


# Block-opening keywords that require an END to close
BLOCK_OPENERS = {
    "PROCESS", "SENSITIVITY",
    "SCENARIO", "IF", "FOR", "WHILE", "SUB", "FUNCTION",
    "EDIT",
    # blocks inside a PROCESS, SYSTEM or EDIT block
    "ALLOCATION", "DOCUMENT", "ANALYSIS",
    # blocks inside MAKE METHOD, EDIT METHOD and MAKE PROJECT
    "CATEGORY", "VARIANT",
}

# MAKE <word> ... END <word> blocks (MAKE FLOW and MAKE SYSTEM are one line)
MAKE_BLOCKS = {"PROCESS", "ACTOR", "SOURCE", "CURRENCY", "LOCATION", "UNITS",
               "UNIT", "PROPERTY", "SOCIAL", "DQ", "METHOD", "PROJECT"}

# Keywords that close a block
BLOCK_CLOSERS = {"END", "NEXT", "WEND"}


class REPL:
    """Interactive Read-Eval-Print Loop for olcaBASIC."""

    def __init__(self, interpreter: Interpreter):
        self.interpreter = interpreter
        self.history: list = []
        self._accumulating = False
        self._accumulated_lines: list = []
        self._block_depth = 0
        self._in_project = False
        self._setup_completer()

    def _setup_completer(self):
        """Set up tab completion if readline is available."""
        try:
            from .completer import Completer, HAS_READLINE
            if HAS_READLINE:
                self.completer = Completer(
                    bridge=self.interpreter.bridge,
                    runtime=self.interpreter.runtime,
                )
                self.completer.setup()
            else:
                self.completer = None
        except Exception:
            self.completer = None

    def run(self):
        """Main REPL loop."""
        while True:
            try:
                if self._accumulating:
                    prompt = f"  {self._block_depth}> "
                else:
                    prompt = "> "

                line = input(prompt)

            except (EOFError, KeyboardInterrupt):
                print("\n  Goodbye.")
                break

            # Track block depth for multi-line input
            upper = line.strip().upper()
            words = upper.split()
            first_word = words[0] if words else ""
            # MAKE opens a block only for MAKE PROCESS; MAKE FLOW is one line
            if first_word == "MAKE" and len(words) > 1 and (
                    words[1] in MAKE_BLOCKS
                    or words[1:3] == ["FLOW", "PROPERTY"]):
                first_word = "PROCESS"
                self._in_project = words[1] == "PROJECT"
            # NW SET "name" is a block in a method and one line in a project
            if (first_word == "NW" and self._accumulating
                    and not self._in_project):
                first_word = "ALLOCATION"
            # PARAMETER SET "name" opens a block; DEFAULT ALLOCATION and
            # REMOVE ALLOCATION are single lines
            if first_word == "PARAMETER" and len(words) > 1 and words[1] == "SET":
                first_word = "ALLOCATION"

            if self._accumulating:
                self._accumulated_lines.append(line)

                # Check for block depth changes
                if first_word in BLOCK_OPENERS:
                    self._block_depth += 1
                elif first_word in BLOCK_CLOSERS:
                    self._block_depth -= 1

                if self._block_depth <= 0:
                    # Block complete, execute
                    full_text = "\n".join(self._accumulated_lines)
                    self._accumulating = False
                    self._accumulated_lines = []
                    self._block_depth = 0
                    self._in_project = False
                    self.history.append(full_text)

                    if not self._run(full_text):
                        print("  Goodbye.")
                        break
                continue

            # Check if this line opens a block
            if first_word in BLOCK_OPENERS:
                # Check if the closing keyword is on the same line
                # (e.g. single-line IF/THEN)
                if first_word == "IF" and "THEN" in upper:
                    # Check if there is content after THEN (single-line IF)
                    after_then = upper.split("THEN", 1)[1].strip()
                    if after_then and "END" not in after_then:
                        # Single-line IF: execute directly
                        self.history.append(line)
                        if not self._run(line):
                            print("  Goodbye.")
                            break
                        continue

                # Start accumulating a block
                self._accumulating = True
                self._accumulated_lines = [line]
                self._block_depth = 1
                continue

            # Single-line command
            self.history.append(line)
            if not self._run(line):
                print("  Goodbye.")
                break

    def _run(self, text: str) -> bool:
        """Run text, treating Ctrl+C as 'stop this command', not 'quit'."""
        try:
            return self.interpreter.run_line(text)
        except KeyboardInterrupt:
            print("\n  Interrupted.")
            return True

    def get_history(self) -> list:
        return list(self.history)
