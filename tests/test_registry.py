"""The command registry is the one source for HELP, the README
reference and the MCP overview."""

import dataclasses
import inspect
import re
from pathlib import Path

import pytest

from olcabasic import ast_nodes, registry
from olcabasic.parser import parse
from olcabasic.registry import (ACORN, BASIC, COMMANDS, LINUX, OLCA, TOPICS,
                                find, render, render_overview)

ROOT = Path(__file__).resolve().parents[1]


def statement_classes():
    return {name for name, cls in inspect.getmembers(ast_nodes, inspect.isclass)
            if issubclass(cls, ast_nodes.Statement)
            and cls is not ast_nodes.Statement}


# ── the registry and the parser cannot drift ─────────────────

def test_every_statement_type_has_a_registry_entry():
    missing = statement_classes() - registry.documented_statements()
    assert missing == set(), f"no registry entry documents: {sorted(missing)}"


def test_registry_names_only_real_statement_types():
    unknown = registry.documented_statements() - statement_classes()
    assert unknown == set()


@pytest.mark.parametrize("command", COMMANDS, ids=lambda c: c.name)
def test_every_example_parses_to_the_statements_it_documents(command):
    statements = parse(command.example)
    assert statements or command.statements == ("CommentStmt",)
    produced = {type(s).__name__ for s in statements}
    documented = set(command.statements)
    assert produced & documented or command.statements == ("CommentStmt",), (
        f"{command.name}: example produces {produced}, entry documents "
        f"{documented}")


@pytest.mark.parametrize("command", COMMANDS, ids=lambda c: c.name)
def test_every_entry_is_complete(command):
    assert command.name == command.name.upper()
    assert command.usage and command.summary and command.example
    assert command.topic in TOPICS
    assert command.dialect in (BASIC, ACORN, LINUX, OLCA)
    assert command.statements
    assert not command.summary.endswith(".")
    for text in (command.usage, command.summary, command.notes, command.syntax):
        assert "—" not in text and "–" not in text    # no dashes


def test_names_and_aliases_are_unique():
    words = [w for c in COMMANDS for w in (c.name,) + c.aliases]
    assert len(words) == len(set(words))


def test_every_statement_keyword_of_the_parser_is_documented():
    """Each keyword parse_statement dispatches on starts some entry's
    name or alias (or is one of the refused BASIC words)."""
    source = (ROOT / "olcabasic" / "parser.py").read_text(encoding="utf-8")
    body = source[source.index("def parse_statement"):source.index("# ── Flags")]
    keywords = set(re.findall(r'kw == "([A-Z]+)"', body))
    keywords |= {w for group in re.findall(r'kw in \(([^)]*)\)', body)
                 for w in re.findall(r'"([A-Z]+)"', group)}
    refused = {"GOTO", "GOSUB", "RETURN", "ON", "LOAD", "HISTORY", "INSPECT",
               "LIST", "NEW"}
    first_words = {w.split()[0] for c in COMMANDS for w in (c.name,) + c.aliases}
    assert keywords - refused - first_words == set()


# ── the three dialects ───────────────────────────────────────

@pytest.mark.parametrize("acorn,linux", [("CAT", "LS"), ("DIR", "CD"),
                                         ("UP", "CD ..")])
def test_acorn_form_is_primary_and_linux_form_is_its_alias(acorn, linux):
    entry = find(acorn)
    assert entry.dialect == ACORN and entry.alias_dialect == LINUX
    assert linux in entry.aliases
    assert find(linux) is entry
    assert entry.heading == f"{acorn} / {linux}"


def test_help_shows_both_dialects_side_by_side():
    text = render("")
    for heading in ("CAT / LS", "DIR / CD", "UP / CD .."):
        assert heading in text
    assert "Acorn (CAT, DIR, UP) and Linux (LS, CD, CD ..)" in text


def test_help_for_either_dialect_word_gives_the_same_entry():
    assert render("CAT") == render("LS")
    assert render("DIR") == render("cd")
    assert "CAT is the Acorn form; LS the Linux form" in render("LS")


