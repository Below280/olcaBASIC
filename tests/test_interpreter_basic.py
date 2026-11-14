"""The BASIC side of the interpreter: no openLCA needed."""

import pytest

from olcabasic.interpreter import BasicError, Interpreter


@pytest.fixture
def basic(capsys):
    interp = Interpreter(None)

    def _run(code):
        capsys.readouterr()
        interp.run_program(code)
        return capsys.readouterr().out
    _run.interp = interp
    return _run


def lines(out):
    return [l.strip() for l in out.splitlines() if l.strip()]


def test_print_numbers_without_trailing_zero(basic):
    assert lines(basic("PRINT 4\nPRINT 2.5\nPRINT 0.1 + 0.2")) == ["4", "2.5", "0.3"]


def test_let_and_arithmetic(basic):
    assert lines(basic("LET a = 2\nLET b = a * 3 + 2 ^ 3\nPRINT b")) == ["14"]


def test_print_several_values(basic):
    assert lines(basic('PRINT "a", 1, 2.5')) == ["a  1  2.5"]


def test_string_concatenation(basic):
    assert lines(basic('LET p$ = "00: X"\nPRINT p$ + "/Bridges"')) == ["00: X/Bridges"]


def test_if_else(basic):
    out = basic('LET x = 5\nIF x > 3 THEN\nPRINT "big"\nELSE\nPRINT "small"\nEND IF')
    assert lines(out) == ["big"]


def test_single_line_if(basic):
    assert lines(basic('IF 1 = 2 THEN PRINT "a" ELSE PRINT "b"')) == ["b"]


def test_for_loop_with_step(basic):
    assert lines(basic("FOR i = 1 TO 7 STEP 3\nPRINT i\nNEXT i")) == ["1", "4", "7"]


def test_for_loop_float_step_does_not_drift(basic):
    out = lines(basic("FOR x = 0 TO 0.3 STEP 0.1\nPRINT x\nNEXT"))
    assert out == ["0", "0.1", "0.2", "0.3"]


def test_for_each(basic):
    assert lines(basic('FOR EACH m IN "a", "b"\nPRINT m\nNEXT')) == ["a", "b"]


def test_while(basic):
    assert lines(basic("LET n = 0\nWHILE n < 3\nLET n = n + 1\nWEND\nPRINT n")) == ["3"]


def test_sub_with_parameters(basic):
    out = basic('SUB addup(a, b)\nPRINT a + b\nEND SUB\naddup 2, 3')
    assert lines(out) == ["5"]


def test_function_returns_its_own_name(basic):
    out = basic("FUNCTION twice(x)\nLET twice = x * 2\nEND FUNCTION\nPRINT twice(4)")
    assert lines(out) == ["8"]


def test_builtin_functions(basic):
    out = basic('PRINT ABS(-2)\nPRINT INT(2.7)\nPRINT SQR(9)\nPRINT MIN(4, 2)\n'
                'PRINT LEN("abc")')
    assert lines(out) == ["2", "2", "3", "2", "3"]


def test_data_goes_on_the_queue(basic):
    basic('DATA "steel", 5, "kg"')
    assert list(basic.interp.runtime.data_queue) == ["steel", 5.0, "kg"]


def test_undefined_variable_is_an_error(basic):
    with pytest.raises(BasicError) as e:
        basic("PRINT nothing_here")
    assert "is not a defined variable" in str(e.value)
    assert 'put it in quotes: "nothing_here"' in str(e.value)


def test_division_by_zero(basic):
    with pytest.raises(BasicError) as e:
        basic("PRINT 1 / 0")
    assert "Division by zero" in str(e.value)


def test_for_step_zero(basic):
    with pytest.raises(BasicError) as e:
        basic("FOR i = 1 TO 2 STEP 0\nNEXT")
    assert "STEP cannot be 0" in str(e.value)


def test_undefined_sub(basic):
    with pytest.raises(BasicError) as e:
        basic("mystery 1")
    assert "'mystery' is not a command, and no SUB has that name" in \
        str(e.value)
    with pytest.raises(BasicError) as e:
        basic('RATING GEOGRAPHY "Good" REASON "x"')
    assert "RATING does not stand on its own here" in str(e.value)


def test_unknown_function(basic):
    with pytest.raises(BasicError) as e:
        basic("PRINT nope(1)")
    assert "Unknown function" in str(e.value)


def test_parse_error_is_printed_not_raised(basic):
    out = basic("LET = 5")
    assert out.startswith("Parse error: Line 1:")


def test_lca_command_offline_is_refused(basic):
    with pytest.raises(BasicError) as e:
        basic('FIND PROCESS "cement"')
    assert "Not connected to openLCA" in str(e.value)


def test_run_line_reports_errors_and_carries_on(capsys):
    interp = Interpreter(None)
    assert interp.run_line("PRINT missing") is True
    assert "Error:" in capsys.readouterr().out
    assert interp.run_line("EXIT") is False
    assert interp.run_line("") is True


def test_include_inserts_the_file(basic, tmp_path):
    (tmp_path / "inc.baslca").write_text('LET shared = 7\n', encoding="utf-8")
    main = tmp_path / "main.baslca"
    main.write_text('INCLUDE "inc.baslca"\nPRINT shared\n', encoding="utf-8")
    capsys_out = basic.interp
    capsys_out.run_program(main.read_text(encoding="utf-8"), str(main))
    assert capsys_out.runtime.get_var("shared") == 7.0


def test_include_loop_is_refused(tmp_path):
    f = tmp_path / "a.baslca"
    f.write_text('INCLUDE "a.baslca"\n', encoding="utf-8")
    with pytest.raises(BasicError) as e:
        Interpreter(None).run_program(f.read_text(encoding="utf-8"), str(f))
    assert "INCLUDE loop" in str(e.value)


def test_include_missing_file(tmp_path):
    with pytest.raises(BasicError) as e:
        Interpreter(None).run_program('INCLUDE "nope.baslca"', str(tmp_path / "m.baslca"))
    assert "Include file not found" in str(e.value)


def test_derived_variables_keep_their_expression(basic):
    basic("LET a = 2\nLET b = a * 3\nLET c = 5")
    rt = basic.interp.runtime
    assert "b" in rt.var_exprs and "a" not in rt.var_exprs and "c" not in rt.var_exprs


def test_navigation_without_a_connection(basic):
    out = basic('NAVIGATE FLOWS\nPWD\nUP\nBACK\nDIR\nCONFIRM DELETE ON')
    assert "Now browsing: Flows" in out
    assert "[Flows] (root)" in out
    assert basic.interp.runtime.confirm_delete is True


def test_set_folders(basic):
    out = basic('SET PROCESS FOLDER "00: X"\nSET FLOW FOLDER "00: X/Flows"\nPWD')
    assert "Process folder set: 00: X" in out
    assert "Build processes:  00: X" in out
    assert "Build flows:      00: X/Flows" in out
