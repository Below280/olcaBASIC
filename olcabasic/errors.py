"""
Errors with a line and a hint.

Every olcaBASIC error says what went wrong, where, and what to type
instead. Structured output (Session.run) carries the three parts
separately as {line, message, hint}.
"""

import re
from typing import Dict, Tuple


class BasicError(Exception):
    """Runtime error in olcaBASIC, with the line and an optional hint.

    If no hint is given, everything after the first sentence of the
    message is treated as the hint when the error is reported in
    structured form: messages are written as "what went wrong. what to
    do about it."
    """

    def __init__(self, message: str, line: int = 0, hint: str = ""):
        self.line = line
        self.message = message
        self.hint = hint
        prefix = f"Line {line}: " if line else ""
        full = f"{message} {hint}".strip() if hint else message
        super().__init__(f"{prefix}{full}")

    def at(self, line: int) -> "BasicError":
        """The same error, reported at a line."""
        return BasicError(self.message, line, self.hint)

    def as_dict(self) -> Dict:
        return error_dict(self.message, self.line, self.hint)


def split_hint(message: str) -> Tuple[str, str]:
    """Split "what went wrong. what to do." into the two parts.

    The split is at the first full stop that ends a sentence outside
    quotes. A message of one sentence has no hint.
    """
    quote = None
    for i, ch in enumerate(message):
        if ch in "\"'":
            # an apostrophe inside a word (isn't, can't) is not a quote
            if ch == "'" and 0 < i < len(message) - 1 \
                    and message[i - 1].isalnum() and message[i + 1].isalnum():
                continue
            if quote is None:
                quote = ch
            elif quote == ch:
                quote = None
            continue
        if ch == "." and quote is None:
            rest = message[i + 1:]
            if rest[:1] == " " and rest[1:2] and (rest[1].isupper()
                                                  or rest[1] in "\"'"):
                return message[:i + 1].strip(), rest.strip()
    return message.strip(), ""


_LINE_PREFIX = re.compile(r"^Line (\d+): ")


def error_dict(message: str, line: int = 0, hint: str = "") -> Dict:
    """{line, message, hint} for structured output."""
    message = str(message)
    m = _LINE_PREFIX.match(message)
    if m:
        line = line or int(m.group(1))
        message = message[m.end():]
    if not hint:
        message, hint = split_hint(message)
    return {"line": int(line or 0), "message": message, "hint": hint}
