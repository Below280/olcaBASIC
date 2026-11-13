"""
Dry run: check a parsed program without touching openLCA.

It cannot know what is in the database, so it checks what the program
itself gets wrong: variables that are never defined, SUBs and FUNCTIONs
that do not exist, files that are missing, scenarios on calculated
variables, commands that would stop and wait for the keyboard, and the
structure of PROCESS blocks.
"""

import dataclasses
import os
from typing import Dict, List

from . import ast_nodes as ast
from .errors import BasicError, error_dict

BUILTINS = {"ABS", "INT", "SQR", "LOG", "EXP", "SIN", "COS", "TAN", "MIN",
            "MAX", "ROUND", "LEN", "VAL", "STR$", "TRIM$", "UCASE$", "LCASE$"}

ALLOCATIONS = {"AS_DEFINED", "PHYSICAL", "ECONOMIC", "CAUSAL", "NONE"}

WRITES = (ast.FlowStmt, ast.BridgeStmt, ast.ProcessStmt, ast.SystemStmt,
          ast.EditProcessStmt, ast.EditFlowStmt, ast.UpdateParamStmt,
          ast.DeleteStmt, ast.LinkStmt, ast.MoveStmt, ast.EntityDeleteStmt,
          ast.EntityMoveStmt, ast.MakeEntityStmt, ast.MethodStmt,
          ast.ProjectStmt, ast.SaveResultAsStmt)
CALCULATIONS = (ast.CalculateStmt, ast.ContributionStmt, ast.InventoryStmt,
                ast.MonteCarloStmt, ast.RunScenariosStmt, ast.SensitivityStmt,
                ast.TreeStmt, ast.CalculateProjectStmt)
NO_CONNECTION_NEEDED = (
    ast.CommentStmt, ast.LetStmt, ast.PrintExprStmt, ast.PrintResultsStmt,
    ast.DataStmt, ast.InputStmt, ast.IfStmt, ast.ForStmt, ast.ForEachStmt,
    ast.WhileStmt, ast.SubDef, ast.SubCall, ast.FunctionDef, ast.RunFileStmt,
    ast.IncludeStmt, ast.ScenarioStmt, ast.SaveResultsStmt,
    ast.ExportResultsStmt, ast.SetFolderStmt, ast.NavigateStmt, ast.PwdStmt,
    ast.UpStmt, ast.BackStmt, ast.CdirStmt, ast.MkdirStmt, ast.HelpStmt,
    ast.ClearStmt, ast.ConfirmDeleteStmt, ast.ExitStmt, ast.SaveProgramStmt,
    ast.NewFromTemplateStmt)


def command_word(stmt) -> str:
    from .interpreter import _command_word
    return _command_word(stmt)


class Report:
    def __init__(self):
        self.errors: List[Dict] = []
        self.warnings: List[Dict] = []
        self.statements = 0
        self.commands: Dict[str, int] = {}
        self.writes: List[str] = []
        self.calculations: List[str] = []

    def error(self, line, message, hint=""):
        entry = error_dict(message, line, hint)
        if entry not in self.errors:
            self.errors.append(entry)

    def warn(self, line, message):
        self.warnings.append({"line": line, "message": message,
                              "level": "warning"})

    def summary(self) -> Dict:
        return {"statements": self.statements, "commands": self.commands,
                "would_write": self.writes,
                "would_calculate": self.calculations,
                "errors": len(self.errors), "warnings": len(self.warnings)}

    def text_lines(self) -> List[str]:
        out = [f"  Dry run: {self.statements} statements checked. "
               f"Nothing was sent to openLCA."]
        if self.writes:
            out.append("  Would write: " + ", ".join(self.writes))
        if self.calculations:
            out.append("  Would calculate: " + ", ".join(self.calculations))
        for e in self.errors:
            hint = f" {e['hint']}" if e["hint"] else ""
            out.append(f"  Error: Line {e['line']}: {e['message']}{hint}")
        for w in self.warnings:
            out.append(f"  WARNING: Line {w['line']}: {w['message']}")
        if not self.errors:
            out.append("  No problems found. Names in the database are "
                       "checked when the program runs.")
        return out


def _literal(expr):
    return expr.value if isinstance(expr, ast.StringLiteral) else None


