"""One test or more for every statement type the parser produces."""

import pytest

from olcabasic import ast_nodes as ast
from olcabasic.parser import parse


def one(source):
    stmts = parse(source)
    assert len(stmts) == 1, stmts
    return stmts[0]


# ── core BASIC ───────────────────────────────────────────────

def test_comments_produce_no_statements():
    assert parse("REM a comment\n' another") == []
    stmts = parse("PRINT 1 ' trailing note\nREM between\nPRINT 2")
    assert [type(s) for s in stmts] == [ast.PrintExprStmt, ast.PrintExprStmt]


def test_let_explicit_and_implicit():
    a = one("LET x = 2 + 3")
    b = one("x = 2 + 3")
    assert isinstance(a, ast.LetStmt) and a.name == "x"
    assert isinstance(a.expr, ast.BinOp) and a.expr.op == "+"
    assert isinstance(b, ast.LetStmt) and b.name == "x"


def test_set_name_is_a_let():
    s = one("SET x = 4")
    assert isinstance(s, ast.LetStmt) and s.name == "x"


def test_print_expression():
    s = one('PRINT "hello"')
    assert isinstance(s, ast.PrintExprStmt)
    assert s.expr.value == "hello"


def test_print_several_expressions():
    s = one('PRINT "a", 1, x')
    assert isinstance(s, ast.PrintStmt) and s.sub_command == "EXPR"
    assert len(s.args) == 3


def test_print_results():
    assert isinstance(one("PRINT RESULTS"), ast.PrintResultsStmt)


@pytest.mark.parametrize("source,sub,nargs", [
    ("PRINT DATABASE", "DATABASE", 0),
    ('PRINT PROCESSES("cement")', "PROCESSES", 1),
    ('PRINT PROCESSES("cement", "C:", "GB")', "PROCESSES", 3),
    ('PRINT METHODS("EF")', "METHODS", 1),
    ("PRINT SYSTEMS", "SYSTEMS", 0),
    ('PRINT PARAMS("sys")', "PARAMS", 1),
    ('PRINT GLOBAL PARAMS("x")', "GLOBAL_PARAMS", 1),
    ('PRINT DETAILS("proc")', "DETAILS", 1),
    ('PRINT QUALITY("proc")', "QUALITY", 1),
    ('PRINT LINKS("sys", "steel")', "LINKS", 2),
    ('PRINT UNITS("kWh")', "UNITS", 1),
    ("PRINT DQ SYSTEMS", "DQ_SYSTEMS", 0),
])
def test_print_sub_commands(source, sub, nargs):
    s = one(source)
    assert isinstance(s, ast.PrintStmt)
    assert s.sub_command == sub and len(s.args) == nargs


@pytest.mark.parametrize("source,sub,nargs", [
    ("DATABASE", "DATABASE", 0),
    ("DATABASE INFO", "DATABASE", 0),
    ('DATABASE FAMILY "ecoinvent"', "FAMILY", 1),
])
def test_database_commands(source, sub, nargs):
    s = one(source)
    assert isinstance(s, ast.PrintStmt)
    assert s.sub_command == sub and len(s.args) == nargs


def test_input_prompt():
    s = one('INPUT "How many?", n')
    assert isinstance(s, ast.InputStmt)
    assert s.prompt == "How many?" and s.variable == "n"


def test_data():
    s = one('DATA "steel", 5, kg')
    assert isinstance(s, ast.DataStmt) and len(s.values) == 3


def test_if_block_with_else():
    s = one('IF x > 1 THEN\nPRINT "a"\nELSE\nPRINT "b"\nEND IF')
    assert isinstance(s, ast.IfStmt)
    assert isinstance(s.condition, ast.Comparison)
    assert len(s.then_body) == 1 and len(s.else_body) == 1


def test_if_single_line():
    s = one('IF x = 1 THEN PRINT "a" ELSE PRINT "b"')
    assert isinstance(s, ast.IfStmt)
    assert isinstance(s.then_body[0], ast.PrintExprStmt)
    assert isinstance(s.else_body[0], ast.PrintExprStmt)


