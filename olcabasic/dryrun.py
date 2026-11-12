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
from .errors import error_dict

BUILTINS = {"ABS", "INT", "SQR", "LOG", "EXP", "SIN", "COS", "TAN", "MIN",
            "MAX", "ROUND", "LEN", "VAL", "STR$", "TRIM$", "UCASE$", "LCASE$"}

ALLOCATIONS = {"AS_DEFINED", "PHYSICAL", "ECONOMIC", "CAUSAL", "NONE"}

WRITES = (ast.FlowStmt, ast.BridgeStmt, ast.ProcessStmt, ast.SystemStmt,
          ast.EditProcessStmt, ast.EditFlowStmt, ast.UpdateParamStmt,
          ast.DeleteStmt, ast.LinkStmt, ast.MoveStmt)
CALCULATIONS = (ast.CalculateStmt, ast.ContributionStmt, ast.InventoryStmt,
                ast.MonteCarloStmt, ast.RunScenariosStmt, ast.SensitivityStmt,
                ast.TreeStmt)
NO_CONNECTION_NEEDED = (
    ast.CommentStmt, ast.LetStmt, ast.PrintExprStmt, ast.PrintResultsStmt,
    ast.DataStmt, ast.InputStmt, ast.IfStmt, ast.ForStmt, ast.ForEachStmt,
    ast.WhileStmt, ast.SubDef, ast.SubCall, ast.FunctionDef, ast.RunFileStmt,
    ast.IncludeStmt, ast.ScenarioStmt, ast.SaveResultsStmt,
    ast.ExportResultsStmt, ast.SetFolderStmt, ast.NavigateStmt, ast.PwdStmt,
    ast.UpStmt, ast.BackStmt, ast.CdirStmt, ast.MkdirStmt, ast.HelpStmt,
    ast.ClearStmt, ast.ConfirmDeleteStmt, ast.ExitStmt, ast.SaveProgramStmt)


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
    scenarios_defined = bool(runtime.scenarios)

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

        elif isinstance(stmt, CALCULATIONS):
            report.calculations.append(word)

        if not connected and not isinstance(stmt, NO_CONNECTION_NEEDED):
            report.warn(line, f"{word} needs a connection to openLCA, and "
                              f"this session has none.")

    return report