def _walk_exprs(node):
    """Every expression node inside an AST node, with nested statements
    left out (they are visited as statements in their own right)."""
    if isinstance(node, ast.Expr):
        yield node
        for f in dataclasses.fields(node):
            yield from _walk_exprs(getattr(node, f.name))
    elif isinstance(node, ast.Statement):
        return
    elif dataclasses.is_dataclass(node):
        for f in dataclasses.fields(node):
            yield from _walk_exprs(getattr(node, f.name))
    elif isinstance(node, dict):
        for v in node.values():
            yield from _walk_exprs(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from _walk_exprs(v)


def _statement_exprs(stmt):
    for f in dataclasses.fields(stmt):
        value = getattr(stmt, f.name)
        if f.name in ("then_body", "else_body", "body"):
            continue
        if isinstance(value, ast.Statement):
            yield from _statement_exprs(value)
        elif isinstance(value, list) and value and all(
                isinstance(v, ast.Statement) for v in value):
            for v in value:
                yield from _statement_exprs(v)
        else:
            yield from _walk_exprs(value)


def _all_statements(statements):
    """Every statement, including those inside IF, FOR, WHILE, SUB and
    FUNCTION bodies."""
    for stmt in statements:
        if stmt is None:
            continue
        yield stmt
        for name in ("then_body", "else_body", "body"):
            yield from _all_statements(getattr(stmt, name, None) or [])


def _uses_variables(expr, known) -> bool:
    return any(isinstance(e, ast.Identifier) and e.name in known
               for e in _walk_exprs(expr))


def _check_epd(stmt, report):
    """The checks on an EPD block that need no database. Returns the
    definition, or None if the block is wrong or cannot be read
    without running the program."""
    from .workflows import epd

    class _NotLiteral(Exception):
        pass

    def text(expr):
        if isinstance(expr, ast.StringLiteral):
            return expr.value
        raise _NotLiteral()

    def number(expr):
        if isinstance(expr, ast.NumberLiteral):
            return expr.value
        raise _NotLiteral()

    try:
        fields = epd.field_values(stmt, text, number)
        return epd.check_definition(text(stmt.name), fields, stmt.lines,
                                    stmt.line)
    except _NotLiteral:
        return None       # built from variables: checked when it runs
    except BasicError as e:
        report.error(e.line or stmt.line, e.message, e.hint)
        return None


def check(statements, runtime, connected: bool = True,
          interactive: bool = False) -> Report:
    report = Report()
    everything = list(_all_statements(statements))
    report.statements = len(everything)

    # ── what the program (and the session so far) defines ────
    known = set(runtime.get_global_vars())
    derived = set(runtime.var_exprs)
    subs = set(runtime.subs)
    functions = set(runtime.functions)
    for stmt in everything:
        if isinstance(stmt, (ast.LetStmt, ast.UpdateParamStmt)):
            known.add(stmt.name)
        elif isinstance(stmt, (ast.ForStmt, ast.ForEachStmt)):
            known.add(stmt.variable)
        elif isinstance(stmt, ast.InputStmt):
            known.add(stmt.variable)
        elif isinstance(stmt, ast.FindStmt) and stmt.assign_to:
            known.add(stmt.assign_to)
        elif isinstance(stmt, ast.SubDef):
            subs.add(stmt.name)
            known.update(stmt.params)
        elif isinstance(stmt, ast.FunctionDef):
            functions.add(stmt.name)
            known.update(stmt.params)
            known.add(stmt.name)
        elif isinstance(stmt, (ast.ProcessStmt,)):
            known.update(l.name for l in stmt.local_params)
        elif isinstance(stmt, ast.EditProcessStmt):
            known.update(l.name for l in stmt.add_params)
        elif isinstance(stmt, ast.ScenarioStmt):
            pass
    # top-level variables defined from other variables are calculated
    for stmt in statements:
        if isinstance(stmt, (ast.LetStmt, ast.UpdateParamStmt)):
            if _uses_variables(stmt.expr, known):
                derived.add(stmt.name)
            else:
                derived.discard(stmt.name)

    confirm = bool(runtime.confirm_delete)
    open_results = set(getattr(runtime, "open_results", {}) or {})
    scenarios_defined = bool(runtime.scenarios)
    active = getattr(runtime, "epd", None)
    epd_defined = active is not None
    epd_modules = list(active.d["modules"]) if active is not None else None

    for stmt in everything:
        word = command_word(stmt)
        report.commands[word] = report.commands.get(word, 0) + 1
        line = stmt.line

        # undefined variables and functions
        for expr in _statement_exprs(stmt):
            if isinstance(expr, ast.Identifier) and expr.name not in known:
                report.error(
                    line, f"'{expr.name}' is not a defined variable.",
                    f"If you meant a name, put it in quotes: \"{expr.name}\"")
            elif isinstance(expr, ast.FuncCall):
                if (expr.name.upper() not in BUILTINS
                        and expr.name not in functions):
                    report.error(line, f"Unknown function: {expr.name}.",
                                 "Define it with FUNCTION ... END FUNCTION "
                                 "before it is used.")

        allocation = getattr(stmt, "allocation", "")
        if allocation and allocation not in ALLOCATIONS:
            report.error(line, f"Unknown allocation method '{allocation}'.",
                         "Use one of: " + ", ".join(sorted(ALLOCATIONS)))

        if isinstance(stmt, ast.SubCall) and stmt.name not in subs:
            report.error(line, f"SUB '{stmt.name}' is not defined.",
                         "Define it with SUB ... END SUB, or check the "
                         "spelling of the command.")

        elif isinstance(stmt, ast.ConfirmDeleteStmt):
            confirm = stmt.enabled

        elif isinstance(stmt, ast.DeleteStmt):
            ref = _literal(stmt.ref) or "?"
            report.writes.append(f"DELETE {stmt.entity_type} \"{ref}\"")
            if not confirm and not interactive:
                report.error(
                    line, "DELETE would stop and ask for confirmation, and "
                          "nobody is there to answer.",
                    "Put CONFIRM DELETE ON before the DELETE line.")

        elif isinstance(stmt, ast.EntityDeleteStmt):
            ref = _literal(stmt.ref) or "?"
            report.writes.append(f"DELETE {stmt.entity_type} \"{ref}\"")
            if not confirm and not interactive:
                report.error(
                    line, "DELETE would stop and ask for confirmation, and "
                          "nobody is there to answer.",
                    "Put CONFIRM DELETE ON before the DELETE line.")

        elif isinstance(stmt, ast.ShutdownStmt):
            if not interactive:
                report.error(
                    line, "SHUTDOWN SERVER needs a person at the olcaBASIC "
                          "terminal.",
                    "It cannot be done through a Session or the MCP.")

        elif isinstance(stmt, ast.SaveResultAsStmt):
            report.writes.append(
                f"SAVE RESULT AS \"{_literal(stmt.name) or '?'}\"")
            if stmt.result_name not in open_results:
                report.error(
                    line, "No result is open."
                    if not stmt.result_name else
                    f"No open result is called '{stmt.result_name}'.",
                    "CALCULATE \"system\" USING \"method\" first; SAVE "
                    "RESULT AS stores the open result.")

        elif isinstance(stmt, ast.InputStmt) and not interactive:
            report.error(line, "INPUT waits for the keyboard, and nobody is "
                               "there to answer.",
                         f"Set the value in the program: LET {stmt.variable} = ...")

        elif (isinstance(stmt, ast.NavigateStmt) and not stmt.target
              and not interactive):
            report.error(line, "NAVIGATE on its own shows a menu and waits "
                               "for the keyboard.",
                         "Say which: NAVIGATE PROCESSES, NAVIGATE FLOWS, "
                         "NAVIGATE METHODS or NAVIGATE SYSTEMS.")

        elif isinstance(stmt, (ast.RunFileStmt, ast.IncludeStmt)):
            name = _literal(stmt.filename)
            if name and not os.path.exists(name):
                report.error(line, f"File not found: {name}.",
                             "Check the path (it is relative to the folder "
                             "the program runs in).")

        elif isinstance(stmt, ast.ScenarioStmt):
            scenarios_defined = True
            for let in stmt.overrides:
                if let.name in derived:
                    report.error(
                        let.line or line,
                        f"'{let.name}' is calculated from other variables, "
                        f"so it can't be set in a SCENARIO.",
                        "Change the variables it is calculated from instead.")

        elif isinstance(stmt, ast.RunScenariosStmt):
            report.calculations.append("RUN SCENARIOS")
            csv = _literal(stmt.from_csv) if stmt.from_csv else None
            if stmt.from_csv is None and not scenarios_defined:
                report.error(line, "No scenarios defined.",
                             "Put SCENARIO ... END SCENARIO blocks before "
                             "RUN SCENARIOS, or use FROM CSV \"file\".")
            elif csv and not os.path.exists(csv):
                report.error(line, f"File not found: {csv}.")

        elif isinstance(stmt, ast.SensitivityStmt):
            report.calculations.append("SENSITIVITY")
            lines = stmt.parameter_lines or []
            for i, name in enumerate(stmt.parameters):
                if name in derived:
                    report.error(
                        lines[i] if i < len(lines) else line,
                        f"'{name}' is calculated from other variables, so "
                        f"it can't be varied in a SENSITIVITY.",
                        "Vary the variables it is calculated from instead.")
            csv = _literal(stmt.from_csv) if stmt.from_csv else None
            if csv and not os.path.exists(csv):
                report.error(line, f"File not found: {csv}.")
            if not stmt.parameters and stmt.from_csv is None:
                report.error(line, "SENSITIVITY has nothing to vary.",
                             "Add at least one VARY line, or FROM \"file.csv\".")

        elif isinstance(stmt, ast.ProcessStmt):
            name = _literal(stmt.name) or "?"
            report.writes.append(f"MAKE PROCESS \"{name}\"")
            if not stmt.read_data or stmt.exchanges:
                products = [ex for ex in stmt.exchanges if ex.is_product]
                if not products:
                    report.error(
                        line, f"PROCESS \"{name}\" has no reference product.",
                        "Mark one OUTPUT line with PRODUCT, for example: "
                        "OUTPUT MAKE FLOW \"name\", 1, kg, PRODUCT")
                elif len(products) > 1:
                    report.error(
                        products[1].line or line,
                        f"PROCESS \"{name}\" has {len(products)} exchanges "
                        f"marked PRODUCT.",
                        "Mark only the main output with PRODUCT.")

        elif isinstance(stmt, ast.EpdStmt):
            name = _literal(stmt.name) or "?"
            report.writes.append(f"EPD \"{name}\" (folders)")
            definition = _check_epd(stmt, report)
            if definition is not None:
                epd_modules = definition["modules"]
            epd_defined = True

        elif isinstance(stmt, ast.ModuleStmt):
            code = stmt.code.upper()
            if not epd_defined:
                report.error(line, f"MODULE {code} needs an EPD, and none "
                                   f"is defined before it.",
                             "Define one first: EPD \"name\" ... END EPD.")
            elif epd_modules is not None and code not in epd_modules:
                report.error(line, f"MODULE {code} is not declared in the "
                                   f"EPD block (MODULES "
                                   f"{', '.join(epd_modules)}).",
                             "Add it to the MODULES line, or remove this "
                             "MODULE block.")
            if stmt.total is None:
                report.error(line, f"MODULE {code} has no TOTAL line.",
                             "Add TOTAL \"name\" before END MODULE.")
            else:
                total = _literal(stmt.total["name"]) or "?"
                report.writes.append(f"MAKE PROCESS \"{code}: {total}\"")
            if stmt.net_flows and code != "D":
                report.error(stmt.net_flows[0]["line"],
                             f"NET FLOW belongs in MODULE D, not MODULE "
                             f"{code}.")

        elif isinstance(stmt, ast.EpdCommandStmt):
            if not epd_defined and stmt.command not in ("STATUS", "CLOSE"):
                report.error(line, f"EPD {stmt.command} needs an EPD, and "
                                   f"none is defined before it.",
                             "Define one first: EPD \"name\" ... END EPD.")
            if stmt.command == "SYSTEMS":
                report.writes.append("EPD SYSTEMS")
            elif stmt.command in ("CALCULATE", "DATA QUALITY"):
                report.calculations.append(f"EPD {stmt.command}")
                target = _literal(stmt.from_file) if stmt.from_file else None
                if target and not os.path.exists(target):
                    report.error(line, f"File not found: {target}",
                                 "EPD DATA QUALITY FROM reads a CSV file of "
                                 "scenarios.")
            elif stmt.command in ("DQ SHEET", "DQ TABLE", "EXPORT MODEL"):
                report.writes.append(
                    f"EPD {stmt.command} "
                    f"\"{_literal(stmt.argument) or '?'}\" (file)")
                if stmt.command != "EXPORT MODEL":
                    report.calculations.append(f"EPD {stmt.command}")
            elif stmt.command == "REPORT":
                report.writes.append(
                    f"EPD REPORT \"{_literal(stmt.argument) or '?'}\" (file)")
            elif stmt.command == "SAVE":
                report.writes.append("EPD SAVE (an EPD and one stored "
                                     "result per module, in openLCA)")
                report.calculations.append("EPD SAVE")
            elif stmt.command == "CLOSE":
                epd_defined, epd_modules = False, None

        elif isinstance(stmt, ast.EpdDocumentStmt):
            if not epd_defined:
                report.error(line, "EPD DOCUMENT needs an EPD, and none "
                                   "is defined before it.",
                             "Define one first: EPD \"name\" ... END EPD.")
            report.writes.append(
                f"EPD DOCUMENT \"{_literal(stmt.filename) or '?'}\" (file)")

        elif isinstance(stmt, ast.EpdSensitivityStmt):
            if not epd_defined:
                report.error(line, "EPD SENSITIVITY needs an EPD, and none "
                                   "is defined before it.",
                             "Define one first: EPD \"name\" ... END EPD.")
            report.calculations.append("EPD SENSITIVITY")
            names = [_literal(g["name"]) for g in stmt.groups]
            for n in {n for n in names if n and names.count(n) > 1}:
                report.error(line, f"The group '{n}' is given twice.")

        elif isinstance(stmt, ast.ParameteriseStmt):
            name = _literal(stmt.target) or "?"
            if not stmt.confirm:
                report.error(
                    line, "PARAMETERISE PROCESS refused without CONFIRM. It "
                          "changes the process in the database for good.",
                    "Back up the database in openLCA first. Then add "
                    f"CONFIRM: PARAMETERISE PROCESS \"{name}\" CONFIRM")
            else:
                report.writes.append(f"PARAMETERISE PROCESS \"{name}\"")

        elif isinstance(stmt, ast.NewFromTemplateStmt):
            from . import templates
            name = _literal(stmt.template)
            if name is not None and templates.read(name) is None:
                report.error(line, f"There is no template called '{name}'.",
                             "Templates: " + ", ".join(
                                 f'"{n}"' for n in templates.names()) + ".")
            target = _literal(stmt.filename)
            if target and os.path.exists(target):
                report.error(line, f"'{target}' already exists, and NEW "
                                   f"FROM TEMPLATE does not write over a "
                                   f"file.")

        elif isinstance(stmt, WRITES):
            target = None
            for attr in ("name", "target", "process_ref", "ref", "source"):
                value = getattr(stmt, attr, None)
                if isinstance(value, str) and value:
                    target = value
                    break
                if isinstance(value, ast.Expr):
                    target = _literal(value)
                    break
            report.writes.append(f"{word} \"{target}\"" if target else word)

        elif isinstance(stmt, ast.ResultQueryStmt):
            if stmt.result_name not in open_results:
                if stmt.result_name:
                    report.error(
                        line, f"No open result is called "
                              f"'{stmt.result_name}'.",
                        f"Name it when it is calculated: CALCULATE "
                        f"\"system\" USING \"method\" AS "
                        f"{stmt.result_name}.")
                else:
                    report.error(
                        line, "No result is open.",
                        "CALCULATE \"system\" USING \"method\" first; "
                        "its result stays open for RESULT queries.")

        elif isinstance(stmt, ast.CloseResultStmt):
            if stmt.all:
                open_results.clear()
            elif stmt.name and stmt.name not in open_results:
                report.error(line, f"No open result is called "
                                   f"'{stmt.name}'.",
                             "CLOSE RESULT on its own closes the current "
                             "result; CLOSE RESULT ALL closes every one.")
            else:
                open_results.discard(stmt.name)

        elif isinstance(stmt, CALCULATIONS):
            if isinstance(stmt, ast.CalculateStmt):
                open_results.add(stmt.result_name)
            report.calculations.append(word)

        if not connected and not isinstance(stmt, NO_CONNECTION_NEEDED):
            report.warn(line, f"{word} needs a connection to openLCA, and "
                              f"this session has none.")

    return report