def test_for_with_step():
    s = one("FOR i = 1 TO 10 STEP 2\nPRINT i\nNEXT i")
    assert isinstance(s, ast.ForStmt)
    assert s.variable == "i" and s.step.value == 2.0 and len(s.body) == 1


def test_for_each():
    s = one('FOR EACH m IN "a", "b"\nPRINT m\nNEXT')
    assert isinstance(s, ast.ForEachStmt)
    assert s.variable == "m" and len(s.values) == 2


def test_while():
    s = one("WHILE x < 3\nLET x = x + 1\nWEND")
    assert isinstance(s, ast.WhileStmt) and len(s.body) == 1


def test_sub_definition_and_call():
    stmts = parse('SUB greet(who)\nPRINT who\nEND SUB\ngreet "Tom"')
    assert isinstance(stmts[0], ast.SubDef) and stmts[0].params == ["who"]
    assert isinstance(stmts[1], ast.SubCall) and stmts[1].name == "greet"


def test_function_definition():
    s = one("FUNCTION twice(x)\nLET twice = x * 2\nEND FUNCTION")
    assert isinstance(s, ast.FunctionDef) and s.params == ["x"]


def test_expression_precedence():
    s = one("LET x = 1 + 2 * 3 ^ 2")
    assert s.expr.op == "+" and s.expr.right.op == "*"
    assert s.expr.right.right.op == "^"


def test_logical_and_comparison_expressions():
    s = one("LET ok = a > 1 AND NOT b = 2 OR c <> 3")
    assert isinstance(s.expr, ast.LogicalOp) and s.expr.op == "OR"


def test_function_call_expression():
    s = one("LET x = MIN(1, 2)")
    assert isinstance(s.expr, ast.FuncCall) and len(s.expr.args) == 2


def test_string_concatenation():
    s = one('LET p$ = "a" + "/b"')
    assert isinstance(s.expr, ast.StringConcat)


# ── flows, bridges, processes ────────────────────────────────

def test_flow_find_form():
    s = one('FLOW "Steel", kg, PRODUCT')
    assert isinstance(s, ast.FlowStmt)
    assert s.unit == "kg" and s.flow_type == "PRODUCT" and not s.is_new


def test_make_flow_and_legacy_flow_new():
    a = one('MAKE FLOW "Steel", kg, WASTE FOLDER "00: X"')
    b = one('FLOW NEW "Steel", kg')
    assert a.is_new and a.flow_type == "WASTE" and a.folder.value == "00: X"
    assert b.is_new


@pytest.mark.parametrize("tail,direction", [
    ("TO AIR", "AIR"), ("TO WATER", "WATER"), ("TO SOIL", "SOIL"),
    ("FROM NATURE", "NATURE"),
])
def test_flow_compartments(tail, direction):
    s = one(f'FLOW "CO2", kg {tail}')
    assert s.flow_type == "ELEMENTARY" and s.direction == direction


def test_bridge_single_line():
    s = one('BRIDGE "BRIDGE | Steel | kg", kg')
    assert isinstance(s, ast.BridgeStmt) and s.unit == "kg" and not s.is_waste


def test_bridge_block():
    s = one('BRIDGE "B", kg\n  FOLDER "00: X/Bridges"\n  PROVIDER "abc"\n'
            '  WASTE\nEND BRIDGE')
    assert s.folder.value == "00: X/Bridges"
    assert s.provider.value == "abc" and s.is_waste


def test_make_bridge():
    assert isinstance(one('MAKE BRIDGE "B", t*km'), ast.BridgeStmt)


