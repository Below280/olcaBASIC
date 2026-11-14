"""
What a hard stress run on 13-14/11/2026 found. Each case was a crash
(a Python error reaching the user), a hang, a rule that could be got
round, or something accepted that should not have been. Each now gives
a plain error, or works.
"""

import datetime

import olca_schema as o
import pytest

from fake_client import STEEL, seed_ecoinvent_like
from olcabasic import Session
from olcabasic.workflows.epd import EpdWorkflow
from test_interpreter_lca import B_STEEL, SETUP, WIDGET

EF = "EF v3.1"


@pytest.fixture
def s(client):
    return Session(client=client)


def refused(r, *words):
    assert not r.ok, r.text
    text = r.errors[0]["message"] + " " + r.errors[0].get("hint", "")
    for w in words:
        assert w in text, f"{w!r} not in {text!r}"
    return text


# ── arithmetic and expressions ───────────────────────────────

@pytest.mark.parametrize("code, words", [
    ("PRINT 10^400", "too large for a number"),
    ("PRINT SQR(-1)", "SQR(-1) has no value"),
    ("PRINT LOG(0)", "LOG(0) has no value"),
    ('PRINT "a" * 3', "'*' cannot work on the text \"a\" and the number 3"),
    ('PRINT "a" - 1', "'-' cannot work on"),
    ('IF "a" < 1 THEN PRINT 1', "'<' cannot compare the text"),
    ('PRINT VAL("12abc")', "the text is not a number"),
    ("PRINT (-8) ^ 0.5", "has no real value"),
    ("PRINT " + "(" * 2000 + "1" + ")" * 2000, "nests too deeply"),
    ("PRINT " + "+".join(["1"] * 20000), "nests too deeply"),
])
def test_bad_arithmetic_is_a_plain_error(s, code, words):
    refused(s.run(code), words)


def test_string_functions(s):
    r = s.run('PRINT LEFT$("abcdef", 2)\nPRINT RIGHT$("abcdef", 3)\n'
              'PRINT MID$("abcdef", 2, 3)\nPRINT INSTR("abcdef", "cd")\n'
              'PRINT SGN(-4)')
    assert r.ok, r.errors
    assert r.text.split() == ["ab", "def", "bcd", "3", "-1"]


# ── programs that never end, and recursion ───────────────────

def test_a_while_loop_that_never_ends_is_stopped(s, monkeypatch):
    import olcabasic.interpreter as interp
    monkeypatch.setattr(interp, "LOOP_LIMIT", 1000)
    refused(s.run("LET i = 0\nWHILE 1\n  LET i = i + 1\nWEND"),
            "has run 1,000 times")


def test_a_huge_for_loop_is_refused_before_it_starts(s):
    refused(s.run("FOR i = 1 TO 1e12\nNEXT i"), "would run")


def test_a_sub_that_calls_itself_forever(s):
    refused(s.run("SUB F\n  F\nEND SUB\nF"), "calls itself")
    # and the session still works at the top level afterwards
    r = s.run("LET a = 1 UNCERTAINTY UNIFORM 0.5, 2")
    assert r.ok, r.errors


def test_call_name_calls_the_sub(s):
    r = s.run('SUB Hello\n  PRINT "hi"\nEND SUB\nCALL Hello')
    assert r.ok and "hi" in r.text


@pytest.mark.parametrize("code, words", [
    ("FUNCTION F(a, b)\n  F = a + b\nEND FUNCTION\nPRINT F(1)",
     "FUNCTION F takes 2 values (a, b), and was given 1"),
    ("FUNCTION F(a)\n  F = a\nEND FUNCTION\nPRINT F(1, 2)",
     "and was given 2"),
    ("SUB S(a)\n  PRINT a\nEND SUB\nS", "SUB S takes 1 value (a)"),
    ("mystery 1", "'mystery' is not a command"),
])
def test_calls_with_the_wrong_values(s, code, words):
    refused(s.run(code), words)


# ── text that came from somewhere else ───────────────────────

def test_a_byte_order_mark_is_ignored(s):
    assert s.run("﻿PRINT 1").ok


