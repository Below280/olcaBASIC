"""
EPD DOCUMENT: the EPD in the sections of the International EPD System
(GPI 5.1.0, section 7.4), from the model and the EPD DOCUMENT block.

Synthetic data only. The programme's own statements are never part of
olcaBASIC; here they are stand-in sentences in a file of the test's
own, as a user's statements file would be.
"""

import pytest

from olcabasic.parser import ParseError, parse
from olcabasic.workflows.epd_document import read_statements, sig
from test_epd_toolkit import (  # noqa: F401  (fixtures)
    client, fixed_date, ready, session)

STATEMENT_KEYS = ("cover", "iso14025", "operator", "ownership",
                  "comparability", "relative", "end_of_life",
                  "primary_share")


def statements_file(tmp_path, leave_out=(), name="statements.txt"):
    path = tmp_path / name
    path.write_text(
        "# stand-in statements for the test\n"
        + "".join(f"{k}: Stand-in statement {k}.\n"
                  for k in STATEMENT_KEYS if k not in leave_out)
        + "  (continued on a second line)\n",
        encoding="utf-8")
    return path


def full_block(tmp_path, out="epd.md", drop=(), extra="", statements=True):
    lines = {
        "STATEMENTS": f'STATEMENTS "{statements_file(tmp_path)}"'
                      if statements else "",
        "OWNER": 'OWNER "Example Timber Ltd"',
        "OWNER ADDRESS": 'OWNER ADDRESS "1 Mill Lane, Hexham, NE46 1AA, '
                         'United Kingdom"',
        "OWNER CONTACT": 'OWNER CONTACT "epd@example.com"',
        "OWNER DESCRIPTION": 'OWNER DESCRIPTION "A sawmill."',
        "PRODUCT DESCRIPTION": 'PRODUCT DESCRIPTION "Kiln-dried sawn '
                               'softwood for construction."',
        "PRODUCT IDENTIFICATION": 'PRODUCT IDENTIFICATION "Strength '
                                  'class C16 to EN 338"',
        "PRODUCT CODE": 'PRODUCT CODE "UN CPC", "3110", "Wood, sawn"',
        "MANUFACTURING": 'MANUFACTURING "Logs are sawn, kiln-dried and '
                         'planed."',
        "SITE": 'SITE "Hexham, United Kingdom"',
        "CONTENT": 'CONTENT "Timber", 1 kg BIOGENIC 100%',
        "SVHC": "SVHC NONE",
        "GEOGRAPHY": 'GEOGRAPHY A1, A2, A3, C1, C2, C3, C4, D "GB"',
        "SCENARIO": 'SCENARIO C1, C2, C3, C4, D "Demolished by hand, '
                    '50 km by lorry, 90% burnt for energy, 10% landfill."',
        "OMITTED": 'OMITTED A4, A5, B1, B2, B3, B4, B5, B6, B7 "Depend on '
                   'the building the product goes into."',
        "REGISTRATION": 'REGISTRATION "EPD-IES-0000000"',
        "VERSION DATE": 'VERSION DATE "2026-11-13"',
        "VALID UNTIL": 'VALID UNTIL "2031-11-12"',
        "VERIFICATION": 'VERIFICATION "Individual EPD verification"',
        "VERIFIER": 'VERIFIER "A. Verifier, Example Verification"',
        "APPROVED BY": 'APPROVED BY "The International EPD System"',
        "FOLLOW UP": "FOLLOW UP NO",
        "SOFTWARE": 'SOFTWARE "openLCA 2.7.0"',
        "METHOD VERSION": 'METHOD VERSION "EF 3.1"',
        "DIAGRAM": f'DIAGRAM "{tmp_path / "flow.png"}"',
        "IMAGE": f'IMAGE "{tmp_path / "product.png"}"',
        "LOGO": f'LOGO "{tmp_path / "logo.png"}"',
    }
    for name in ("flow.png", "product.png", "logo.png"):
        (tmp_path / name).write_bytes(b"png")
    body = "\n".join(f"  {v}" for k, v in lines.items()
                     if k not in drop and v)
    return (f'EPD DOCUMENT "{tmp_path / out}"\n{body}\n{extra}'
            f'END EPD DOCUMENT\n')