def test_basic_commands_are_marked_basic():
    for name in ("LET", "PRINT", "IF", "FOR", "FOR EACH", "WHILE", "SUB",
                 "FUNCTION", "DATA", "REM", "INCLUDE", "RUN", "INPUT"):
        assert find(name).dialect == BASIC, name


# ── HELP ─────────────────────────────────────────────────────

def test_help_lists_every_command(run):
    text = run("HELP")
    for c in COMMANDS:
        assert c.heading in text, c.name
    for topic in TOPICS:
        assert topic in text


def test_help_topic(run):
    text = run("HELP CALCULATE")
    assert 'CALCULATE "system" USING "method"' in text
    assert "MONTECARLO" in text and "SCENARIO" not in text.replace("SCENARIOS", "")


def test_help_command_shows_syntax_example_and_notes(run):
    text = run("HELP MAKE PROCESS")
    assert "MAKE PROCESS / PROCESS" in text
    assert 'INPUT USE PROCESS "process name", amount, unit' in text
    assert "Example:" in text and "Exactly one line is marked PRODUCT" in text


def test_help_is_case_insensitive_and_takes_several_words(run):
    assert run("help make process") == run("HELP MAKE PROCESS")
    assert run('HELP "CD .."') == run("HELP UP")


def test_help_for_a_word_with_several_forms(run):
    text = run("HELP FIND")
    assert "FIND has several forms" in text
    assert "FIND PROCESS" in text and "FIND CHEMICAL" in text


def test_old_help_topics_still_answer(run):
    assert "NAVIGATION" in run("HELP FOLDER")
    assert "deprecated" in run("HELP NEW")
    assert "SCENARIO" in run("HELP SCENARIO")
    assert "SENSITIVITY ON" in run("HELP SENSITIVITY")


def test_unknown_help_topic(run):
    text = run("HELP NONSENSE")
    assert "No help for: NONSENSE" in text and "NAVIGATION" in text


def test_stale_help_text_is_gone():
    source = (ROOT / "olcabasic" / "interpreter.py").read_text(encoding="utf-8")
    assert "olcaBASIC Commands:" not in source
    assert "INPUT NEW \"new flow\"" not in source
    text = render("")
    assert "INPUT NEW" not in text and "FLOW NEW" not in text
    for word in ("MAKE PROCESS", "EDIT PROCESS", "TREE", "LINK", "MOVE"):
        assert word in text


def test_help_works_offline():
    from olcabasic import Session
    r = Session(offline=True).run("HELP")
    assert r.ok and "olcaBASIC commands" in r.text


# ── the README reference and the overview ────────────────────

def test_readme_reference_is_the_generated_one():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert registry.update_readme(readme) == readme, (
        "README command reference is out of date: run "
        "python -m olcabasic.registry --readme README.md")


def test_readme_reference_names_every_command():
    section = registry.render_markdown()
    for c in COMMANDS:
        assert f"`{c.name}`" in section
    assert "| `CAT` / `LS` | Acorn / Linux |" in section


def test_overview_is_under_2000_tokens():
    text = render_overview()
    # a token is about four characters of English; three is a safe bound
    assert len(text) / 3 < 2000
    assert len(text.split()) < 1500


def test_overview_covers_every_command_and_the_rules():
    text = render_overview()
    for c in COMMANDS:
        assert c.usage in text, c.name
    assert 'USING "method"' in text and "CONFIRM DELETE ON" in text
    assert "olcabasic_help" in text


def test_registry_cli(tmp_path, capsys):
    readme = tmp_path / "README.md"
    readme.write_text(f"# x\n\n{registry.README_BEGIN}\nold\n{registry.README_END}\n",
                      encoding="utf-8")
    assert registry._main(["--readme", str(readme)]) == 0
    text = readme.read_text(encoding="utf-8")
    assert "old" not in text.split(registry.README_BEGIN)[1].split("### ")[0]
    assert "`MAKE PROCESS`" in text
    registry._main(["--overview"])
    assert "NAVIGATION" in capsys.readouterr().out