def test_a_doubled_quote_is_a_quote(s, client):
    r = s.run(SETUP + 'MAKE PROCESS "Bob""s widget"\n  OUTPUT MAKE FLOW '
              '"Bob""s widget", 1, kg, PRODUCT\nEND PROCESS')
    assert r.ok, r.errors
    assert client.by_name(o.Process, 'Bob"s widget')


# ── amounts and limits ───────────────────────────────────────

@pytest.mark.parametrize("amount, words", [
    ("0", "cannot be zero"), ("-1", "cannot be negative")])
def test_a_reference_amount_is_above_zero(s, amount, words):
    refused(s.run(SETUP + f'MAKE PROCESS "A"\n  OUTPUT MAKE FLOW "A", '
                          f'{amount}, kg, PRODUCT\nEND PROCESS'), words)


def test_an_infinite_amount_is_refused(s):
    refused(s.run(SETUP + 'MAKE PROCESS "A"\n  OUTPUT MAKE FLOW "A", 1, kg, '
                          'PRODUCT\n  OUTPUT "Carbon dioxide, fossil", '
                          '1e308*10, kg TO AIR\nEND PROCESS'),
            "too large for a number")


@pytest.mark.parametrize("tail, words", [
    (f'CONTRIBUTION "Widget" USING "{EF}" TOP 0', "TOP needs a number above 0"),
    (f'MONTECARLO "Widget" USING "{EF}" RUNS 100000000',
     "more than the limit of 100,000"),
    (f'SENSITIVITY ON "Widget" USING "{EF}" BY 150%\n  VARY elec\n'
     f'END SENSITIVITY', "down to zero or below"),
])
def test_limits(s, tail, words):
    refused(s.run(WIDGET + 'VALIDATE "Widget"\n' + tail), words)


def test_a_value_outside_its_own_range(s):
    refused(s.run("LET a = 10 UNCERTAINTY UNIFORM 1, 2"),
            "outside its own UNIFORM range 1 to 2")


@pytest.mark.parametrize("year", [0, 1899, datetime.date.today().year + 1])
def test_a_reference_year_is_a_real_year(s, year):
    refused(s.run(SETUP + f'MAKE PROCESS "T"\n  DATA PRIMARY SOURCE "x" '
                          f'PROVIDER "y" YEAR {year}\n  OUTPUT MAKE FLOW "T",'
                          f' 1, kg, PRODUCT\nEND PROCESS'),
            "is not a reference year")


def test_an_unknown_location_is_refused(s):
    refused(s.run(SETUP + 'MAKE PROCESS "T"\n  LOCATION "XX-NOPE"\n  OUTPUT '
                          'MAKE FLOW "T", 1, kg, PRODUCT\nEND PROCESS'),
            "No location has the code or name 'XX-NOPE'")


def test_a_flow_of_another_type_is_not_reused(s):
    refused(s.run(SETUP + 'MAKE FLOW "Q", kg, PRODUCT\nMAKE FLOW "Q", kg, '
                          'WASTE'), "already exists", "as a product flow")


# ── scenarios and sensitivity with a name that is not there ──

def test_a_scenario_with_a_parameter_the_system_lacks(s):
    refused(s.run(WIDGET + f'VALIDATE "Widget"\nSCENARIO "s"\n  LET nope = 1'
                           f'\nEND SCENARIO\nRUN SCENARIOS ON "Widget" USING'
                           f' "{EF}"'),
            "no input parameter called 'nope'")


def test_sensitivity_with_a_parameter_the_system_lacks(s, client):
    refused(s.run(WIDGET + f'VALIDATE "Widget"\nSENSITIVITY ON "Widget" '
                           f'USING "{EF}" BY 10%\n  VARY elec, nope\n'
                           f'END SENSITIVITY'),
            "no input parameter called 'nope'")


# ── EPD ──────────────────────────────────────────────────────

def test_an_epd_unit_that_openlca_does_not_know(monkeypatch):
    import test_epd_toolkit as t
    monkeypatch.setattr(EpdWorkflow, "today",
                        staticmethod(lambda: datetime.date(2026, 11, 12)))
    c = t.add_epd_methods(seed_ecoinvent_like())
    s = Session(client=c)
    s.run('DATABASE FAMILY "ecoinvent"')
    refused(s.run(t.block().replace("DECLARED UNIT 1, kg",
                                    "DECLARED UNIT 1, bananas")),
            "'bananas' is not a unit openLCA knows")