@pytest.fixture
def reported(session, client, tmp_path):
    ready(session, client)
    r = session.run(f'EPD DATA QUALITY\nEPD REPORT "{tmp_path / "r.csv"}"')
    assert r.ok, f"{r.errors}\n{r.text}"
    return session


def refused(r, *words):
    assert not r.ok, r.text
    text = r.errors[0]["message"] + " " + r.errors[0]["hint"]
    for w in words:
        assert w in text, f"{w!r} not in:\n{text}"
    return text


# ── numbers ──────────────────────────────────────────────────

@pytest.mark.parametrize("value, shown", [
    (123.45, "1.2E+2"), (0.12345, "1.2E-1"), (0, "0"), (-0.0042, "-4.2E-3"),
    (1, "1.0E+0")])
def test_two_significant_digits(value, shown):
    assert sig(value) == shown


def test_statements_file(tmp_path):
    got = read_statements(statements_file(tmp_path))
    assert got["cover"] == "Stand-in statement cover."
    assert got["primary_share"].endswith("(continued on a second line)")


# ── the block ────────────────────────────────────────────────

def test_the_block_parses(tmp_path):
    stmt = parse(full_block(tmp_path))[0]
    keys = [e["key"] for e in stmt.lines]
    assert "OWNER ADDRESS" in keys and "FOLLOW UP" in keys
    content = next(e for e in stmt.lines if e["key"] == "CONTENT")
    assert content["unit"] == "kg" and content["options"] == {
        "BIOGENIC": 100.0}


@pytest.mark.parametrize("line, words", [
    ("  CONTENT \"Timber\", 1\n", "needs a unit"),
    ("  SVHC \"Lead\", \"231-100-4\"\n", "comma"),
    ("  NONSENSE \"x\"\n", "not a line of an EPD DOCUMENT block"),
    ("  FOLLOW UP MAYBE\n", "YES or NO"),
])
def test_bad_lines_are_parse_errors(line, words):
    with pytest.raises(ParseError) as e:
        parse(f'EPD DOCUMENT "x.md"\n{line}END EPD DOCUMENT\n')
    assert words in str(e.value)


# ── the gates ────────────────────────────────────────────────

def test_refused_before_epd_report(session, client, tmp_path):
    ready(session, client)
    refused(session.run(full_block(tmp_path)), "EPD DOCUMENT refused",
            "EPD REPORT has not passed")
    assert not (tmp_path / "epd.md").exists()


def test_refused_without_a_programme(session, client, tmp_path):
    from test_epd_toolkit import block, bridges, modules, PARAMS
    r = session.run(PARAMS + block(programme=False) + bridges(client)
                    + modules() + "EPD SYSTEMS\nEPD CHECK\nEPD CALCULATE\n"
                    + f'EPD REPORT "{tmp_path / "r.csv"}"\n')
    assert r.ok, r.text
    refused(session.run(full_block(tmp_path)), "International EPD System",
            'PROGRAMME "IES"')


def test_everything_missing_is_listed_at_once(reported, tmp_path):
    text = refused(
        reported.run(full_block(tmp_path, drop=(
            "OWNER ADDRESS", "PRODUCT DESCRIPTION", "SITE", "SVHC",
            "GEOGRAPHY", "SCENARIO", "OMITTED"))),
        "EPD DOCUMENT refused", "OWNER ADDRESS", "PRODUCT DESCRIPTION",
        "SITE", "SVHC", "module A1 is declared and has no geographical",
        "module C1 is declared and its scenario", "module A4 is not "
        "declared, and the reason", "Nothing was written")
    assert "GPI 5.1.0, 7.4" in text
    assert not (tmp_path / "epd.md").exists()


