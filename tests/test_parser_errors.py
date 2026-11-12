"""The parser refuses what it does not understand, and says why."""

import pytest

from olcabasic.parser import ParseError, parse, parse_line


def error(source):
    with pytest.raises(ParseError) as e:
        parse(source)
    return e.value


def test_line_numbers_are_refused():
    e = error('10 PRINT "hello"')
    assert "Line numbers are not supported" in str(e) and e.line == 1


@pytest.mark.parametrize("word", ["GOTO", "GOSUB", "RETURN", "HISTORY",
                                  "INSPECT", "NEW"])
def test_unsupported_basic_keywords_say_so(word):
    assert f"{word} is not supported in olcaBASIC" in str(error(f"{word} 10"))


def test_error_carries_the_line():
    e = error('PRINT 1\nPRINT 2\nLET = 5')
    assert e.line == 3 and str(e).startswith("Line 3:")


def test_reserved_word_as_variable():
    e = error("LET process = 5")
    assert "reserved word" in str(e) and "my_process" in str(e)


def test_trailing_text_is_refused():
    assert "Unexpected 'extra'" in str(error('PRINT "a" extra'))


def test_missing_closing_bracket():
    assert "Missing closing ')'" in str(error("LET x = (1 + 2"))


def test_tokeniser_errors_become_parse_errors():
    e = error('PRINT 1\nPRINT "a" & "b"')
    assert e.line == 2 and "use + to join strings" in str(e)


@pytest.mark.parametrize("source,needle", [
    ('PROCESS "P"\n INPUT "a", 1, kg', "PROCESS block missing END PROCESS"),
    ('SCENARIO "S"\n LET a = 1', "SCENARIO block missing END SCENARIO"),
    ('SENSITIVITY ON "W" USING "M" BY 5\n VARY a', "missing END SENSITIVITY"),
    ('IF x = 1 THEN\n PRINT 1', "IF block missing END IF"),
    ("FOR i = 1 TO 3\n PRINT i", "FOR missing NEXT"),
    ('FOR EACH x IN 1, 2\n PRINT x', "FOR EACH missing NEXT"),
    ("WHILE x < 2\n PRINT x", "WHILE missing WEND"),
    ("SUB s()\n PRINT 1", "SUB missing END SUB"),
    ("FUNCTION f()\n PRINT 1", "FUNCTION missing END FUNCTION"),
    ('EDIT PROCESS "P"\n SET LOCATION "GB"', "EDIT block missing END EDIT"),
    ('EDIT FLOW "F"\n SET REFERENCE "Mass"', "EDIT FLOW block missing END EDIT"),
])
def test_unclosed_blocks(source, needle):
    assert needle in str(error(source))


@pytest.mark.parametrize("source,needle", [
    ('PROCESS "P"\n PRINT 1\nEND PROCESS', "is not allowed inside PROCESS"),
    ('SCENARIO "S"\n PRINT 1\nEND SCENARIO', "is not allowed inside SCENARIO"),
    ('SENSITIVITY ON "W" USING "M" BY 5\n PRINT 1\nEND SENSITIVITY',
     "is not allowed inside SENSITIVITY"),
    ('EDIT PROCESS "P"\n PRINT 1\nEND EDIT', "is not allowed inside EDIT"),
    ('EDIT FLOW "F"\n PRINT 1\nEND EDIT', "is not allowed inside EDIT FLOW"),
    ('SYSTEM "P"\n LINKING ONLY_DEFAULTS\n PRINT 1\nEND SYSTEM',
     "is not allowed inside SYSTEM"),
    ('BRIDGE "B", kg\n FOLDER "x"\n PRINT 1\nEND BRIDGE',
     "is not allowed inside BRIDGE"),
])
def test_wrong_statement_inside_a_block(source, needle):
    assert needle in str(error(source))


