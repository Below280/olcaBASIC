"""
Tokeniser for olcaBASIC.

Splits a source line into tokens: keywords, strings, numbers,
identifiers, operators, and punctuation. Handles line continuation
with trailing underscore.
"""

import re
from enum import Enum, auto
from typing import List, Optional


class TokenType(Enum):
    # Literals
    STRING = auto()       # "hello"
    NUMBER = auto()       # 42, 3.14, 1e-7
    IDENTIFIER = auto()   # biomass_input, project$

    # Keywords (matched case-insensitively)
    KEYWORD = auto()

    # Operators and punctuation
    EQUALS = auto()       # =
    COMMA = auto()        # ,
    PLUS = auto()         # +
    MINUS = auto()        # -
    STAR = auto()         # *
    SLASH = auto()        # /
    LPAREN = auto()       # (
    RPAREN = auto()       # )
    PERCENT = auto()      # %
    LESS = auto()         # <
    GREATER = auto()      # >
    LESS_EQ = auto()      # <=
    GREATER_EQ = auto()   # >=
    NOT_EQ = auto()       # <>

    # Special
    NEWLINE = auto()
    EOF = auto()
    COMMENT = auto()      # REM or ' ... (rest of line)


class Token:
    __slots__ = ("type", "value", "line", "col")

    def __init__(self, type: TokenType, value: str,
                 line: int = 0, col: int = 0):
        self.type = type
        self.value = value
        self.line = line
        self.col = col

    def __repr__(self):
        return f"Token({self.type.name}, {self.value!r})"

    def keyword_match(self, *keywords: str) -> bool:
        """Check if this token is a keyword matching any of the given strings."""
        if self.type != TokenType.KEYWORD:
            return False
        upper = self.value.upper()
        return upper in keywords

    def upper(self) -> str:
        """Return the value uppercased."""
        return self.value.upper()


# All olcaBASIC keywords. Order matters for multi-word keywords
# which must be checked before single-word ones during parsing.
KEYWORDS = {
    # Core BASIC
    "REM", "LET", "PRINT", "INPUT", "OUTPUT", "IF", "THEN", "ELSE",
    "END", "FOR", "TO", "STEP", "NEXT", "EACH", "IN",
    "WHILE", "WEND", "SUB", "FUNCTION", "AS", "RETURN",
    "AND", "OR", "NOT", "ON", "ERROR",
    "DATA", "READ", "GOTO", "GOSUB",
    # File operations
    "RUN", "SAVE", "LOAD", "INCLUDE", "NEW",
    "HISTORY", "CLEAR", "EXIT", "QUIT", "HELP",
    # LCA entities
    "FLOW", "PROCESS", "BRIDGE", "SYSTEM",
    "CALCULATE", "SENSITIVITY", "SCENARIO", "SCENARIOS",
    "CONTRIBUTION", "MONTECARLO", "INVENTORY",
    # LCA modifiers
    "USING", "ALLOCATE", "LOCATION", "FOLDER",
    "PROVIDER", "DESCRIPTION", "PROPERTY",
    "LINKING", "TARGET", "CATEGORIES", "TOP",
    "BY", "FROM", "VARY", "RUNS", "MAX",
    "TIER", "AGAINST", "WITH", "LIMIT",
    # LCA types
    "PRODUCT", "WASTE", "ELEMENTARY",
    # LCA entity operations
    "FIND", "INSPECT", "LIST", "EXTRACT",
    "VALIDATE", "CHECK", "AUDIT", "EDIT",
    "DELETE", "CONFIRM", "ADD", "UPDATE", "REMOVE", "SET",
    # Output
    "EXPORT", "RESULTS", "DATABASE", "METHODS", "SYSTEMS",
    "PROCESSES", "FLOWS", "PARAMS", "DETAILS", "QUALITY",
    "LINKS", "UNITS", "GLOBAL", "CHEMICAL", "FILTER",
    "DQ", "INFO", "FAMILY",
    # Elementary flow directions
    "AIR", "WATER", "SOIL", "NATURE",
    # Allocation
    "ECONOMIC", "PHYSICAL", "CAUSAL", "NONE",
    "AS_DEFINED",
    # Linking
    "PREFER_DEFAULTS", "ONLY_DEFAULTS",
    # IO
    "CSV", "FORMULA",
    # Connection
    "CONNECT", "PORT", "REFRESH",
    # Output format
    "INPUTS",
}

# Two-word keywords that the tokeniser should recognise as single tokens
# when they appear adjacent. The parser handles these at a higher level
# instead, so we just tokenise each word individually.

# Regex patterns
_STRING_PAT = re.compile(r'"([^"]*)"')
_NUMBER_PAT = re.compile(
    r'(?<![A-Za-z_])(\d+\.?\d*(?:[eE][+-]?\d+)?)'
)
_IDENT_PAT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\$?')
_WHITESPACE_PAT = re.compile(r'[ \t]+')