PROCESS = '''MAKE PROCESS "Widget" LOCATION "GB"
  FOLDER "00: X"
  DESCRIPTION "A widget"
  FLOW SCHEMA "Pedigree"
  PROCESS SCHEMA "Quality"
  LET mass = 2
  OUTPUT MAKE FLOW "Widget", 1, kg, PRODUCT
  INPUT USE PROCESS "steel", mass * 2, kg LOCATION "GLO" PEDIGREE (1,2,3,4,5) COMMENT "note"
  INPUT USE FLOW "water", 3, kg
  INPUT USE "plastic", 1, kg PROVIDER "uuid-1"
  INPUT "legacy", 1, kg
  INPUT NEW "old style", 1, kg
  OUTPUT "CO2", 5, kg TO AIR
  INPUT "ore", 1, kg FROM NATURE
  OUTPUT "scrap", 1, kg WASTE
  INPUT "x", 1, kg FORMULA "a*b"
END PROCESS'''


def test_process_block_header_fields():
    s = one(PROCESS)
    assert isinstance(s, ast.ProcessStmt)
    assert s.name.value == "Widget" and s.location.value == "GB"
    assert s.folder.value == "00: X" and s.description.value == "A widget"
    assert s.flow_schema.value == "Pedigree"
    assert s.process_schema.value == "Quality"
    assert [p.name for p in s.local_params] == ["mass"]
    assert len(s.exchanges) == 10


def test_process_exchange_forms():
    ex = one(PROCESS).exchanges
    assert ex[0].direction == "OUTPUT" and ex[0].is_new and ex[0].is_product
    assert ex[1].use_type == "PROCESS" and ex[1].location.value == "GLO"
    assert ex[1].pedigree == [1, 2, 3, 4, 5] and ex[1].comment.value == "note"
    assert ex[2].use_type == "FLOW"
    assert ex[3].use_type == "PROCESS" and ex[3].provider.value == "uuid-1"
    assert ex[4].use_type == "" and not ex[4].is_new
    assert ex[5].is_new and ex[5].legacy_new
    assert ex[6].direction_compartment == "AIR"
    assert ex[7].direction_compartment == "NATURE"
    assert ex[8].is_waste
    assert ex[9].formula.value == "a*b"


def test_plain_process_keyword_still_works():
    s = one('PROCESS "P"\n OUTPUT NEW "P", 1, kg, PRODUCT\nEND PROCESS')
    assert isinstance(s, ast.ProcessStmt)


def test_process_read_inputs_from_data():
    s = one('PROCESS "P"\n READ INPUTS FROM DATA\nEND PROCESS')
    assert s.read_data


def test_pedigree_as_string():
    s = one('PROCESS "P"\n INPUT "a", 1, kg PEDIGREE "(1;2;1;1;3)"\nEND PROCESS')
    assert s.exchanges[0].pedigree == "(1;2;1;1;3)"


@pytest.mark.parametrize("unit", ["kg", "t*km", "kWh", "m3", "Item(s)", "MJ"])
def test_units(unit):
    s = one(f'PROCESS "P"\n INPUT "a", 1, {unit}\nEND PROCESS')
    assert s.exchanges[0].unit == unit


EDIT = '''EDIT PROCESS "Widget"
  ADD INPUT USE PROCESS "steel", 2, kg
  ADD PARAM p = 3
  REMOVE INPUT "water"
  REMOVE EXCHANGE "any"
  UPDATE INPUT "plastic", 4, kg LOCATION "RER"
  UPDATE OUTPUT "CO2" PEDIGREE (1,1,1,1,1) COMMENT "measured"
  UPDATE INPUT "ore" PROVIDER "uuid-2"
  UPDATE EXCHANGE "x" AMOUNT 9
  UPDATE PARAM p = 5
  SET DESCRIPTION "new"
  SET FOLDER "00: Y"
  SET LOCATION "DE"
END EDIT'''


def test_edit_process_block():
    s = one(EDIT)
    assert isinstance(s, ast.EditProcessStmt)
    assert len(s.add_exchanges) == 1 and len(s.add_params) == 1
    assert [r["direction"] for r in s.remove_exchanges] == ["INPUT", ""]
    assert len(s.update_exchanges) == 4
    assert s.update_exchanges[0]["unit"] == "kg"
    assert s.update_exchanges[0]["location"].value == "RER"
    assert s.update_exchanges[1]["pedigree"] == [1, 1, 1, 1, 1]
    assert s.update_exchanges[2]["provider"].value == "uuid-2"
    assert s.update_exchanges[3]["amount"].value == 9.0
    assert "p" in s.update_params
    assert s.set_description.value == "new"
    assert s.set_category.value == "00: Y" and s.set_location.value == "DE"