# ── the rules ────────────────────────────────────────────────

def test_deleting_a_bridge_a_system_uses_is_refused(s, client):
    assert s.run(WIDGET + 'VALIDATE "Widget"').ok
    refused(s.run(f'DELETE PROCESS "{B_STEEL}"'), 'product system "Widget"')


def test_calculating_a_background_process_on_its_own_is_allowed(s):
    """Looking at a background dataset's own results is not a breach of
    the bridge rule: there is no model of yours in it."""
    r = s.run(f'SYSTEM "{STEEL}"\nCALCULATE "{STEEL}" USING "{EF}"')
    assert r.ok, r.errors


def _epd_calculated(monkeypatch):
    import test_epd_toolkit as t
    monkeypatch.setattr(EpdWorkflow, "today",
                        staticmethod(lambda: datetime.date(2026, 11, 12)))
    c = t.add_epd_methods(seed_ecoinvent_like())
    s = Session(client=c)
    s.run('DATABASE FAMILY "ecoinvent"')
    r = s.run(t.PARAMS + t.block() + t.bridges(c) + t.modules() + t.STEPS)
    assert r.ok, r.text
    return s


def test_a_parameter_written_after_epd_calculate_sets_the_results_aside(
        monkeypatch, tmp_path):
    s = _epd_calculated(monkeypatch)
    r = s.run("UPDATE PARAMETER kiln_kwh = 99")
    assert "was calculated with the old value of kiln_kwh" in r.text
    refused(s.run(f'EPD DATA QUALITY\nEPD REPORT "{tmp_path / "r.csv"}"'),
            "needs the results")


def test_let_on_a_global_says_openlca_still_has_the_old_value(monkeypatch):
    s = _epd_calculated(monkeypatch)
    r = s.run("LET kiln_kwh = 99")
    assert r.ok
    assert "kiln_kwh is a global parameter in openLCA, where it is 2" in r.text


@pytest.mark.parametrize("folder, background", [
    ("C:Manufacturing/24:Manufacture of basic metals", True),
    ("E:Water supply; sewerage, waste management and remediation "
     "activities", True),
    ("31-33: Manufacturing", True), ("21: Mining", True),
    ("Recycled content cut-off", True),
    ("00: My model", False), ("00: olcaBASIC live test/Bridges", False),
    ("My model", False), ("Examples", False), ("", False),
])
def test_which_folders_are_background(folder, background):
    from olcabasic.background import is_background_folder
    assert is_background_folder(folder) is background


def test_a_dry_run_of_a_huge_expression(s):
    r = s.run("PRINT " + "+".join(["1"] * 20000), dry_run=True)
    assert not r.ok and "nests too deeply" in r.errors[0]["message"]


def test_include_with_no_name_or_a_folder(s, tmp_path):
    refused(s.run('INCLUDE ""'), "INCLUDE needs a file name")
    refused(s.run(f'INCLUDE "{tmp_path}"'), "is a folder")


def test_a_program_file_saved_by_notepad_in_cp1252(s, tmp_path):
    path = tmp_path / "old.baslca"
    path.write_bytes('PRINT "caf\xe9"\n'.encode("cp1252"))
    r = s.run(f'RUN "{path}"')
    assert r.ok and "café" in r.text
    path.write_bytes(b"\xef\xbb\xbfPRINT 7\n")          # UTF-8 with a BOM
    r = s.run(f'INCLUDE "{path}"')
    assert r.ok and "7" in r.text


def test_a_number_too_large_to_hold_is_refused(s):
    refused(s.run("PRINT 1e400"), "too large for a number")
    assert s.run("PRINT 1.7e308").ok


# ── EPD DOCUMENT with awkward lines ──────────────────────────

def _document(monkeypatch, tmp_path, old, new, out="epd.md"):
    import test_epd_document as td
    import test_epd_toolkit as t
    monkeypatch.setattr(EpdWorkflow, "today",
                        staticmethod(lambda: datetime.date(2026, 11, 12)))
    c = t.add_epd_methods(seed_ecoinvent_like())
    s = Session(client=c)
    s.run('DATABASE FAMILY "ecoinvent"')
    t.ready(s, c)
    assert s.run(f'EPD DATA QUALITY\nEPD REPORT "{tmp_path / "r.csv"}"').ok
    block = td.full_block(tmp_path, out=out)
    assert old in block
    return s.run(block.replace(old, new))


