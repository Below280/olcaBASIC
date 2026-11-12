"""Navigation speaks Acorn and Linux. Every Acorn command and its Linux
form must give identical results; where they differ (CDIR and MKDIR)
the difference is the documented one."""

import pytest

from fake_client import seed_ecoinvent_like
from olcabasic import Session
from olcabasic import ast_nodes as ast
from olcabasic.parser import parse


def fresh():
    return Session(client=seed_ecoinvent_like())


def state(session):
    rt = session.runtime
    return (rt.navigation_mode, dict(rt.nav_folders), dict(rt.nav_previous),
            rt.process_folder, rt.flow_folder)


def both(prelude, acorn, linux):
    """Run prelude then one form in each of two fresh sessions; return
    the two (text, state) pairs."""
    out = []
    for command in (acorn, linux):
        s = fresh()
        assert s.run(prelude).ok
        r = s.run(command)
        assert r.ok, r.errors
        out.append((r.text, state(s)))
    return out


PRELUDE = 'DIR "D:Test supply"\nDIR "35:Test supply"'


@pytest.mark.parametrize("acorn,linux", [
    ("CAT", "LS"),
    ('CAT "C:Test manufacturing"', 'LS "C:Test manufacturing"'),
    ("CAT FLOWS", "LS FLOWS"),
    ("CAT *test*", "LS *test*"),
    ('DIR "351:Test generation"', 'CD "351:Test generation"'),
    ('DIR "C:Test manufacturing"', 'CD "C:Test manufacturing"'),
    ("DIR", "CD"),
    ("UP", "CD .."),
    ("BACK", "CD -"),
    ('DIR "/"', "CD /"),
])
def test_acorn_and_linux_forms_give_identical_results(acorn, linux):
    a, b = both(PRELUDE, acorn, linux)
    assert a == b
    assert a[0]          # something was shown


@pytest.mark.parametrize("acorn,linux,node", [
    ("CAT", "LS", ast.CatStmt), ('DIR "x"', 'CD "x"', ast.DirStmt),
    ("UP", "CD ..", ast.UpStmt), ("BACK", "CD -", ast.BackStmt),
    ('DIR "/"', "CD /", ast.DirStmt),
])
def test_both_forms_parse_to_the_same_statement(acorn, linux, node):
    a, b = parse(acorn)[0], parse(linux)[0]
    assert type(a) is type(b) is node
    a.line = b.line = 0
    assert a == b


def test_cd_dash_goes_back_and_forth_like_back():
    s = fresh()
    s.run('DIR "C:Test manufacturing"\nDIR "D:Test supply"')
    assert s.run("CD -").text.strip() == "C:Test manufacturing"
    assert s.run("CD -").text.strip() == "D:Test supply"
    assert s.run("BACK").text.strip() == "C:Test manufacturing"


def test_cd_slash_goes_to_the_top_level():
    s = fresh()
    s.run(PRELUDE)
    assert s.run("CD /").text.strip() == "(root)"
    assert s.runtime.nav_folders["PROCESSES"] == ""
    assert s.run("CD -").text.strip() == "D:Test supply/35:Test supply"


def test_pwd_shows_browsing_and_building():
    s = fresh()
    s.run(PRELUDE + '\nSET PROCESS FOLDER "00: Mine"')
    text = s.run("PWD").text
    assert "[Processes] D:Test supply/35:Test supply" in text
    assert "Build processes:  00: Mine" in text


# ── CDIR and MKDIR: the documented difference ────────────────

def test_cdir_creates_enters_and_builds_there():
    s = fresh()
    r = s.run('CDIR "00: New"')
    assert "Created and moved to: 00: New" in r.text
    assert s.runtime.nav_folders["PROCESSES"] == "00: New"
    assert s.runtime.process_folder == "00: New"


def test_mkdir_creates_without_entering_or_changing_the_build_folder():
    s = fresh()
    s.run('DIR "C:Test manufacturing"\nSET PROCESS FOLDER "00: Elsewhere"')
    before = state(s)
    r = s.run('MKDIR "New sub"')
    assert r.ok and "Created: C:Test manufacturing/New sub" in r.text
    assert "You are still in: C:Test manufacturing" in r.text
    assert state(s) == before


def test_folder_made_with_mkdir_can_be_listed_and_entered():
    s = fresh()
    s.run('MKDIR "00: Made"')
    assert "[DIR]  00: Made/" in s.run("CAT").text
    assert "[DIR]  00: Made/" in s.run("LS").text
    assert s.run('CD "00: Made"').text.strip() == "00: Made"
    assert "(empty)" in s.run("CAT").text


def test_mkdir_nested_and_existing():
    s = fresh()
    s.run('MKDIR "00: A/B"')
    assert s.run('DIR "00: A"').ok and s.run('DIR "B"').ok
    r = s.run('CD /\nMKDIR "C:Test manufacturing"')
    assert "Folder already exists: C:Test manufacturing" in r.text


def test_mkdir_needs_a_name():
    r = fresh().run("MKDIR")
    assert not r.ok and "MKDIR needs a folder name" in r.errors[0]["message"]
    assert 'MKDIR "00: My model"' in r.errors[0]["hint"]


def test_mkdir_and_cdir_folders_are_forgotten_on_reset():
    s = fresh()
    s.run('MKDIR "00: Made"')
    s.reset()
    assert not s.run('DIR "00: Made"').ok


def test_unknown_folder_error_names_both_ways_to_create_one():
    r = fresh().run('CD "Nowhere"')
    assert not r.ok
    assert "CDIR" in r.errors[0]["hint"] and "MKDIR" in r.errors[0]["hint"]


# ── Acorn meaning wins ───────────────────────────────────────

def test_cat_lists_a_folder_it_does_not_print_a_file(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("file contents", encoding="utf-8")
    r = fresh().run(f'CAT "{f.as_posix()}"')
    assert "file contents" not in r.text and "0 folders, 0 entities" in r.text


@pytest.mark.parametrize("word", ["rm", "mv", "cp", "touch"])
def test_linux_words_that_would_clash_are_not_commands(word):
    r = fresh().run(f'{word} "x"', dry_run=True)
    assert not r.ok and f"SUB '{word}' is not defined" in r.errors[0]["message"]


def test_every_navigation_keyword_still_exists():
    from olcabasic.tokeniser import KEYWORDS
    assert {"CAT", "DIR", "CDIR", "UP", "BACK", "LS", "CD", "PWD", "MKDIR",
            "NAVIGATE"} <= KEYWORDS