def tokenise_line(text: str, line_number: int = 0) -> List[Token]:
    """Tokenise a single line of olcaBASIC source."""
    tokens = []
    pos = 0
    length = len(text)

    # Strip trailing newline/whitespace
    text = text.rstrip()
    length = len(text)

    # Check for line continuation (trailing underscore)
    continuation = False
    if text.endswith(" _") or text.endswith("\t_"):
        text = text[:-1].rstrip()
        length = len(text)
        continuation = True

    while pos < length:
        # Skip whitespace
        m = _WHITESPACE_PAT.match(text, pos)
        if m:
            pos = m.end()
            continue

        # Comment: ' (apostrophe) — rest of line
        if text[pos] == "'":
            tokens.append(Token(TokenType.COMMENT, text[pos:],
                                line_number, pos))
            break

        # String literal
        if text[pos] == '"':
            m = _STRING_PAT.match(text, pos)
            if m:
                tokens.append(Token(TokenType.STRING, m.group(1),
                                    line_number, pos))
                pos = m.end()
                continue
            else:
                # Unterminated string — take rest of line
                tokens.append(Token(TokenType.STRING,
                                    text[pos + 1:],
                                    line_number, pos))
                break

        # Two-character operators
        if pos + 1 < length:
            two = text[pos:pos + 2]
            if two == "<=":
                tokens.append(Token(TokenType.LESS_EQ, two,
                                    line_number, pos))
                pos += 2
                continue
            elif two == ">=":
                tokens.append(Token(TokenType.GREATER_EQ, two,
                                    line_number, pos))
                pos += 2
                continue
            elif two == "<>":
                tokens.append(Token(TokenType.NOT_EQ, two,
                                    line_number, pos))
                pos += 2
                continue

        # Single-character operators and punctuation
        ch = text[pos]
        if ch == "=":
            tokens.append(Token(TokenType.EQUALS, ch, line_number, pos))
            pos += 1
            continue
        elif ch == ",":
            tokens.append(Token(TokenType.COMMA, ch, line_number, pos))
            pos += 1
            continue
        elif ch == "+":
            tokens.append(Token(TokenType.PLUS, ch, line_number, pos))
            pos += 1
            continue
        elif ch == "-":
            # Could be negative number or minus operator
            # If previous token is a number/identifier/rparen, it is minus
            # Otherwise it might be a negative number
            if (tokens and tokens[-1].type in
                    (TokenType.NUMBER, TokenType.IDENTIFIER,
                     TokenType.RPAREN)):
                tokens.append(Token(TokenType.MINUS, ch,
                                    line_number, pos))
                pos += 1
                continue
            else:
                # Try negative number
                m = _NUMBER_PAT.match(text, pos + 1)
                if m and m.start() == pos + 1:
                    tokens.append(Token(TokenType.NUMBER,
                                        "-" + m.group(1),
                                        line_number, pos))
                    pos = m.end()
                    continue
                else:
                    tokens.append(Token(TokenType.MINUS, ch,
                                        line_number, pos))
                    pos += 1
                    continue
        elif ch == "*":
            tokens.append(Token(TokenType.STAR, ch, line_number, pos))
            pos += 1
            continue
        elif ch == "/":
            tokens.append(Token(TokenType.SLASH, ch, line_number, pos))
            pos += 1
            continue
        elif ch == "(":
            tokens.append(Token(TokenType.LPAREN, ch, line_number, pos))
            pos += 1
            continue
        elif ch == ")":
            tokens.append(Token(TokenType.RPAREN, ch, line_number, pos))
            pos += 1
            continue
        elif ch == "%":
            tokens.append(Token(TokenType.PERCENT, ch, line_number, pos))
            pos += 1
            continue
        elif ch == "<":
            tokens.append(Token(TokenType.LESS, ch, line_number, pos))
            pos += 1
            continue
        elif ch == ">":
            tokens.append(Token(TokenType.GREATER, ch, line_number, pos))
            pos += 1
            continue

        # Number literal
        m = _NUMBER_PAT.match(text, pos)
        if m and m.start() == pos:
            tokens.append(Token(TokenType.NUMBER, m.group(1),
                                line_number, pos))
            pos = m.end()
            continue

        # Identifier or keyword
        m = _IDENT_PAT.match(text, pos)
        if m:
            word = m.group()
            if word.upper() == "REM":
                # REM — rest of line is a comment
                tokens.append(Token(TokenType.COMMENT, text[pos:],
                                    line_number, pos))
                break
            elif word.upper() in KEYWORDS:
                tokens.append(Token(TokenType.KEYWORD, word,
                                    line_number, pos))
            else:
                tokens.append(Token(TokenType.IDENTIFIER, word,
                                    line_number, pos))
            pos = m.end()
            continue

        # Unknown character — skip it
        pos += 1

    tokens.append(Token(TokenType.NEWLINE, "\\n", line_number, pos))
    return tokens, continuation


def tokenise(source: str) -> List[Token]:
    """Tokenise a complete olcaBASIC program."""
    all_tokens = []
    lines = source.split("\n")
    accumulated = ""
    start_line = 0

    for i, line in enumerate(lines):
        if accumulated:
            accumulated += " " + line.strip()
        else:
            accumulated = line
            start_line = i + 1  # 1-based line numbers

        tokens, continuation = tokenise_line(accumulated, start_line)

        if continuation:
            # Remove the NEWLINE token and continue accumulating
            tokens = [t for t in tokens if t.type != TokenType.NEWLINE]
            # Keep going
        else:
            all_tokens.extend(tokens)
            accumulated = ""

    # Handle any remaining accumulated text
    if accumulated:
        tokens, _ = tokenise_line(accumulated, start_line)
        all_tokens.extend(tokens)

    all_tokens.append(Token(TokenType.EOF, "", len(lines), 0))
    return all_tokens
