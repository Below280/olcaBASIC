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
}

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
            first_word = upper.split()[0] if upper.split() else ""

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
                    self.history.append(full_text)

                    if not self.interpreter.run_line(full_text):
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
                        if not self.interpreter.run_line(line):
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
            if not self.interpreter.run_line(line):
                print("  Goodbye.")
                break

    def get_history(self) -> list:
        return list(self.history)