def test_edit_block_records_each_line():
    s = one(EDIT)
    assert s.line == 1
    assert s.remove_exchanges[0]["line"] == 4
    assert s.update_exchanges[0]["line"] == 6


def test_edit_flow_block():
    s = one('EDIT FLOW "Concrete"\n  ADD PROPERTY "Mass" AS 2400 kg PER m3\n'
            '  UPDATE PROPERTY "Mass" AS 1 m3 PER 2400 kg\n'
            '  SET REFERENCE "Volume"\nEND EDIT')
    assert isinstance(s, ast.EditFlowStmt)
    assert [op["op"] for op in s.operations] == ["add", "update", "reference"]
    assert s.operations[0]["unit"] == "kg" and s.operations[0]["per_unit"] == "m3"
    assert isinstance(s.operations[1]["amount"], ast.BinOp)


def test_update_parameter():
    s = one("UPDATE PARAMETER mass = 4")
    assert isinstance(s, ast.UpdateParamStmt) and s.name == "mass"


def test_system_single_line_and_block():
    a = one('SYSTEM "Widget"')
    b = one('SYSTEM "Widget"\n  LINKING ONLY_DEFAULTS\n  TARGET 2, kg PROPERTY "Mass"\n'
            '  FOLDER "00: X"\nEND SYSTEM')
    assert isinstance(a, ast.SystemStmt) and a.linking == "PREFER_DEFAULTS"
    assert b.linking == "ONLY_DEFAULTS" and b.target_unit == "kg"
    assert b.target_property.value == "Mass" and b.folder.value == "00: X"


def test_make_system():
    assert isinstance(one('MAKE SYSTEM "Widget"'), ast.SystemStmt)


# ── calculations ─────────────────────────────────────────────

def test_calculate():
    s = one('CALCULATE "Widget" USING "EF v3.1" ALLOCATE ECONOMIC')
    assert isinstance(s, ast.CalculateStmt)
    assert s.method.value == "EF v3.1" and s.allocation == "ECONOMIC"


def test_contribution_with_categories():
    s = one('CONTRIBUTION "W" USING "EF v3.1" TOP 5\n'
            '  CATEGORIES "Climate change", "Acidification"\nEND CONTRIBUTION')
    assert isinstance(s, ast.ContributionStmt)
    assert s.top == 5 and len(s.categories) == 2


def test_contribution_default_top():
    assert one('CONTRIBUTION "W" USING "M"').top == 10


def test_inventory():
    s = one('INVENTORY "W" USING "M" MAX 20')
    assert isinstance(s, ast.InventoryStmt) and s.max_flows == 20


def test_montecarlo():
    s = one('MONTECARLO "W" USING "M" RUNS 200')
    assert isinstance(s, ast.MonteCarloStmt) and s.runs == 200


def test_tree():
    s = one('TREE "W" USING "M" CATEGORY "Climate change" LEVELS 2 TOP 3 NOQUALITY')
    assert isinstance(s, ast.TreeStmt)
    assert s.levels == 2 and s.top == 3 and not s.with_quality


def test_scenario_block():
    s = one('SCENARIO "High"\n  LET mass = 5\n  SET other = 2\nEND SCENARIO')
    assert isinstance(s, ast.ScenarioStmt)
    assert s.name == "High" and [l.name for l in s.overrides] == ["mass", "other"]
    assert [l.line for l in s.overrides] == [2, 3]


def test_run_scenarios():
    s = one('RUN SCENARIOS ON "W" USING "M"')
    assert isinstance(s, ast.RunScenariosStmt) and s.from_csv is None


