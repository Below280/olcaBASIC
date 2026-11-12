"""Tokeniser tests."""

import pytest

from olcabasic.tokeniser import (KEYWORDS, TokeniseError, TokenType, tokenise,
                                 tokenise_line)


def types(text):
    tokens, _ = tokenise_line(text, 1)
    return [t.type for t in tokens]


def values(text):
    tokens, _ = tokenise_line(text, 1)
    return [t.value for t in tokens if t.type != TokenType.NEWLINE]


def test_string_literal():
    assert values('"hello world"') == ["hello world"]
    assert types('"x"')[0] == TokenType.STRING


def test_unterminated_string_is_an_error():
    with pytest.raises(TokeniseError) as e:
        tokenise_line('PRINT "oops', 7)
    assert e.value.line == 7
    assert "Unterminated string" in str(e.value)


@pytest.mark.parametrize("text,expected", [
    ("42", "42"), ("3.14", "3.14"), ("1e-7", "1e-7"), (".5", ".5"),
    ("2.5E+3", "2.5E+3"),
])
def test_number_literals(text, expected):
    tokens, _ = tokenise_line(text, 1)
    assert tokens[0].type == TokenType.NUMBER
    assert tokens[0].value == expected


def test_negative_number_after_operator_is_one_token():
    assert values("LET x = -5") == ["LET", "x", "=", "-5"]


def test_minus_after_identifier_is_an_operator():
    assert types("a - 5")[:3] == [TokenType.IDENTIFIER, TokenType.MINUS,
                                  TokenType.NUMBER]


def test_keywords_are_case_insensitive():
    for text in ("print", "Print", "PRINT"):
        tok = tokenise_line(text, 1)[0][0]
        assert tok.type == TokenType.KEYWORD
        assert tok.keyword_match("PRINT")


def test_identifier_with_dollar():
    tok = tokenise_line("project$", 1)[0][0]
    assert tok.type == TokenType.IDENTIFIER and tok.value == "project$"


@pytest.mark.parametrize("op,ttype", [
    ("<=", TokenType.LESS_EQ), (">=", TokenType.GREATER_EQ),
    ("<>", TokenType.NOT_EQ), ("<", TokenType.LESS), (">", TokenType.GREATER),
    ("=", TokenType.EQUALS), ("+", TokenType.PLUS), ("*", TokenType.STAR),
    ("/", TokenType.SLASH), ("^", TokenType.CARET), ("%", TokenType.PERCENT),
    ("(", TokenType.LPAREN), (")", TokenType.RPAREN), (",", TokenType.COMMA),
])
def test_operators(op, ttype):
    assert types(f"a {op} b")[1] == ttype


def test_apostrophe_comment_takes_rest_of_line():
    tokens, _ = tokenise_line("LET x = 1 ' a note", 1)
    assert tokens[-2].type == TokenType.COMMENT
    assert tokens[-2].value == "' a note"


def test_rem_comment():
    tokens, _ = tokenise_line("REM anything : goes & here", 1)
    assert tokens[0].type == TokenType.COMMENT


def test_dotdot_for_cd():
    assert values("CD ..") == ["CD", ".."]


@pytest.mark.parametrize("ch,hint", [
    ("&", "use + to join strings"),
    (":", "put each statement on its own line"),
    (";", "use , to separate PRINT items"),
])
def test_unexpected_characters_carry_a_hint(ch, hint):
    with pytest.raises(TokeniseError) as e:
        tokenise_line(f"PRINT 1 {ch} 2", 3)
    assert hint in str(e.value)
    assert "Line 3" in str(e.value)


def test_unknown_character_without_hint():
    with pytest.raises(TokeniseError):
        tokenise_line("PRINT @", 1)


def test_line_continuation_joins_lines():
    tokens = tokenise('PRINT 1 + _\n  2\nPRINT 3')
    vals = [t.value for t in tokens if t.type == TokenType.NUMBER]
    assert vals == ["1", "2", "3"]
    newlines = [t for t in tokens if t.type == TokenType.NEWLINE]
    assert len(newlines) == 2


def test_line_numbers_are_one_based():
    tokens = tokenise("PRINT 1\n\nPRINT 2")
    prints = [t for t in tokens if t.type == TokenType.KEYWORD]
    assert [t.line for t in prints] == [1, 3]


def test_program_ends_with_eof():
    assert tokenise("PRINT 1")[-1].type == TokenType.EOF


def test_three_dialects_are_all_keywords():
    basic = {"LET", "PRINT", "IF", "THEN", "ELSE", "FOR", "NEXT", "WHILE",
             "WEND", "SUB", "FUNCTION", "DATA", "READ", "REM", "INCLUDE",
             "RUN", "SAVE", "LOAD"}
    acorn = {"CAT", "DIR", "CDIR", "UP", "BACK"}
    linux = {"LS", "CD", "PWD"}
    assert (basic | acorn | linux) <= KEYWORDS