def test_biogenic_share_is_required_on_each_material(reported, tmp_path):
    block = full_block(tmp_path).replace(
        'CONTENT "Timber", 1 kg BIOGENIC 100%', 'CONTENT "Timber", 1 kg')
    refused(reported.run(block), "biogenic carbon", "BIOGENIC n%")


def test_a_small_svhc_is_not_declared_as_one(reported, tmp_path):
    block = full_block(tmp_path).replace(
        "SVHC NONE", 'SVHC "Lead", "231-100-4", "7439-92-1", 0.05%')
    refused(reported.run(block), "not above 0.1%")


def test_dates_are_iso(reported, tmp_path):
    block = full_block(tmp_path).replace('"2031-11-12"', '"12/11/2031"')
    refused(reported.run(block), "YYYY-MM-DD")


# ── the document ─────────────────────────────────────────────

def test_a_complete_document(reported, tmp_path):
    r = reported.run(full_block(tmp_path))
    assert r.ok, f"{r.errors}\n{r.text}"
    assert "Every section the programme requires is filled in" in r.text
    doc = (tmp_path / "epd.md").read_text(encoding="utf-8")
    assert "DRAFT" not in doc
    order = ["# Environmental Product Declaration: Test timber",
             "## General information", "### Programme information",
             "### Product category rules (PCR)", "### Verification",
             "### Ownership and limitations on use of the EPD",
             "## Information about the EPD owner", "## Product information",
             "## Content declaration", "## LCA information",
             "### Modules declared and geographical scope",
             "## Environmental performance", "## Version history",
             "## Abbreviations", "## References"]
    at = [doc.index(h) for h in order]
    assert at == sorted(at)
    for text in ("EPD-IES-0000000", "EPD International AB",
                 "Stand-in statement ownership.",
                 "Stand-in statement end_of_life.",
                 "| Declared | X | X | X | ND | ND |",
                 "Cradle to gate with modules C1-C4 and module D",
                 "UN CPC code | 3110: Wood, sawn",
                 "0.45 kg C per declared unit",
                 "Share of primary data", "Test PCR 1.0",
                 "Depend on the building the product goes into.",
                 "Original version of the EPD", "| GWP-GHG |",
                 "Module D is declared on its own"):
        assert text in doc, text
    assert doc.count("E+") + doc.count("E-") > 10   # two-digit results


def test_a_draft_says_what_is_missing(reported, tmp_path):
    r = reported.run(full_block(tmp_path, drop=(
        "REGISTRATION", "VERIFIER", "DIAGRAM"), statements=False))
    assert r.ok, f"{r.errors}\n{r.text}"
    assert "It is a DRAFT" in r.text and "REGISTRATION" in r.text
    doc = (tmp_path / "epd.md").read_text(encoding="utf-8")
    assert doc.startswith("> **DRAFT, not for publication.**")
    assert "[DRAFT: the statement 'ownership' required by GPI 5.1.0, " \
           "7.4.2.4" in doc


def test_a_statement_missing_from_the_file_makes_a_draft(reported,
                                                         tmp_path):
    block = full_block(tmp_path)
    path = statements_file(tmp_path, leave_out=("comparability",),
                           name="short.txt")
    block = block.replace(
        f'STATEMENTS "{tmp_path / "statements.txt"}"',
        f'STATEMENTS "{path}"')
    r = reported.run(block)
    assert r.ok, r.text
    assert "the statement 'comparability'" in r.text


def test_the_document_follows_the_model(reported, tmp_path):
    """Change the model and the document is refused until the report
    is run again."""
    assert reported.run("EPD CALCULATE").ok
    refused(reported.run(full_block(tmp_path)),
            "EPD REPORT has not passed since the results were last "
            "calculated")


def test_dry_run_and_help(tmp_path):
    from olcabasic import Session
    s = Session(offline=True)
    assert "EPD DOCUMENT" in s.run("HELP EPD DOCUMENT").text
    r = s.run(full_block(tmp_path), dry_run=True)
    assert any("EPD DOCUMENT needs an EPD" in e["message"]
               for e in r.errors)