def test_run_scenarios_from_csv_block():
    s = one('RUN SCENARIOS ON "W" USING "M"\n  FROM CSV "in.csv"\n'
            '  SAVE "out.csv"\nEND RUN')
    assert s.from_csv.value == "in.csv" and s.save_to.value == "out.csv"


def test_run_file():
    s = one('RUN "model.baslca"')
    assert isinstance(s, ast.RunFileStmt)


def test_sensitivity_block():
    s = one('SENSITIVITY ON "W" USING "M" BY 15%\n  VARY a, b\n  VARY "c"\n'
            'END SENSITIVITY')
    assert isinstance(s, ast.SensitivityStmt)
    assert s.variation_pct == 15.0 and s.parameters == ["a", "b", "c"]


def test_sensitivity_from_csv():
    s = one('SENSITIVITY ON "W" USING "M" BY 10\n  FROM "p.csv"\n'
            '  SAVE "o.csv"\nEND SENSITIVITY')
    assert s.from_csv.value == "p.csv" and s.save_to.value == "o.csv"


# ── audit ────────────────────────────────────────────────────

def test_validate():
    a = one('VALIDATE "W"')
    b = one('VALIDATE "W" WITH CALCULATION')
    assert isinstance(a, ast.ValidateStmt) and not a.with_calc and b.with_calc


def test_check():
    s = one('CHECK "W" TIER 2 AGAINST "lci.csv"')
    assert isinstance(s, ast.CheckStmt) and s.tier == 2
    assert s.against.value == "lci.csv"
    assert one('CHECK "W"').tier == 1


def test_extract_and_audit():
    assert isinstance(one('EXTRACT FOLDER "00: X"'), ast.ExtractStmt)
    assert isinstance(one('AUDIT "00: X"'), ast.AuditStmt)


# ── output, delete, find, show ───────────────────────────────

def test_save_results_and_export():
    assert isinstance(one('SAVE RESULTS "r.csv"'), ast.SaveResultsStmt)
    assert isinstance(one('EXPORT RESULTS TO "r.csv"'), ast.ExportResultsStmt)


@pytest.mark.parametrize("kind", ["PROCESS", "SYSTEM"])
def test_delete(kind):
    s = one(f'DELETE {kind} "Widget"')
    assert isinstance(s, ast.DeleteStmt) and s.entity_type == kind


@pytest.mark.parametrize("source,enabled", [
    ("CONFIRM DELETE ON", True), ("CONFIRM DELETE OFF", False),
    ("CONFIRM DELETE", True),
])
def test_confirm_delete(source, enabled):
    s = one(source)
    assert isinstance(s, ast.ConfirmDeleteStmt) and s.enabled is enabled


@pytest.mark.parametrize("kind", ["PROCESS", "FLOW", "METHOD", "CHEMICAL", "UNIT"])
def test_find(kind):
    s = one(f'FIND {kind} "term"')
    assert isinstance(s, ast.FindStmt) and s.entity_type == kind


def test_find_process_at_and_in():
    s = one('FIND PROCESS "cement" AT "GB" IN "C:Manufacturing"')
    assert s.location.value == "GB" and s.category.value == "C:Manufacturing"


@pytest.mark.parametrize("source,etype,sub", [
    ('SHOW PROCESS "W"', "PROCESS", ""),
    ('SHOW PROCESS "W" INPUTS', "PROCESS", "INPUTS"),
    ('SHOW PROCESS "W" OUTPUTS', "PROCESS", "OUTPUTS"),
    ('SHOW PROCESS "W" LOCATION', "PROCESS", "LOCATION"),
    ('SHOW PROCESS "W" DESCRIPTION', "PROCESS", "DESCRIPTION"),
    ('SHOW PROCESS "W" PARAMS', "PROCESS", "PARAMS"),
    ('SHOW FLOW "F"', "FLOW", ""),
    ('SHOW FLOW "F" UNITS', "FLOW", "UNITS"),
    ('SHOW PARAMETER "p"', "PARAMETER", ""),
    ('SHOW PARAMETER "p" VALUE', "PARAMETER", "VALUE"),
])
def test_show(source, etype, sub):
    s = one(source)
    assert isinstance(s, ast.ShowStmt)
    assert s.entity_type == etype and s.sub_command == sub