@pytest.mark.parametrize("old, new, words", [
    ('CONTENT "Timber", 1 kg BIOGENIC 100%',
     'CONTENT "Timber", 0 kg BIOGENIC 100%', "needs a mass above 0"),
    ('CONTENT "Timber", 1 kg BIOGENIC 100%',
     'CONTENT "Timber", 5 kg BIOGENIC 100%', "the materials add up to 5 kg"),
    ('SVHC NONE', 'SVHC NONE\n  PACKAGING "Wrap", 0 kg',
     "PACKAGING 'Wrap'"),
    ('GEOGRAPHY A1, A2, A3, C1, C2, C3, C4, D "GB"',
     'GEOGRAPHY A1, A2, A3, C1, C2, C3, C4, D "GB"\n  GEOGRAPHY A1 "FR"',
     "module A1 is on line"),
])
def test_document_lines_that_do_not_add_up(monkeypatch, tmp_path, old, new,
                                           words):
    refused(_document(monkeypatch, tmp_path, old, new), words)


@pytest.mark.parametrize("out", ["epd.md", "epd.docx"])
def test_free_text_that_looks_like_markup_stays_text(monkeypatch, tmp_path,
                                                     out):
    import zipfile
    r = _document(monkeypatch, tmp_path, 'OWNER DESCRIPTION "A sawmill."',
                  'OWNER DESCRIPTION "# Not a heading\x01"', out)
    assert r.ok, r.errors
    if out == "epd.md":
        assert "\\# Not a heading" in (tmp_path / out).read_text("utf-8")
    else:
        xml = zipfile.ZipFile(tmp_path / out).read(
            "word/document.xml").decode("utf-8")
        assert '<w:t xml:space="preserve"># Not a heading</w:t>' in xml
        assert "\x01" not in xml


# ── SUB and FUNCTION heads that used to hang the parser ──────

@pytest.mark.parametrize("code, words", [
    ("SUB A(1)\nEND SUB", "the values it takes are names"),
    ("SUB A(x\nPRINT 1", "got the end of the line"),
    ("FUNCTION F(1, 2)\nEND FUNCTION", "the values it takes are names"),
    ("SUB 5\nEND SUB", "SUB needs a name"),
    ("SUB A(x, x)\nEND SUB", "names 'x' twice"),
    ("SUB A\nEND FUNCTION", "ends with END SUB"),
    ("FUNCTION F(x) AS\nEND FUNCTION", "AS needs a type name"),
])
def test_a_bad_sub_or_function_head_is_an_error_not_a_hang(s, code, words):
    refused(s.run(code), words)


@pytest.mark.parametrize("code, words", [
    ("PRINT ABS(1", "missing its closing )"),
    ("PRINT ABS(1 2)", "expected a comma or )"),
    ("PRINT ABS(", "The line ends where a value was expected"),
    ("PRINT SQR(4, 5)", "SQR takes 1 value, and was given 2"),
    ("PRINT ABS()", "ABS takes 1 value, and was given 0"),
    ('PRINT MID$("abc", 0, 2)', "the start is 1 or more"),
    ('PRINT LEFT$("abc", -1)', "cannot be below 0"),
    ('FOR i = "a" TO 3\nNEXT i', 'FOR needs a number for the start'),
])
def test_function_calls_and_loops_with_wrong_values(s, code, words):
    refused(s.run(code), words)


@pytest.mark.parametrize("folder, words", [
    ("00: A/../B", "has a . or .. folder in it"),
    ("00: A\\B", "has a \\ in it"),
    ("c:manufacturing", "is a background folder"),
    ("00: A//B", "has an empty folder name"),
])
def test_folder_paths_that_would_mislead(s, folder, words):
    refused(s.run(f'SET PROCESS FOLDER "{folder}"'), words)
    refused(s.run(f'MKDIR "{folder}"'), words)


def test_folder_paths_are_tidied(s):
    r = s.run('SET PROCESS FOLDER "/00: A/ B /"\nMKDIR " 00: C / D "\nPWD')
    assert r.ok, r.errors
    assert "Build processes:  00: A/B" in r.text
    assert "Created: 00: C/D" in r.text