def test_error_inside_process_block_reports_its_own_line():
    e = error('PROCESS "P"\n INPUT "a", 1, kg\n PRINT 1\nEND PROCESS')
    assert e.line == 3


def test_calculate_requires_using():
    assert "Expected USING" in str(error('CALCULATE "W"'))


@pytest.mark.parametrize("source", [
    'CONTRIBUTION "W"', 'INVENTORY "W"', 'MONTECARLO "W"', 'TREE "W"',
    'SENSITIVITY ON "W"\nEND SENSITIVITY', 'RUN SCENARIOS ON "W"',
])
def test_every_analysis_requires_a_method(source):
    assert "Expected USING" in str(error(source))


def test_delete_flow_parses():
    """Changed on purpose in 0.4.0 (design section 9): DELETE FLOW is
    available now that the engine checks for uses before deleting."""
    stmt = parse('DELETE FLOW "Steel"')[0]
    assert stmt.entity_type == "FLOW"


def test_delete_needs_a_type():
    e = error('DELETE "Widget"')
    assert "Say what to delete" in str(e)
    assert "DELETE PROCESS" in e.hint and "DELETE SYSTEM" in e.hint


def test_find_needs_a_type():
    assert "FIND needs a type" in str(error('FIND "cement"'))


def test_pedigree_scores_out_of_range():
    e = error('PROCESS "P"\n INPUT "a", 1, kg PEDIGREE (1,2,6,1,1)\nEND PROCESS')
    assert "Pedigree scores run from 1 to 5" in str(e)


def test_compartment_must_be_known():
    e = error('PROCESS "P"\n OUTPUT "a", 1, kg TO SPACE\nEND PROCESS')
    assert "Expected AIR, WATER or SOIL after TO" in str(e)


def test_linking_must_be_known():
    e = error('SYSTEM "P"\n LINKING SOMETHING\nEND SYSTEM')
    assert "LINKING must be PREFER_DEFAULTS or ONLY_DEFAULTS" in str(e)


def test_update_needs_something_to_change():
    e = error('EDIT PROCESS "P"\n UPDATE INPUT "a"\nEND EDIT')
    assert "UPDATE needs an amount" in str(e)


def test_remove_flow_property_is_refused():
    e = error('EDIT FLOW "F"\n REMOVE PROPERTY "Mass"\nEND EDIT')
    assert "Removing a flow property isn't available" in str(e)


def test_update_must_be_update_parameter():
    assert "Expected UPDATE PARAMETER" in str(error("UPDATE x = 1"))


def test_make_needs_a_type():
    assert "Expected PROCESS, FLOW, BRIDGE, or SYSTEM after MAKE" in str(
        error('MAKE "x"'))


def test_show_needs_a_type():
    assert "Expected PROCESS, FLOW, SYSTEM or PARAMETER after SHOW" in str(
        error('SHOW "x"'))


def test_single_line_if_takes_one_statement_per_branch():
    e = error('IF 1 = 1 THEN PRINT 1 PRINT 2')
    assert "Unexpected" in str(e) or "Only one statement" in str(e)


def test_vary_needs_a_name():
    e = error('SENSITIVITY ON "W" USING "M" BY 5\n VARY 5\nEND SENSITIVITY')
    assert "Expected a parameter name after VARY" in str(e)


def test_sensitivity_requires_by_and_something_to_vary():
    """Required by the grammar from 0.4.0 (design section 4, principle
    2): there is no safe default for the range."""
    e = error('SENSITIVITY ON "W" USING "M"\n VARY a\nEND SENSITIVITY')
    assert "SENSITIVITY needs BY" in str(e) and "BY 10%" in e.hint
    e = error('SENSITIVITY ON "W" USING "M" BY 10%\nEND SENSITIVITY')
    assert "nothing to vary" in str(e) and "VARY" in e.hint


def test_parse_line_returns_none_on_error():
    assert parse_line("LET = 5") is None
    assert parse_line('PRINT "ok"') is not None