def test_link():
    s = one('LINK PROCESS "A" TO PROCESS "B" WITH 2, kg')
    assert isinstance(s, ast.LinkStmt)
    assert s.source.value == "A" and s.target.value == "B" and s.unit == "kg"


@pytest.mark.parametrize("kind", ["PROCESS", "FLOW", "SYSTEM"])
def test_move(kind):
    s = one(f'MOVE {kind} "W" TO "00: Y"')
    assert isinstance(s, ast.MoveStmt) and s.entity_type == kind
    assert s.destination.value == "00: Y"


def test_move_to_current_folder():
    assert one('MOVE PROCESS "W" TO FOLDER').destination is None


# ── navigation: Acorn and Linux dialects ─────────────────────

@pytest.mark.parametrize("word", ["CAT", "LS"])
def test_cat_and_ls_are_the_same_statement(word):
    s = one(word)
    assert isinstance(s, ast.CatStmt) and s.path is None


@pytest.mark.parametrize("word", ["CAT", "LS"])
def test_cat_forms(word):
    assert one(f'{word} "00: X"').path.value == "00: X"
    assert one(f"{word} FLOWS").entity_type == "FLOWS"
    assert one(f"{word} *concrete*").filter_pattern == "*concrete*"
    assert one(f'{word} "*concrete*"').filter_pattern == "*concrete*"


@pytest.mark.parametrize("word", ["DIR", "CD"])
def test_dir_and_cd_are_the_same_statement(word):
    s = one(f'{word} "00: X"')
    assert isinstance(s, ast.DirStmt) and s.path.value == "00: X"
    assert one(word).path is None


def test_cd_dotdot_is_up():
    assert isinstance(one("CD .."), ast.UpStmt)
    assert isinstance(one("UP"), ast.UpStmt)


def test_back_pwd_cdir():
    assert isinstance(one("BACK"), ast.BackStmt)
    assert isinstance(one("PWD"), ast.PwdStmt)
    s = one('CDIR "New folder"')
    assert isinstance(s, ast.CdirStmt) and s.name.value == "New folder"


@pytest.mark.parametrize("source,target", [
    ("NAVIGATE", ""), ("NAVIGATE FLOWS", "FLOWS"),
    ("NAVIGATE PROCESS", "PROCESSES"), ("NAVIGATE FLOW", "FLOWS"),
    ("NAVIGATE METHODS", "METHODS"), ("NAVIGATE SYSTEMS", "SYSTEMS"),
])
def test_navigate(source, target):
    s = one(source)
    assert isinstance(s, ast.NavigateStmt) and s.target == target


@pytest.mark.parametrize("source,target", [
    ('SET PROCESS FOLDER "00: X"', "PROCESS"),
    ('SET FLOW FOLDER "00: X"', "FLOW"),
    ('SET FOLDER "00: X"', "PROCESS"),
])
def test_set_folder(source, target):
    s = one(source)
    assert isinstance(s, ast.SetFolderStmt) and s.target == target


# ── REPL commands ────────────────────────────────────────────

def test_help_with_and_without_topic():
    assert one("HELP").topic == ""
    assert one("HELP PROCESS").topic == "PROCESS"


def test_clear_refresh_exit_quit():
    assert isinstance(one("CLEAR"), ast.ClearStmt)
    assert isinstance(one("REFRESH"), ast.RefreshStmt)
    assert isinstance(one("EXIT"), ast.ExitStmt)
    assert isinstance(one("QUIT"), ast.ExitStmt)


def test_include_statement():
    assert isinstance(one('INCLUDE "common.baslca"'), ast.IncludeStmt)


def test_statement_line_numbers():
    stmts = parse('PRINT 1\n\nPRINT 2\nPROCESS "P"\n INPUT "a", 1, kg\nEND PROCESS')
    assert [s.line for s in stmts] == [1, 3, 4]
