"""
Interpreter for olcaBASIC.

Walks the AST and dispatches each statement to the bridge
(for openLCA operations) or handles it locally (variables,
control flow, output).
"""

import os
import re
import math
from typing import Any, Dict, List, Optional

from .ast_nodes import *
from .runtime import Runtime
from .bridge import LCABridge
from .parser import parse, parse_line, ParseError
from .formatting import (
    format_impacts, format_scenarios, format_sensitivity,
    format_processes, format_methods, format_systems,
    format_process_details, format_database_info, format_params,
    format_generic, format_flows, format_table, format_tree, results_to_csv,
    format_dq_systems, exchange_amount, param_values_of, format_flow_details,
)


# Category prefixes used to find elementary flows. Matched
# case-insensitively as a prefix, so "Elementary flows/resource"
# covers in ground, in water, in air, land and biotic.
# Databases name compartments differently: ecoinvent-style trees
# use "Emission to air", FLCAC/FEDEFL uses "emission/air" and calls
# soil "ground". Each direction lists every known form.
COMPARTMENT_CATEGORIES = {
    "AIR": ["Elementary flows/emission to air",
            "Elementary flows/emission/air"],
    "WATER": ["Elementary flows/emission to water",
              "Elementary flows/emission/water"],
    "SOIL": ["Elementary flows/emission to soil",
             "Elementary flows/emission/soil",
             "Elementary flows/emission/ground"],
    "NATURE": ["Elementary flows/resource"],
}


def _fmt_num(v):
    """Print whole-number floats without a trailing .0"""
    if isinstance(v, float):
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return format(v, ".12g")   # 800.1, not 800.0999999999999
    return str(v)


class BasicError(Exception):
    """Runtime error in olcaBASIC with line number."""
    def __init__(self, message: str, line: int = 0):
        self.line = line
        prefix = f"Line {line}: " if line else ""
        super().__init__(f"{prefix}{message}")


class Interpreter:
    """Executes olcaBASIC AST nodes."""

    def __init__(self, bridge: Optional[LCABridge] = None):
        self.bridge = bridge
        self.runtime = Runtime()
        self._stop_requested = False

        # Register built-in math functions
        self._builtins = {
            "ABS": abs,
            "INT": lambda x: int(math.floor(x)),
            "SQR": math.sqrt,
            "LOG": math.log,
            "EXP": math.exp,
            "SIN": math.sin,
            "COS": math.cos,
            "TAN": math.tan,
            "MIN": min,
            "MAX": max,
            "ROUND": round,
            "LEN": len,
            "VAL": float,
            "STR$": str,
            "TRIM$": str.strip,
            "UCASE$": str.upper,
            "LCASE$": str.lower,
        }

    # ── Program execution ────────────────────────────────

    def run_program(self, source: str, filename: str = ""):
        """Parse and execute a complete program."""
        # Handle INCLUDE before parsing
        source = self._process_includes(source, filename)

        try:
            statements = parse(source)
        except ParseError as e:
            print(f"Parse error: {e}")
            return

        self._stop_requested = False
        self._execute_block(statements)

    def run_line(self, text: str) -> bool:
        """Execute a single line (REPL mode). Returns False to quit."""
        text = text.strip()
        if not text:
            return True

        # Quick check for EXIT/QUIT
        if text.upper() in ("EXIT", "QUIT"):
            return False

        try:
            statements = parse(text)
        except ParseError as e:
            print(f"  Error: {e}")
            return True

        for stmt in statements:
            if stmt is None:
                continue
            if isinstance(stmt, ExitStmt):
                return False
            try:
                self._execute(stmt)
            except BasicError as e:
                print(f"  Error: {e}")
            except RuntimeError as e:
                print(f"  Error: {e}")
            except Exception as e:
                print(f"  Error: {e}")

        return True

    # ── Include processing ───────────────────────────────

    def _process_includes(self, source: str, base_path: str,
                          _seen=None) -> str:
        """Process INCLUDE directives (textual inclusion)."""
        seen = set(_seen or ())
        if base_path:
            seen.add(os.path.abspath(base_path))
        lines = source.split("\n")
        result = []
        base_dir = os.path.dirname(os.path.abspath(base_path)) if base_path else "."

        for line in lines:
            stripped = line.strip().upper()
            if stripped.startswith("INCLUDE"):
                # Extract filename
                parts = line.strip().split('"')
                if len(parts) >= 2:
                    inc_file = parts[1]
                    inc_path = os.path.join(base_dir, inc_file)
                    if os.path.abspath(inc_path) in seen:
                        raise BasicError(
                            f"INCLUDE loop: {inc_file} includes itself")
                    try:
                        with open(inc_path, "r", encoding="utf-8") as f:
                            inc_source = f.read()
                    except FileNotFoundError:
                        raise BasicError(
                            f"Include file not found: {inc_path}")
                    # Recursive includes
                    inc_source = self._process_includes(
                        inc_source, inc_path, seen)
                    result.append(inc_source)
                    continue
            result.append(line)

        return "\n".join(result)

    # ── Block execution ──────────────────────────────────

    def _execute_block(self, statements: List[Statement]):
        """Execute a list of statements in order."""
        for stmt in statements:
            if self._stop_requested:
                break
            if stmt is None:
                continue
            self._execute(stmt)

    # ── Statement dispatch ───────────────────────────────

    def _execute(self, stmt: Statement):
        """Execute a single statement."""
        if isinstance(stmt, CommentStmt):
            return

        elif isinstance(stmt, LetStmt):
            self._exec_let(stmt)

        elif isinstance(stmt, PrintStmt):
            self._exec_print(stmt)

        elif isinstance(stmt, PrintResultsStmt):
            self._exec_print_results()

        elif isinstance(stmt, PrintExprStmt):
            val = self._eval(stmt.expr)
            print(f"  {_fmt_num(val)}")

        elif isinstance(stmt, DataStmt):
            self._exec_data(stmt)

        elif isinstance(stmt, InputStmt):
            self._exec_input(stmt)

        elif isinstance(stmt, FlowStmt):
            self._exec_flow(stmt)

        elif isinstance(stmt, BridgeStmt):
            self._exec_bridge(stmt)

        elif isinstance(stmt, ProcessStmt):
            self._exec_process(stmt)

        elif isinstance(stmt, SystemStmt):
            self._exec_system(stmt)

        elif isinstance(stmt, CalculateStmt):
            self._exec_calculate(stmt)

        elif isinstance(stmt, ContributionStmt):
            self._exec_contribution(stmt)

        elif isinstance(stmt, InventoryStmt):
            self._exec_inventory(stmt)

        elif isinstance(stmt, MonteCarloStmt):
            self._exec_montecarlo(stmt)

        elif isinstance(stmt, ScenarioStmt):
            self._exec_scenario(stmt)

        elif isinstance(stmt, RunScenariosStmt):
            self._exec_run_scenarios(stmt)

        elif isinstance(stmt, SensitivityStmt):
            self._exec_sensitivity(stmt)

        elif isinstance(stmt, ValidateStmt):
            self._exec_validate(stmt)

        elif isinstance(stmt, CheckStmt):
            self._exec_check(stmt)

        elif isinstance(stmt, ExtractStmt):
            self._exec_extract(stmt)

        elif isinstance(stmt, AuditStmt):
            self._exec_audit(stmt)

        elif isinstance(stmt, SaveResultsStmt):
            self._exec_save_results(stmt)

        elif isinstance(stmt, ExportResultsStmt):
            self._exec_save_results(
                SaveResultsStmt(line=stmt.line, filename=stmt.filename))

        elif isinstance(stmt, DeleteStmt):
            self._exec_delete(stmt)

        elif isinstance(stmt, FindStmt):
            self._exec_find(stmt)

        elif isinstance(stmt, IfStmt):
            self._exec_if(stmt)

        elif isinstance(stmt, ForStmt):
            self._exec_for(stmt)

        elif isinstance(stmt, ForEachStmt):
            self._exec_for_each(stmt)

        elif isinstance(stmt, WhileStmt):
            self._exec_while(stmt)

        elif isinstance(stmt, SubDef):
            self.runtime.subs[stmt.name] = stmt

        elif isinstance(stmt, FunctionDef):
            self.runtime.functions[stmt.name] = stmt

        elif isinstance(stmt, SubCall):
            self._exec_sub_call(stmt)

        elif isinstance(stmt, RunFileStmt):
            self._exec_run_file(stmt)

        elif isinstance(stmt, EditProcessStmt):
            self._exec_edit_process(stmt)

        elif isinstance(stmt, EditFlowStmt):
            self._exec_edit_flow(stmt)

        elif isinstance(stmt, UpdateParamStmt):
            self._exec_update_param(stmt)

        elif isinstance(stmt, ShowStmt):
            self._exec_show(stmt)

        elif isinstance(stmt, LinkStmt):
            self._exec_link(stmt)

        elif isinstance(stmt, NavigateStmt):
            self._exec_navigate(stmt)

        elif isinstance(stmt, TreeStmt):
            self._exec_tree(stmt)

        elif isinstance(stmt, MoveStmt):
            self._exec_move(stmt)

        elif isinstance(stmt, ConfirmDeleteStmt):
            self.runtime.confirm_delete = stmt.enabled

        elif isinstance(stmt, SetFolderStmt):
            folder = self._eval_str(stmt.folder)
            if stmt.target == "FLOW":
                self.runtime.flow_folder = folder
                print(f"  Flow folder set: {folder}")
            else:
                self.runtime.previous_folder = self.runtime.process_folder
                self.runtime.process_folder = folder
                print(f"  Process folder set: {folder}")

        elif isinstance(stmt, HelpStmt):
            self._exec_help(stmt)

        elif isinstance(stmt, CatStmt):
            self._exec_cat(stmt)

        elif isinstance(stmt, DirStmt):
            self._exec_dir_nav(stmt)

        elif isinstance(stmt, CdStmt):
            self._exec_dir_nav(stmt)  # undocumented alias

        elif isinstance(stmt, PwdStmt):
            mode = self.runtime.navigation_mode
            here = self.runtime.nav_folders.get(mode, "") or "(root)"
            pf = self.runtime.process_folder or "(root)"
            ff = self.runtime.flow_folder or "(root)"
            print(f"  Browsing:         [{mode.title()}] {here}")
            print(f"  Build processes:  {pf}")
            print(f"  Build flows:      {ff}")

        elif isinstance(stmt, UpStmt):
            self._exec_up()

        elif isinstance(stmt, BackStmt):
            self._exec_back()

        elif isinstance(stmt, CdirStmt):
            self._exec_cdir(stmt)

        elif isinstance(stmt, ClearStmt):
            os.system("cls" if os.name == "nt" else "clear")

        elif isinstance(stmt, RefreshStmt):
            if self.bridge:
                self.bridge.refresh_caches()
                print("  Caches cleared.")

    # ── Expression evaluation ────────────────────────────

    def _eval(self, expr: Expr) -> Any:
        """Evaluate an expression and return its value."""
        if expr is None:
            return None

        if isinstance(expr, NumberLiteral):
            return expr.value

        if isinstance(expr, StringLiteral):
            return expr.value

        if isinstance(expr, Identifier):
            name = expr.name
            if self.runtime.has_var(name):
                return self.runtime.get_var(name)
            # An undefined name used to evaluate to its own text,
            # which turned typos into strings. Refuse it instead.
            raise BasicError(
                f"'{name}' is not a defined variable. If you meant "
                f"a name, put it in quotes: \"{name}\"")

        if isinstance(expr, BinOp):
            left = self._eval(expr.left)
            right = self._eval(expr.right)
            if expr.op == "+":
                return left + right
            elif expr.op == "-":
                return left - right
            elif expr.op == "*":
                return left * right
            elif expr.op == "/":
                if right == 0:
                    raise BasicError("Division by zero", 0)
                return left / right
            elif expr.op == "^":
                return left ** right

        if isinstance(expr, UnaryOp):
            val = self._eval(expr.operand)
            if expr.op == "-":
                return -val
            if expr.op == "NOT":
                return not val

        if isinstance(expr, StringConcat):
            left = str(self._eval(expr.left))
            right = str(self._eval(expr.right))
            return left + right

        if isinstance(expr, Comparison):
            left = self._eval(expr.left)
            right = self._eval(expr.right)
            if expr.op == "=":
                return left == right
            elif expr.op == "<>":
                return left != right
            elif expr.op == "<":
                return left < right
            elif expr.op == ">":
                return left > right
            elif expr.op == "<=":
                return left <= right
            elif expr.op == ">=":
                return left >= right

        if isinstance(expr, LogicalOp):
            left = self._eval(expr.left)
            if expr.op == "AND":
                return left and self._eval(expr.right)
            elif expr.op == "OR":
                return left or self._eval(expr.right)

        if isinstance(expr, FuncCall):
            return self._eval_func(expr)

        return str(expr)

    def _eval_str(self, expr: Expr) -> str:
        """Evaluate an expression and return it as a string."""
        val = self._eval(expr)
        return str(val) if val is not None else ""

    def _eval_func(self, expr: FuncCall) -> Any:
        """Evaluate a function call."""
        name_upper = expr.name.upper()
        args = [self._eval(a) for a in expr.args]

        # Built-in functions
        if name_upper in self._builtins:
            return self._builtins[name_upper](*args)

        # User-defined functions
        if expr.name in self.runtime.functions:
            func_def = self.runtime.functions[expr.name]
            self.runtime.push_scope()
            for i, param in enumerate(func_def.params):
                if i < len(args):
                    self.runtime.set_var(param, args[i])
            self._execute_block(func_def.body)
            # Return value is stored in a variable named after the function
            result = self.runtime.get_var(expr.name) if self.runtime.has_var(expr.name) else None
            self.runtime.pop_scope()
            return result

        raise BasicError(f"Unknown function: {expr.name}")

    def _expr_to_formula(self, expr: Expr) -> str:
        """Convert an expression AST to a formula string for openLCA.
        Named variables become parameter references; numbers stay as numbers."""
        if isinstance(expr, NumberLiteral):
            return str(expr.value)
        if isinstance(expr, Identifier):
            return expr.name
        if isinstance(expr, BinOp):
            left = self._expr_to_formula(expr.left)
            right = self._expr_to_formula(expr.right)
            return f"({left} {expr.op} {right})"
        if isinstance(expr, UnaryOp):
            operand = self._expr_to_formula(expr.operand)
            return f"({expr.op}{operand})"
        if isinstance(expr, FuncCall):
            args = ", ".join(self._expr_to_formula(a) for a in expr.args)
            return f"{expr.name}({args})"
        # Fallback: evaluate and return as string
        return str(self._eval(expr))

    def _expr_is_variable(self, expr: Expr) -> bool:
        """Check if an expression references any named variables."""
        if isinstance(expr, Identifier):
            return self.runtime.has_var(expr.name)
        if isinstance(expr, BinOp):
            return (self._expr_is_variable(expr.left)
                    or self._expr_is_variable(expr.right))
        if isinstance(expr, UnaryOp):
            return self._expr_is_variable(expr.operand)
        if isinstance(expr, FuncCall):
            return any(self._expr_is_variable(a) for a in expr.args)
        return False

    # ── Statement executors ──────────────────────────────

    def _exec_let(self, stmt: LetStmt):
        value = self._eval(stmt.expr)
        self.runtime.set_var(stmt.name, value)
        # Top-level variables defined from other variables keep their
        # expression, so they become formula parameters in openLCA
        if self.runtime.current_scope is self.runtime.global_scope:
            if self._expr_is_variable(stmt.expr):
                self.runtime.var_exprs[stmt.name] = stmt.expr
            else:
                self.runtime.var_exprs.pop(stmt.name, None)

    def _exec_data(self, stmt: DataStmt):
        for val_expr in stmt.values:
            val = self._eval(val_expr)
            self.runtime.push_data(val)

    def _exec_input(self, stmt: InputStmt):
        response = input(f"  {stmt.prompt} ")
        # Try to convert to number
        try:
            value = float(response)
            if value == int(value):
                value = int(value)
        except ValueError:
            value = response
        self.runtime.set_var(stmt.variable, value)

    def _require_bridge(self, line: int = 0):
        if not self.bridge or not self.bridge.connected:
            raise BasicError(
                "Not connected to openLCA. Cannot execute this command.",
                line)

    def _exec_print(self, stmt: PrintStmt):
        sub = stmt.sub_command.upper()

        if sub == "DATABASE":
            self._require_bridge(stmt.line)
            result = self.bridge.database_info()
            print(format_database_info(result))

        elif sub == "PROCESSES":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            term = args[0] if len(args) > 0 else ""
            cat = args[1] if len(args) > 1 else ""
            loc = args[2] if len(args) > 2 else ""
            result = self.bridge.search_processes(term, cat, loc)
            print(format_processes(result))

        elif sub == "METHODS":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            term = args[0] if args else ""
            result = self.bridge.list_methods(term)
            print(format_methods(result))

        elif sub == "SYSTEMS":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            term = args[0] if args else ""
            result = self.bridge.list_systems(term)
            print(format_systems(result))

        elif sub == "PARAMS":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            ref = args[0] if args else ""
            result = self.bridge.get_system_parameters(ref)
            print(format_params(result))

        elif sub == "GLOBAL_PARAMS":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            filt = args[0] if args else ""
            result = self.bridge.get_global_parameters(filt)
            print(format_params(result))

        elif sub == "DETAILS":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            ref = args[0] if args else ""
            proc = self.bridge.resolve_process_strict(ref)
            if "error" in proc:
                raise BasicError(proc["error"], stmt.line)
            result = self.bridge.get_process_details(proc["process_id"])
            print(format_process_details(result))

        elif sub == "QUALITY":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            ref = args[0] if args else ""
            result = self.bridge.get_data_quality(ref)
            print(format_generic(result))

        elif sub == "LINKS":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            ref = args[0] if args else ""
            filt = args[1] if len(args) > 1 else ""
            result = self.bridge.get_system_links(ref, filt)
            print(format_generic(result))

        elif sub == "UNITS":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            name = args[0] if args else ""
            result = self.bridge.find_unit(name)
            print(format_generic(result))

        elif sub == "DQ_SYSTEMS":
            self._require_bridge(stmt.line)
            result = self.bridge.list_dq_systems()
            if "error" in result:
                raise BasicError(result["error"], stmt.line)
            print(format_dq_systems(result))

        elif sub == "FAMILY":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            family = args[0] if args else ""
            result = self.bridge.set_database_family(family)
            print(format_generic(result))

        elif sub == "EXPR":
            # Multiple comma-separated expressions
            vals = [self._eval(a) for a in stmt.args]
            print("  " + "  ".join(_fmt_num(v) for v in vals))

        else:
            print(f"  Unknown PRINT sub-command: {sub}")

    def _exec_print_results(self):
        results = self.runtime.last_results
        if not results:
            print("  No results to display. Run a calculation first.")
            return

        rtype = self.runtime.last_results_type
        if rtype == "calculate":
            print(format_impacts(results))
        elif rtype == "scenarios":
            print(format_scenarios(results))
        elif rtype == "sensitivity":
            print(format_sensitivity(results))
        else:
            print(format_generic(results))

    def _exec_flow(self, stmt: FlowStmt):
        self._require_bridge(stmt.line)
        name = self._eval_str(stmt.name)
        folder = self._eval_str(stmt.folder) if stmt.folder else self.runtime.flow_folder

        ft = stmt.flow_type.lower()
        if stmt.direction:
            ft = "elementary"

        # Map direction to category path
        search_cat = ""
        if stmt.direction:
            search_cat = COMPARTMENT_CATEGORIES[stmt.direction]
            if stmt.direction == "NATURE":
                folder = folder or "Elementary flows/resource/in ground"
            else:
                folder = folder or search_cat[0]

        if stmt.is_new:
            # NEW: always create
            result = self.bridge.create_flow(name, stmt.unit, folder, ft)
            if "error" in result:
                raise BasicError(result["error"], stmt.line)
            existed = result.get("already_existed", False)
            status = "exists" if existed else "created"
            print(f"  Flow {status}: {name} ({stmt.unit}, {ft})")
        else:
            # Default: find existing
            found = self.bridge.find_flow(
                name, stmt.unit, search_cat, strict=bool(search_cat))
            if found:
                print(f"  Flow found: {found['flow_name']}")
            else:
                # Not found: create it
                result = self.bridge.create_flow(name, stmt.unit, folder, ft)
                if "error" in result:
                    raise BasicError(result["error"], stmt.line)
                print(f"  Flow created: {name} ({stmt.unit}, {ft})")

    def _exec_bridge(self, stmt: BridgeStmt):
        self._require_bridge(stmt.line)
        name = self._eval_str(stmt.name)
        folder = self._eval_str(stmt.folder) if stmt.folder else self.runtime.process_folder
        provider_id = None

        if stmt.provider:
            prov_str = self._eval_str(stmt.provider)
            prov = self.bridge.resolve_process_strict(prov_str)
            if "error" in prov:
                raise BasicError(prov["error"], stmt.line)
            provider_id = prov["process_id"]

        provider_flow_id = None
        if stmt.provider_flow:
            provider_flow_id = self._eval_str(stmt.provider_flow)

        result = self.bridge.create_bridge(
            name, stmt.unit, folder, provider_id,
            provider_flow_id, stmt.is_waste)

        if "error" in result:
            raise BasicError(result["error"], stmt.line)

        existed = result.get("already_existed", False)
        status = "exists" if existed else "created"
        print(f"  Bridge {status}: {name} ({stmt.unit})")

    def _exec_process(self, stmt: ProcessStmt):
        self._require_bridge(stmt.line)
        name = self._eval_str(stmt.name)
        folder = self._eval_str(stmt.folder) if stmt.folder else self.runtime.process_folder
        description = self._eval_str(stmt.description) if stmt.description else ""
        location = self._eval_str(stmt.location) if stmt.location else None
        flow_schema = self._eval_str(stmt.flow_schema) if stmt.flow_schema else None
        process_schema = self._eval_str(stmt.process_schema) if stmt.process_schema else None

        # Handle READ INPUTS FROM DATA. Work on a copy so running the
        # same PROCESS twice (e.g. in a loop) doesn't pile up exchanges.
        ex_list = list(stmt.exchanges)
        if stmt.read_data:
            while self.runtime.has_data():
                flow_name = self.runtime.read_data()
                amount = self.runtime.read_data()
                unit = self.runtime.read_data()
                ex = ExchangeDef(
                    direction="INPUT",
                    flow_name=StringLiteral(str(flow_name)),
                    amount=NumberLiteral(float(amount)),
                    unit=str(unit),
                )
                ex_list.append(ex)

        # Local LETs inside the PROCESS block must be visible to the
        # exchange amounts, so evaluate them into a temporary scope.
        self.runtime.push_scope()
        try:
            for let_stmt in stmt.local_params:
                self.runtime.set_var(let_stmt.name,
                                     self._eval(let_stmt.expr))
            exchanges = self._build_exchanges(stmt, folder, ex_list)
            local_values = {n: self.runtime.get_var(n) for n in
                            (l.name for l in stmt.local_params)}
        finally:
            self.runtime.pop_scope()

        # Build parameter dicts from local LET statements
        parameters = []
        param_names = set()
        for let_stmt in stmt.local_params:
            val = local_values[let_stmt.name]
            if not isinstance(val, (int, float)):
                raise BasicError(
                    f"Parameter '{let_stmt.name}' must be a number",
                    stmt.line)
            parameters.append({"name": let_stmt.name, "value": float(val)})
            param_names.add(let_stmt.name)

        # Top-level variables used in exchange formulas become openLCA
        # GLOBAL parameters (not per-process copies), so a variable
        # shared by several processes is one parameter, and scenarios
        # and sensitivity change it everywhere. Local LETs above stay
        # process-scope and take precedence inside this process.
        for ex_dict in exchanges:
            formula = ex_dict.get("formula", "")
            if formula:
                for var_name in self._referenced_globals(formula):
                    if var_name not in param_names:
                        self._sync_global(var_name, stmt.line)

        return self._create_process(stmt, name, folder, exchanges,
                                    parameters, description, location,
                                    flow_schema, process_schema)

    def _referenced_globals(self, formula: str) -> list:
        """Top-level variables named in a formula (whole words only,
        so 'mass' doesn't match 'cement_mass')."""
        names = set(self.runtime.get_numeric_globals()) | set(
            self.runtime.var_exprs)
        return [n for n in sorted(names)
                if re.search(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])",
                             formula)]

    def _sync_global(self, name: str, line: int, _chain=(), force=False):
        """Create or update the openLCA global parameter for a
        top-level variable. Derived variables become formula
        parameters, with their inputs synced first."""
        if name in _chain:
            raise BasicError(
                f"Circular definition: {' -> '.join(_chain + (name,))}", line)

        expr = self.runtime.var_exprs.get(name)
        if expr is not None:
            formula = self._expr_to_formula(expr)
            for dep in self._referenced_globals(formula):
                if dep != name:
                    self._sync_global(dep, line, _chain + (name,))
            desired = ("formula", formula)
        else:
            val = self.runtime.get_var(name)
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise BasicError(
                    f"'{name}' is used in an exchange but isn't a number",
                    line)
            desired = ("value", float(val))

        previous = self.runtime.synced_globals.get(name)
        if previous == desired and not force:
            return

        if desired[0] == "formula":
            result = self.bridge.create_global_parameter(
                name, formula=desired[1])
        else:
            result = self.bridge.create_global_parameter(
                name, value=desired[1])
        if "error" in result:
            raise BasicError(f"Global parameter '{name}': "
                             f"{result['error']}", line)

        # Warn when overwriting a global this session didn't create:
        # it may belong to another model in the same database
        prev = result.get("previous") or {}
        norm = lambda f: re.sub(r"\s+", "", f or "")
        if desired[0] == "formula":
            really_changed = norm(prev.get("formula")) != norm(desired[1])
        else:
            really_changed = (bool(prev.get("formula"))
                              or prev.get("value") != desired[1])
        if (previous is None and result.get("already_existed")
                and really_changed):
            was = prev.get("formula") or prev.get("value")
            print(f"  NOTE: global parameter '{name}' already existed "
                  f"(was {was}) and has been updated. Other models in "
                  f"this database that use it will change too.")
        self.runtime.synced_globals[name] = desired

    def _check_overridable(self, names, what: str, line: int):
        """Derived variables are calculated by openLCA; point users at
        the inputs instead of silently ignoring the override."""
        for n in names:
            expr = self.runtime.var_exprs.get(n)
            if expr is not None:
                deps = self._referenced_globals(self._expr_to_formula(expr))
                raise BasicError(
                    f"'{n}' is calculated from {' and '.join(deps)}, so it "
                    f"can't be set in a {what}. Change "
                    f"{' or '.join(deps)} instead.", line)

    def _build_exchanges(self, stmt: ProcessStmt, folder: str,
                         ex_list: list) -> list:
        exchanges = []
        for ex in ex_list:
            if ex.legacy_new and "NEW" not in self.runtime.deprecation_shown:
                self.runtime.deprecation_shown.add("NEW")
                print("  NOTE: INPUT NEW and OUTPUT NEW are deprecated. Use "
                      "INPUT MAKE FLOW and OUTPUT MAKE FLOW instead; the old "
                      "form will be removed in a future version.")
            flow_name = self._eval_str(ex.flow_name)
            unit = ex.unit

            # Determine flow type. New foreground flows go in the
            # SET FLOW FOLDER if one is set, else the process folder.
            flow_type = "product"
            category = self.runtime.flow_folder or folder
            if ex.is_product:
                flow_type = "product"
            elif ex.is_waste:
                flow_type = "waste"
            elif ex.direction_compartment:
                flow_type = "elementary"
                search_cats = COMPARTMENT_CATEGORIES[ex.direction_compartment]
                category = search_cats[0]   # where a NEW flow is created
            elif ex.direction == "OUTPUT":
                flow_type = "product"

            # Resolve the flow: find existing or create new
            flow_id = None
            provider_id = None

            if ex.is_new:
                # NEW keyword: always create a fresh flow
                flow_result = self.bridge.create_flow(
                    flow_name, unit, category, flow_type)
                if "error" in flow_result:
                    raise BasicError(
                        f"Flow '{flow_name}': {flow_result['error']}",
                        stmt.line)
                flow_id = flow_result["flow_id"]

            elif ex.direction_compartment:
                # Elementary flow (TO AIR, TO WATER, etc.)
                # Never try process lookup; search flows by category
                flow_match = self.bridge.find_flow(
                    flow_name, unit, search_cats, strict=True)
                if flow_match:
                    flow_id = flow_match["flow_id"]
                    if flow_match.get("ambiguous"):
                        print(f"  NOTE: '{flow_name}' exists in "
                              f"{flow_match['ambiguous']} sub-compartments; "
                              f"using {flow_match['category']}")
                else:
                    raise BasicError(
                        f"Elementary flow '{flow_name}' not found under "
                        f"{' or '.join(repr(c) for c in search_cats)}. "
                        f"FIND FLOW \"{flow_name}\" shows the names and "
                        f"categories in your database. Check the name matches your "
                        f"database, or use NEW to create it (note: "
                        f"new elementary flows have no characterisation "
                        f"factors and will contribute zero to impacts).",
                        stmt.line)

            else:
                # Product/waste flow: find existing process or flow.
                # USE FLOW skips the process lookup; USE PROCESS
                # insists on one (it's how you get a provider).
                location_filter = (self._eval_str(ex.location)
                                   if ex.location else "")
                if ex.use_type == "FLOW":
                    if location_filter:
                        raise BasicError(
                            "LOCATION picks between processes, so it "
                            "can't be used with USE FLOW", stmt.line)
                    proc_match = None
                else:
                    proc_match = self.bridge.find_process_qref_flow(
                        flow_name, location_filter)
                if proc_match and "error" in proc_match:
                    raise BasicError(proc_match["error"], stmt.line)
                if not proc_match and ex.use_type == "PROCESS":
                    raise BasicError(
                        f"No process found matching '{flow_name}'. "
                        f"FIND PROCESS shows the names in your database, "
                        f"or use USE FLOW to link a flow without a "
                        f"provider.", stmt.line)
                if proc_match:
                    flow_id = proc_match["flow_id"]
                    provider_id = proc_match["process_id"]
                    if proc_match.get("ambiguous"):
                        loc = proc_match.get("location", "")
                        print(f"  WARNING: '{flow_name}' matched "
                              f"{proc_match['ambiguous']} processes, "
                              f"using '{proc_match['process_name']}'"
                              f"{' | ' + loc if loc else ''}. "
                              f"Add LOCATION \"code\" to pick a "
                              f"specific one.")
                else:
                    # Try to find a flow by name directly
                    flow_match = self.bridge.find_flow(
                        flow_name, unit, category)
                    if flow_match and location_filter:
                        raise BasicError(
                            f"LOCATION was given, but '{flow_name}' "
                            f"matched a flow rather than a process, so "
                            f"there is no provider to choose between",
                            stmt.line)
                    if flow_match:
                        flow_id = flow_match["flow_id"]
                        if flow_match.get("ambiguous"):
                            print(f"  WARNING: '{flow_name}' matched "
                                  f"{flow_match['ambiguous']} flows, "
                                  f"using first match.")
                    else:
                        # Nothing found
                        if ex.direction == "INPUT":
                            raise BasicError(
                                f"No process or flow found matching "
                                f"'{flow_name}'. Check the spelling, "
                                f"or use INPUT MAKE FLOW to create a "
                                f"new flow.",
                                stmt.line)
                        else:
                            print(f"  NOTE: Creating new flow "
                                  f"'{flow_name}' (use OUTPUT NEW to "
                                  f"suppress this message)")
                            flow_result = self.bridge.create_flow(
                                flow_name, unit, category, flow_type)
                            if "error" in flow_result:
                                raise BasicError(
                                    f"Flow '{flow_name}': "
                                    f"{flow_result['error']}",
                                    stmt.line)
                            flow_id = flow_result["flow_id"]

            # Build exchange dict
            ex_dict = {
                "flow_id": flow_id,
                "flow_name": flow_name,
                "unit": unit,
                "is_input": ex.direction == "INPUT",
                "is_qref": ex.is_product,
            }

            # Set provider if we found a matching process
            if provider_id:
                ex_dict["provider_id"] = provider_id

            # Pedigree scores (checked against the FLOW SCHEMA by the
            # engine) and a per-line comment, both optional
            if ex.pedigree is not None:
                ex_dict["dq_entry"] = (ex.pedigree if isinstance(ex.pedigree, str)
                                       else "(" + ";".join(str(n) for n in ex.pedigree) + ")")
            if ex.comment is not None:
                ex_dict["comment"] = self._eval_str(ex.comment)

            # Handle amount: explicit formula, variable reference, or bare number
            if ex.formula:
                ex_dict["formula"] = self._eval_str(ex.formula)
            elif self._expr_is_variable(ex.amount):
                # Expression contains variables: pass as formula
                ex_dict["formula"] = self._expr_to_formula(ex.amount)
            else:
                # Bare number: auto-parametrised by the engine
                ex_dict["amount"] = float(self._eval(ex.amount))

            # Explicit provider overrides auto-detected one. It must
            # identify exactly one process (UUID or unique name).
            if ex.provider:
                prov_str = self._eval_str(ex.provider)
                prov = self.bridge.resolve_process_strict(prov_str)
                if "error" in prov:
                    hint = (" Or use LOCATION \"code\" on this line instead "
                            "of PROVIDER." if prov.get("ambiguous") else "")
                    raise BasicError(f"PROVIDER: {prov['error']}{hint}",
                                     stmt.line)
                ex_dict["provider_id"] = prov["process_id"]

            exchanges.append(ex_dict)
        return exchanges

    def _create_process(self, stmt, name, folder, exchanges, parameters,
                        description, location, flow_schema,
                        process_schema):
        result = self.bridge.create_process(
            name, folder, exchanges, parameters or None,
            description, location, flow_schema, process_schema)

        if "error" in result:
            # Put the engine's wording into olcaBASIC terms
            msg = result["error"].replace(
                "Set flow_schema.",
                'Add a FLOW SCHEMA "name" line to the PROCESS block '
                '(PRINT DQ SYSTEMS lists the names).')
            raise BasicError(msg, stmt.line)

        if result.get("already_existed", False):
            where = folder or "(root)"
            print(f"  WARNING: process '{name}' already exists in {where}. "
                  f"It was NOT changed, so the exchanges above were not "
                  f"applied. DELETE PROCESS \"{name}\" first to rebuild it.")
            return
        ex_count = result.get("exchange_count", 0)
        p_count = result.get("parameter_count", 0)
        print(f"  Process created: {name} "
              f"({ex_count} exchanges, {p_count} parameters)")

    def _exec_system(self, stmt: SystemStmt):
        self._require_bridge(stmt.line)
        proc_ref = self._eval_str(stmt.process_ref)
        folder = self._eval_str(stmt.folder) if stmt.folder else None
        linking = stmt.linking.lower()
        target_amount = float(self._eval(stmt.target_amount)) if stmt.target_amount else 1.0
        target_unit = stmt.target_unit or None
        target_prop = self._eval_str(stmt.target_property) if stmt.target_property else None

        print(f"  Creating product system from: {proc_ref}...")
        result = self.bridge.create_system(
            proc_ref, linking, target_amount, target_unit,
            target_prop, folder)

        if "error" in result:
            raise BasicError(result["error"], stmt.line)

        sys_name = result.get("system_name", proc_ref)
        if result.get("already_existed", False):
            print(f"  WARNING: product system '{sys_name}' already exists "
                  f"and was reused as it is. If the process changed, "
                  f"DELETE SYSTEM \"{sys_name}\" first to rebuild it.")
        else:
            print(f"  System created: {sys_name}")
        if result.get("warnings"):
            for w in result["warnings"]:
                print(f"  WARNING: {w}")

    def _exec_calculate(self, stmt: CalculateStmt):
        self._require_bridge(stmt.line)
        system = self._eval_str(stmt.system)
        method = self._eval_str(stmt.method)
        print(f"  Calculating: {system} using {method}...")
        result = self.bridge.calculate(system, method, stmt.allocation)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        self.runtime.store_results(result, "calculate")
        print(format_impacts(result))

    def _exec_contribution(self, stmt: ContributionStmt):
        self._require_bridge(stmt.line)
        system = self._eval_str(stmt.system)
        method = self._eval_str(stmt.method)
        cats = [self._eval_str(c) for c in stmt.categories] or None
        print(f"  Contribution analysis: {system}...")
        result = self.bridge.contribution(
            system, method, stmt.top, cats, stmt.allocation)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        self.runtime.store_results(result, "contribution")
        print(format_generic(result))

    def _exec_inventory(self, stmt: InventoryStmt):
        self._require_bridge(stmt.line)
        system = self._eval_str(stmt.system)
        method = self._eval_str(stmt.method)
        print(f"  Inventory: {system}...")
        result = self.bridge.inventory(
            system, method, stmt.max_flows, stmt.allocation)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        self.runtime.store_results(result, "inventory")
        print(format_generic(result))

    def _exec_montecarlo(self, stmt: MonteCarloStmt):
        self._require_bridge(stmt.line)
        system = self._eval_str(stmt.system)
        method = self._eval_str(stmt.method)
        print(f"  Monte Carlo ({stmt.runs} runs): {system}...")
        result = self.bridge.monte_carlo(
            system, method, stmt.runs, stmt.allocation)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        self.runtime.store_results(result, "montecarlo")
        print(format_generic(result))

    def _exec_scenario(self, stmt: ScenarioStmt):
        """Accumulate a scenario definition."""
        self._check_overridable([l.name for l in stmt.overrides],
                                "SCENARIO", stmt.line)
        overrides = {}
        for let_stmt in stmt.overrides:
            val = self._eval(let_stmt.expr)
            overrides[let_stmt.name] = float(val)
        self.runtime.scenarios[stmt.name] = overrides

    def _exec_run_scenarios(self, stmt: RunScenariosStmt):
        self._require_bridge(stmt.line)
        system = self._eval_str(stmt.system)
        method = self._eval_str(stmt.method)

        if stmt.from_csv:
            # CSV-based scenarios
            csv_path = self._eval_str(stmt.from_csv)
            save_to = self._eval_str(stmt.save_to) if stmt.save_to else ""
            print(f"  Running scenarios from {csv_path}...")
            result = self.bridge.run_scenarios_csv(
                system, method, csv_path, save_to, stmt.allocation)
        else:
            # Use accumulated SCENARIO blocks
            scenarios = self.runtime.scenarios
            if not scenarios:
                raise BasicError(
                    "No scenarios defined. Use SCENARIO blocks before "
                    "RUN SCENARIOS.", stmt.line)
            print(f"  Running {len(scenarios)} scenarios...")
            result = self.bridge.run_scenarios(
                system, method, scenarios, stmt.allocation)

        if "error" in result:
            raise BasicError(result["error"], stmt.line)

        self.runtime.store_results(result, "scenarios")
        print(format_scenarios(result))

        # Clear accumulated scenarios after running
        self.runtime.scenarios.clear()

    def _exec_sensitivity(self, stmt: SensitivityStmt):
        self._require_bridge(stmt.line)
        system = self._eval_str(stmt.system)
        method = self._eval_str(stmt.method)

        if stmt.from_csv:
            csv_path = self._eval_str(stmt.from_csv)
            save_to = self._eval_str(stmt.save_to) if stmt.save_to else ""
            print(f"  Running sensitivity from {csv_path}...")
            result = self.bridge.run_sensitivity_csv(
                system, method, csv_path, stmt.variation_pct,
                save_to, stmt.allocation)
        else:
            params = stmt.parameters
            self._check_overridable(params, "SENSITIVITY", stmt.line)
            print(f"  Sensitivity +/-{stmt.variation_pct}% on "
                  f"{len(params)} parameters...")
            result = self.bridge.run_sensitivity(
                system, method, params, stmt.variation_pct,
                stmt.allocation)

        if "error" in result:
            raise BasicError(result["error"], stmt.line)

        self.runtime.store_results(result, "sensitivity")
        print(format_sensitivity(result))

    def _exec_validate(self, stmt: ValidateStmt):
        self._require_bridge(stmt.line)
        ref = self._eval_str(stmt.system)
        print(f"  Validating: {ref}...")
        result = self.bridge.validate_system(ref, stmt.with_calc)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        print(format_generic(result))

    def _exec_check(self, stmt: CheckStmt):
        self._require_bridge(stmt.line)
        ref = self._eval_str(stmt.system)
        print(f"  Checking: {ref} (Tier {stmt.tier})...")
        if stmt.tier == 1:
            result = self.bridge.validate_system(ref)
            print(format_generic(result))
        elif stmt.tier >= 2:
            print("  Tier 2/3 checks require extract_model comparison.")
            print("  Use EXTRACT and COMPARE for source comparison.")

    def _exec_extract(self, stmt: ExtractStmt):
        self._require_bridge(stmt.line)
        folder = self._eval_str(stmt.folder)
        print(f"  Extracting: {folder}...")
        result = self.bridge.extract_model(folder)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        print(format_generic(result))

    def _exec_audit(self, stmt: AuditStmt):
        self._require_bridge(stmt.line)
        folder = self._eval_str(stmt.folder)
        print(f"  Auditing: {folder}...")
        result = self.bridge.audit_model(folder)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        print(format_generic(result))

    def _exec_save_results(self, stmt: SaveResultsStmt):
        if not self.runtime.last_results:
            print("  No results to save.")
            return
        filename = self._eval_str(stmt.filename)
        csv_str = results_to_csv(
            self.runtime.last_results,
            self.runtime.last_results_type)
        if not csv_str.strip():
            raise BasicError(
                f"SAVE RESULTS doesn't support "
                f"{self.runtime.last_results_type} results yet", stmt.line)
        # newline="" stops Windows writing blank rows between lines
        with open(filename, "w", newline="", encoding="utf-8") as f:
            f.write(csv_str)
        print(f"  Results saved to {filename}")

    def _exec_delete(self, stmt: DeleteStmt):
        self._require_bridge(stmt.line)
        ref = self._eval_str(stmt.ref)
        if not stmt.entity_type:
            raise BasicError("Say what to delete: DELETE PROCESS or "
                             "DELETE SYSTEM", stmt.line)
        etype = stmt.entity_type.lower()
        if etype == "system":
            etype = "product_system"

        # The engine deletes by UUID, so resolve the name first.
        # (Passing the name always came back 'not found'.)
        target = self.bridge.resolve_entity_strict(etype, ref)
        if "error" in target:
            raise BasicError(target["error"], stmt.line)
        if target.get("not_found"):
            print(f"  Not found: {ref} (nothing to delete)")
            return

        if not self.runtime.confirm_delete:
            confirm = input(
                f"  Delete {stmt.entity_type} '{target['name']}'? (yes/no) ")
            if confirm.lower() not in ("yes", "y"):
                print("  Cancelled.")
                return
        else:
            print(f"  Deleting {stmt.entity_type} '{target['name']}'...")

        result = self.bridge.delete_entity(etype, target["id"])
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        print(f"  Deleted: {result.get('name', ref)}")
        self.bridge.refresh_caches()

    def _exec_find(self, stmt: FindStmt):
        self._require_bridge(stmt.line)
        term = self._eval_str(stmt.search_term)
        etype = stmt.entity_type.upper()

        if etype == "PROCESS":
            loc = self._eval_str(stmt.location) if stmt.location else ""
            cat = self._eval_str(stmt.category) if stmt.category else ""
            result = self.bridge.search_processes(term, cat, loc)
            print(format_processes(result))
        elif etype == "FLOW":
            cat = self._eval_str(stmt.category) if stmt.category else ""
            result = self.bridge.search_flows(term, cat)
            if "error" in result:
                raise BasicError(result["error"], stmt.line)
            print(format_flows(result))
        elif etype == "METHOD":
            result = self.bridge.list_methods(term)
            print(format_methods(result))
        elif etype == "CHEMICAL":
            result = self.bridge.chemical_synonyms(term)
            print(format_generic(result))
        elif etype == "UNIT":
            result = self.bridge.find_unit(term)
            print(format_generic(result))
        else:
            print(f"  Unknown FIND type: {etype}")

        # Store result if assigned to a variable
        if stmt.assign_to:
            self.runtime.set_var(stmt.assign_to, result)

    # ── Control flow ─────────────────────────────────────

    def _exec_if(self, stmt: IfStmt):
        condition = self._eval(stmt.condition)
        if condition:
            self._execute_block(stmt.then_body)
        else:
            self._execute_block(stmt.else_body)

    def _exec_for(self, stmt: ForStmt):
        start = float(self._eval(stmt.start))
        end = float(self._eval(stmt.end))
        step = float(self._eval(stmt.step)) if stmt.step else 1.0

        if step == 0:
            raise BasicError("FOR loop STEP cannot be 0", stmt.line)
        # Count iterations up front so float steps (0.1) don't drift
        n = int(math.floor((end - start) / step + 1e-9)) + 1
        whole = all(float(v).is_integer() for v in (start, step))
        for k in range(max(n, 0)):
            i = start + k * step
            self.runtime.set_var(stmt.variable, int(i) if whole else i)
            self._execute_block(stmt.body)
            if self._stop_requested:
                break

    def _exec_for_each(self, stmt: ForEachStmt):
        values = [self._eval(v) for v in stmt.values]
        for val in values:
            self.runtime.set_var(stmt.variable, val)
            self._execute_block(stmt.body)
            if self._stop_requested:
                break

    def _exec_while(self, stmt: WhileStmt):
        while self._eval(stmt.condition):
            self._execute_block(stmt.body)
            if self._stop_requested:
                break

    def _exec_sub_call(self, stmt: SubCall):
        name = stmt.name
        if name not in self.runtime.subs:
            raise BasicError(f"SUB '{name}' is not defined", stmt.line)

        sub_def = self.runtime.subs[name]
        args = [self._eval(a) for a in stmt.args]

        self.runtime.push_scope()
        for i, param in enumerate(sub_def.params):
            if i < len(args):
                self.runtime.set_var(param, args[i])
        self._execute_block(sub_def.body)
        self.runtime.pop_scope()

    def _exec_run_file(self, stmt: RunFileStmt):
        filename = self._eval_str(stmt.filename)
        try:
            with open(filename, "r", encoding="utf-8") as f:
                source = f.read()
            self.run_program(source, filename)
        except FileNotFoundError:
            raise BasicError(f"File not found: {filename}", stmt.line)

    def _exec_update_param(self, stmt: UpdateParamStmt):
        """UPDATE PARAMETER: set the variable, and write the openLCA
        global parameter straight away (LET only writes it when a
        PROCESS, LINK or EDIT uses it)."""
        self._require_bridge(stmt.line)
        if self.runtime.current_scope is not self.runtime.global_scope:
            raise BasicError("UPDATE PARAMETER only works at the top level "
                             "of a program, not inside a SUB or FUNCTION",
                             stmt.line)
        before = (self.runtime.get_var(stmt.name)
                  if self.runtime.has_var(stmt.name) else None)
        self._exec_let(LetStmt(line=stmt.line, name=stmt.name, expr=stmt.expr))
        self._sync_global(stmt.name, stmt.line, force=True)
        expr = self.runtime.var_exprs.get(stmt.name)
        now = self.runtime.get_var(stmt.name)
        shown = (f"{self._expr_to_formula(expr)} (currently {_fmt_num(now)})"
                 if expr is not None else _fmt_num(now))
        was = f" (was {_fmt_num(before)})" if before is not None else ""
        print(f"  Global parameter {stmt.name} = {shown}{was}")

    def _exec_edit_flow(self, stmt: EditFlowStmt):
        """EDIT FLOW: add or update flow properties, set the reference."""
        self._require_bridge(stmt.line)
        target = self._eval_str(stmt.target)
        found = self.bridge.find_flow(target, "", "")
        if not found:
            raise BasicError(f"Flow not found: '{target}'", stmt.line)
        if found.get("ambiguous"):
            raise BasicError(f"'{target}' matches {found['ambiguous']} flows. "
                             f"Give the exact name of the one you mean.",
                             stmt.line)
        ops = []
        for op in stmt.operations:
            entry = {"op": op["op"], "property": self._eval_str(op["property"])}
            if op["op"] in ("add", "update"):
                amount = self._eval(op["amount"])
                if not isinstance(amount, (int, float)) or isinstance(amount, bool):
                    raise BasicError("The amount in a property relation must "
                                     "be a number", op.get("line", stmt.line))
                entry.update(amount=float(amount), unit=op["unit"],
                             per_unit=op["per_unit"])
            ops.append(entry)

        result = self.bridge.edit_flow(found["flow_id"], ops)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        print(f"  Edited flow: {result.get('flow_name', target)}")
        for c in result.get("changes", []):
            print(f"    {c}")
        # A flow outside your own folders is shared with other models
        cat = (result.get("category") or found.get("category") or "").lower()
        mine = [f.lower().rstrip("/") for f in (self.runtime.flow_folder,
                                                self.runtime.process_folder) if f]
        if not any(cat == m or cat.startswith(m + "/") for m in mine):
            print(f"  NOTE: '{target}' isn't in your build folders, so this "
                  f"change affects every model that uses it.")

    def _exec_edit_process(self, stmt: EditProcessStmt):
        """EDIT PROCESS: add, remove and update exchanges and
        parameters, and set description, folder and location."""
        self._require_bridge(stmt.line)
        target = self._eval_str(stmt.target)
        found = self.bridge.resolve_process_strict(target)
        if "error" in found:
            raise BasicError(found["error"], stmt.line)
        proc_id = found["process_id"]
        proc = self.bridge.get_process_object(proc_id)
        if proc is None:
            raise BasicError(f"Could not load process '{target}'", stmt.line)
        current = list(proc.exchanges or [])

        def find_exchange(spec, action):
            """One exchange matching a flow or provider name."""
            name = self._eval_str(spec["name"])
            want = spec["direction"]
            lname = name.lower()
            hits = [ex for ex in current
                    if (not want or ex.is_input == (want == "INPUT"))
                    and ((ex.flow and ex.flow.name.lower() == lname) or
                         (ex.default_provider and ex.default_provider.name
                          and ex.default_provider.name.lower() == lname))]
            line = spec.get("line", stmt.line)
            if not hits:
                names = sorted({ex.flow.name for ex in current if ex.flow})
                raise BasicError(
                    f"'{target}' has no {want.lower() or 'exchange'} called "
                    f"'{name}'. Its exchanges are: {', '.join(names)}", line)
            if len(hits) > 1:
                raise BasicError(
                    f"'{name}' matches {len(hits)} exchanges in '{target}'. "
                    f"Say INPUT or OUTPUT to pick one.", line)
            return name, hits[0], line

        # Removals. The engine removes by flow, so a flow that appears
        # more than once can't be removed on its own.
        remove_ids = []
        for spec in stmt.remove_exchanges:
            name, ex, line = find_exchange(spec, "remove")
            if getattr(ex, "is_quantitative_reference", False):
                raise BasicError(
                    f"'{name}' is the reference product of '{target}' and "
                    f"can't be removed. Delete the process instead.", line)
            if sum(1 for e in current if e.flow and e.flow.id == ex.flow.id) > 1:
                raise BasicError(
                    f"'{name}' appears more than once in '{target}', so "
                    f"EDIT can't remove just one of them yet.", line)
            remove_ids.append(ex.flow.id)

        # Updates
        updates = []
        for spec in stmt.update_exchanges:
            name, ex, line = find_exchange(spec, "update")
            upd = {"flow_id": ex.flow.id}
            if "amount" in spec:
                if self._expr_is_variable(spec["amount"]):
                    formula = self._expr_to_formula(spec["amount"])
                    for var_name in self._referenced_globals(formula):
                        self._sync_global(var_name, line)
                    upd["formula"] = formula
                else:
                    upd["amount"] = float(self._eval(spec["amount"]))
            if "formula" in spec:
                upd["formula"] = self._eval_str(spec["formula"])
            if "unit" in spec:
                upd["unit"] = spec["unit"]
            if "pedigree" in spec:
                ped = spec["pedigree"]
                upd["dq_entry"] = (ped if isinstance(ped, str)
                                   else "(" + ";".join(str(n) for n in ped) + ")")
            if "comment" in spec:
                upd["comment"] = self._eval_str(spec["comment"])
            if "provider" in spec:
                prov = self.bridge.resolve_process_strict(
                    self._eval_str(spec["provider"]))
                if "error" in prov:
                    raise BasicError(f"PROVIDER: {prov['error']}", line)
                upd["provider_id"] = prov["process_id"]
            if "location" in spec:
                # Same product, supplied from another location
                prov_name = (ex.default_provider.name
                             if ex.default_provider else name)
                match = self.bridge.find_process_qref_flow(
                    prov_name, self._eval_str(spec["location"]))
                if not match:
                    raise BasicError(f"No process '{prov_name}' to relink",
                                     line)
                if "error" in match:
                    raise BasicError(match["error"], line)
                if match["flow_id"] != ex.flow.id:
                    raise BasicError(
                        f"The '{prov_name}' at that location makes a "
                        f"different product, so it can't supply '{name}'",
                        line)
                upd["provider_id"] = match["process_id"]
            updates.append(upd)

        # Additions use exactly the same resolution as PROCESS
        folder = self.runtime.process_folder
        added = self._build_exchanges(stmt, folder, stmt.add_exchanges)
        for ex_dict in added:
            for var_name in self._referenced_globals(ex_dict.get("formula", "")):
                self._sync_global(var_name, stmt.line)

        add_params = []
        for let_stmt in stmt.add_params:
            val = self._eval(let_stmt.expr)
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise BasicError(f"Parameter '{let_stmt.name}' must be a "
                                 f"number", stmt.line)
            add_params.append({"name": let_stmt.name, "value": float(val)})
        upd_params = {}
        for pname, expr in stmt.update_params.items():
            upd_params[pname] = float(self._eval(expr))

        kwargs = {}
        if added:
            kwargs["add_exchanges"] = added
        if remove_ids:
            kwargs["remove_exchanges"] = remove_ids
        if updates:
            kwargs["update_exchanges"] = updates
        if add_params:
            kwargs["add_parameters"] = add_params
        if upd_params:
            kwargs["update_parameters"] = upd_params
        if stmt.set_description is not None:
            kwargs["description"] = self._eval_str(stmt.set_description)
        if stmt.set_category is not None:
            kwargs["category"] = self._eval_str(stmt.set_category)
        if stmt.set_location is not None:
            kwargs["location"] = self._eval_str(stmt.set_location)
        if not kwargs:
            print(f"  Nothing to change in '{target}'.")
            return

        result = self.bridge.edit_process(proc_id, **kwargs)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        changes = result.get("changes", [])
        warnings = [c for c in changes if str(c).startswith("WARNING")]
        print(f"  Edited process: {target}")
        for c in changes:
            if c not in warnings:
                print(f"    {c}")
        for w in warnings:
            print(f"  {w}")
        if (stmt.set_location is not None and
                not any("location set" in str(c) for c in changes)):
            print(f"  WARNING: location '{kwargs['location']}' wasn't found, "
                  f"so the location is unchanged.")
        if added or remove_ids or any("provider_id" in u for u in updates):
            print("  NOTE: product systems that already use this process "
                  "keep their old links. DELETE SYSTEM and SYSTEM again "
                  "to include these changes.")
        self.bridge.refresh_caches()

    def _exec_show(self, stmt: ShowStmt):
        """SHOW PROCESS/FLOW/PARAMETER with optional sub-command."""
        self._require_bridge(stmt.line)
        ref = self._eval_str(stmt.ref)
        sub = stmt.sub_command.upper()
        etype = stmt.entity_type.upper()

        if etype == "PROCESS":
            proc = self.bridge.resolve_process_strict(ref)
            if "error" in proc:
                raise BasicError(proc["error"], stmt.line)
            result = self.bridge.get_process_details(proc["process_id"])
            if "error" in result:
                raise BasicError(result["error"], stmt.line)

            if not sub:
                print(format_process_details(result))
            elif sub == "INPUTS":
                exchanges = result.get("exchanges", [])
                inputs = [e for e in exchanges if e.get("is_input")]
                if not inputs:
                    print(f"  {result.get('name', ref)}: no inputs")
                else:
                    print(f"  {result.get('name', ref)}: "
                          f"{len(inputs)} inputs")
                    headers = ["Flow", "Amount", "Unit", "Provider"]
                    rows = []
                    values = param_values_of(result)
                    for e in inputs:
                        amt = exchange_amount(e, values)
                        rows.append([
                            e.get("flow", "?"), amt,
                            e.get("unit", ""),
                            e.get("provider", "") or "",
                        ])
                    print(format_table(headers, rows,
                                       max_widths=[45, 30, 8, 30]))
            elif sub == "OUTPUTS":
                exchanges = result.get("exchanges", [])
                outputs = [e for e in exchanges if not e.get("is_input")]
                if not outputs:
                    print(f"  {result.get('name', ref)}: no outputs")
                else:
                    print(f"  {result.get('name', ref)}: "
                          f"{len(outputs)} outputs")
                    headers = ["Flow", "Amount", "Unit", "QRef"]
                    rows = []
                    values = param_values_of(result)
                    for e in outputs:
                        amt = exchange_amount(e, values)
                        qref = "*" if e.get("is_qref") else ""
                        rows.append([
                            e.get("flow", "?"), amt,
                            e.get("unit", ""), qref,
                        ])
                    print(format_table(headers, rows,
                                       max_widths=[45, 30, 8, 4]))
            elif sub == "LOCATION":
                print(f"  {result.get('location', '(none)')}")
            elif sub == "DESCRIPTION":
                desc = result.get("description", "(none)")
                print(f"  {desc}")
            elif sub == "PARAMS":
                params = result.get("parameters", [])
                if not params:
                    print(f"  {result.get('name', ref)}: no parameters")
                else:
                    headers = ["Name", "Value", "Formula"]
                    rows = [[p.get("name", "?"),
                             str(p.get("value", "")),
                             p.get("formula", "") or ""]
                            for p in params]
                    print(format_table(headers, rows))

        elif etype == "FLOW":
            found = self.bridge.find_flow(ref, "", "")
            if not found:
                raise BasicError(f"Flow not found: {ref}", stmt.line)
            if found.get("ambiguous"):
                raise BasicError(f"'{ref}' matches {found['ambiguous']} flows. "
                                 f"Give the exact name of the one you mean.",
                                 stmt.line)
            flow = self.bridge.get_flow_details(found["flow_id"])
            if "error" in flow:
                raise BasicError(flow["error"], stmt.line)
            if sub == "DESCRIPTION":
                print(f"  {flow['description'] or '(none)'}")
            else:
                print(format_flow_details(flow, units_only=(sub == "UNITS")))

        elif etype == "PARAMETER":
            result = self.bridge.get_global_parameters(ref)
            params = result.get("parameters", [])
            if not params:
                raise BasicError(f"Parameter not found: {ref}", stmt.line)
            exact = [q for q in params if q.get("name") == ref]
            if not exact and len(params) > 1:
                names = ", ".join(q.get("name", "?") for q in params[:10])
                raise BasicError(f"'{ref}' matches several parameters: "
                                 f"{names}", stmt.line)
            p = (exact or params)[0]
            if not sub or sub == "VALUE":
                name = p.get("name", "?")
                if p.get("formula"):
                    # openLCA stores 0 as the value of a formula parameter,
                    # so show the formula and olcaBASIC's current value
                    now = (self.runtime.get_var(name)
                           if self.runtime.has_var(name) else None)
                    now_txt = f"  (currently {_fmt_num(now)})" if now is not None else ""
                    print(f"  {name} = {p['formula']}{now_txt}")
                else:
                    print(f"  {name} = {_fmt_num(p.get('value', '?'))}")
            elif sub == "DESCRIPTION":
                print(f"  {p.get('description', '(none)')}")

    def _exec_link(self, stmt: LinkStmt):
        """LINK PROCESS "source" TO PROCESS "target" WITH amount, unit.
        Adds an input exchange to the target process using the source's
        output flow."""
        self._require_bridge(stmt.line)
        source_name = self._eval_str(stmt.source)
        target_name = self._eval_str(stmt.target)

        # Both ends must identify exactly one process
        src = self.bridge.resolve_process_strict(source_name)
        if "error" in src:
            raise BasicError(f"Source: {src['error']}", stmt.line)
        tgt = self.bridge.resolve_process_strict(target_name)
        if "error" in tgt:
            raise BasicError(f"Target: {tgt['error']}", stmt.line)

        # The source's reference flow is what the target takes in
        source_info = self.bridge.find_process_qref_flow(src["process_id"])
        if not source_info or "error" in source_info:
            raise BasicError(
                f"Source process '{source_name}' has no reference flow "
                f"to link", stmt.line)

        unit = stmt.unit or source_info.get("unit", "")
        exchange = {
            "flow_id": source_info["flow_id"],
            "unit": unit,
            "is_input": True,
            "provider_id": src["process_id"],
        }
        # Variables stay live as formulas, exactly as in PROCESS
        if stmt.amount is not None and self._expr_is_variable(stmt.amount):
            formula = self._expr_to_formula(stmt.amount)
            for var_name in self._referenced_globals(formula):
                self._sync_global(var_name, stmt.line)
            exchange["formula"] = formula
            amount = formula
        else:
            amount = float(self._eval(stmt.amount)) if stmt.amount else 1.0
            exchange["amount"] = amount

        # Add exchange to target
        result = self.bridge.edit_process(
            tgt["process_id"], add_exchanges=[exchange])

        if "error" in result:
            raise BasicError(result["error"], stmt.line)

        print(f"  Linked: {source_name} -> {target_name} "
              f"({amount} {unit})")

    def _active_folder(self) -> str:
        """Get the folder for the active navigation tree."""
        mode = self.runtime.navigation_mode
        return self.runtime.nav_folders.get(mode, "")

    def _set_active_folder(self, path: str):
        """Set the browsing folder for the active tree, saving previous.
        Browsing never changes where new processes and flows are built:
        only SET PROCESS FOLDER, SET FLOW FOLDER and CDIR do that."""
        mode = self.runtime.navigation_mode
        self.runtime.nav_previous[mode] = self.runtime.nav_folders[mode]
        self.runtime.nav_folders[mode] = path

    def _nav_entity_type(self) -> str:
        """Map navigation mode to entity type for list_category_contents."""
        mode = self.runtime.navigation_mode
        return {"PROCESSES": "PROCESSES", "FLOWS": "FLOWS",
                "METHODS": "", "SYSTEMS": "SYSTEMS"}.get(mode, "")

    def _exec_navigate(self, stmt: NavigateStmt):
        """NAVIGATE — switch browsing context."""
        if stmt.target:
            self.runtime.navigation_mode = stmt.target
            print(f"  Now browsing: {stmt.target.title()}")
        else:
            # Show menu
            modes = ["PROCESSES", "FLOWS", "METHODS", "SYSTEMS"]
            labels = ["Processes", "Flows", "Methods and parameters",
                      "Product systems"]
            print("  Browse:")
            for i, label in enumerate(labels, 1):
                marker = " *" if modes[i-1] == self.runtime.navigation_mode else ""
                print(f"    {i}. {label}{marker}")
            try:
                choice = input("\n  : ").strip()
                if choice.isdigit() and 1 <= int(choice) <= 4:
                    self.runtime.navigation_mode = modes[int(choice) - 1]
                    print(f"  Now browsing: {labels[int(choice) - 1]}")
                elif choice.upper() in modes:
                    self.runtime.navigation_mode = choice.upper()
                    print(f"  Now browsing: {choice.title()}")
            except (EOFError, KeyboardInterrupt):
                pass

    def _exec_cat(self, stmt):
        """CAT/LS — list category contents in the active tree."""
        self._require_bridge(stmt.line)
        if stmt.path:
            path = self._eval_str(stmt.path)
        else:
            path = self._active_folder()

        # Use entity_type from statement if given, otherwise from nav mode
        entity_type = stmt.entity_type or self._nav_entity_type()

        result = self.bridge.list_category_contents(path, entity_type)

        from fnmatch import fnmatch
        pattern = stmt.filter_pattern.lower() if stmt.filter_pattern else ""

        mode_label = self.runtime.navigation_mode.title()
        if pattern:
            print(f"  [{mode_label}] {result['path']}  "
                  f"(filter: {stmt.filter_pattern})")
        else:
            print(f"  [{mode_label}] {result['path']}")
        print()

        shown_folders = 0
        if result["subfolders"]:
            for sf in result["subfolders"]:
                last = sf.split("/")[-1]
                if pattern and not fnmatch(last.lower(), pattern):
                    continue
                print(f"    [DIR]  {last}/")
                shown_folders += 1

        shown_entities = 0
        if result["entities"]:
            for e in result["entities"]:
                if pattern and not fnmatch(e["name"].lower(), pattern):
                    continue
                tag = e["type"][0].upper()
                print(f"    [{tag}]    {e['name']}")
                shown_entities += 1

        if shown_folders == 0 and shown_entities == 0:
            if pattern:
                print(f"    No matches for {stmt.filter_pattern}")
            else:
                print("    (empty)")

        print()
        if pattern:
            print(f"  {shown_folders} folders, "
                  f"{shown_entities} entities (filtered)")
        else:
            print(f"  {result['subfolder_count']} folders, "
                  f"{result['entity_count']} entities")

    def _exec_dir_nav(self, stmt):
        """DIR "path" — navigate within the active tree."""
        if stmt.path is None:
            mode = self.runtime.navigation_mode
            folder = self._active_folder() or "(root)"
            print(f"  {mode.title()}: {folder}")
            return

        path = self._eval_str(stmt.path)

        if path == "/" or path == "":
            self._set_active_folder("")
        else:
            self._require_bridge(stmt.line)
            entity_type = self._nav_entity_type()
            current = self._active_folder()
            relative = (current.rstrip("/") + "/" + path) if current else path
            # Relative first (DIR "subfolder"), then absolute
            if current and self.bridge.folder_exists(relative, entity_type):
                self._set_active_folder(relative)
            elif self.bridge.folder_exists(path, entity_type):
                self._set_active_folder(path)
            else:
                # Don't invent a folder: that silently sends later
                # PROCESS and CDIR commands somewhere that isn't there
                raise BasicError(
                    f"Folder not found: '{path}'. Use CAT to list folders, "
                    f"or CDIR to create a new one.", stmt.line)

        folder = self._active_folder() or "(root)"
        print(f"  {folder}")

    def _exec_up(self):
        """UP — go up one level in the active tree."""
        current = self._active_folder()
        if "/" in current:
            self._set_active_folder(current.rsplit("/", 1)[0])
        else:
            self._set_active_folder("")
        folder = self._active_folder() or "(root)"
        print(f"  {folder}")

    def _exec_back(self):
        """BACK — toggle to previous folder in the active tree."""
        mode = self.runtime.navigation_mode
        prev = self.runtime.nav_previous.get(mode, "")
        self.runtime.nav_previous[mode] = self.runtime.nav_folders[mode]
        self.runtime.nav_folders[mode] = prev
        folder = prev or "(root)"
        print(f"  {folder}")

    def _exec_cdir(self, stmt):
        """CDIR — create and enter a folder in the active tree."""
        name = self._eval_str(stmt.name)
        current = self._active_folder()
        if current:
            new_path = current.rstrip("/") + "/" + name
        else:
            new_path = name
        self._set_active_folder(new_path)
        # A folder is created to put things in, so it becomes the
        # build folder for this tree
        mode = self.runtime.navigation_mode
        if mode == "FLOWS":
            self.runtime.flow_folder = new_path
            what = "New flows"
        else:
            self.runtime.previous_folder = self.runtime.process_folder
            self.runtime.process_folder = new_path
            what = "New processes"
        print(f"  Created and moved to: {new_path}")
        print(f"  {what} will be built here.")

    def _exec_tree(self, stmt: TreeStmt):
        """TREE: multi-level contribution tree for one impact category,
        with the pedigree scores on each branch's link."""
        self._require_bridge(stmt.line)
        system = self._eval_str(stmt.system)
        method = self._eval_str(stmt.method)
        if stmt.category is None:
            calc = self.bridge.calculate(system, method, stmt.allocation)
            if "error" in calc:
                raise BasicError(calc["error"], stmt.line)
            cats = ", ".join(i.get("category", "?") for i in calc.get("impacts", []))
            raise BasicError(f"TREE needs CATEGORY. Categories in "
                             f"{method}: {cats}", stmt.line)
        category = self._eval_str(stmt.category)
        print(f"  Building contribution tree: {system}...")
        result = self.bridge.upstream_tree(
            system, method, category, stmt.levels, stmt.top,
            stmt.allocation, stmt.with_quality)
        if "error" in result:
            extra = result.get("available")
            msg = result["error"] + (f". Available: {', '.join(extra)}" if extra else "")
            raise BasicError(msg, stmt.line)
        self.runtime.store_results(result, "tree")
        print(format_tree(result, stmt.with_quality))

    def _exec_move(self, stmt: MoveStmt):
        """MOVE PROCESS/FLOW/SYSTEM to a different folder."""
        self._require_bridge(stmt.line)
        ref = self._eval_str(stmt.ref)
        etype = stmt.entity_type.upper()

        if stmt.destination:
            dest = self._eval_str(stmt.destination)
        else:
            # MOVE ... TO FOLDER uses current SET folder
            if etype == "FLOW":
                dest = self.runtime.flow_folder
            else:
                dest = self.runtime.process_folder

        if not dest:
            raise BasicError(
                "No destination folder. Use MOVE ... TO \"path\" "
                "or SET PROCESS FOLDER first.", stmt.line)

        if etype == "PROCESS":
            # Strict: moving the wrong one of two same-named processes
            # could pull a background dataset out of its folder
            proc = self.bridge.resolve_process_strict(ref)
            if "error" in proc:
                raise BasicError(proc["error"], stmt.line)
            result = self.bridge.edit_process(
                proc["process_id"], category=dest)
            if "error" in result:
                raise BasicError(result["error"], stmt.line)
        else:
            raise BasicError(
                f"MOVE {etype} not yet supported. "
                f"Use MOVE PROCESS for now.", stmt.line)

        print(f"  Moved {etype.lower()} '{ref}' to '{dest}'")
        self.bridge.refresh_caches()

    def _exec_help(self, stmt):
        if stmt.topic:
            topic = stmt.topic.upper()
            topics = {
                "PROCESS": """
  PROCESS "name" [LOCATION "code"]
    FOLDER "path"
    OUTPUT NEW "flow", amount, unit, PRODUCT
    INPUT "existing process", amount, unit
    INPUT "process name", amount, unit LOCATION "GB"
    INPUT NEW "new flow", amount, unit
    OUTPUT "CO2", 5, kg TO AIR
    LET param = value
  END PROCESS

  INPUT without NEW finds the existing process/flow and
  wires it up as a provider automatically. If multiple
  processes share the same name, add LOCATION "code"
  to pick the right one.

  INPUT NEW creates a fresh flow (no provider link).
  OUTPUT NEW creates your foreground product.

  Elementary flows (TO AIR, TO WATER, TO SOIL, FROM NATURE)
  search the database by name and compartment. They never
  try to match a process. If not found, an error is raised
  because new elementary flows have no characterisation
  factors.""",
                "FOLDER": """
  SET PROCESS FOLDER "path"   Default folder for processes
  SET FLOW FOLDER "path"      Default folder for new flows
  DIR "folder"                Navigate into folder
  DIR                         Show current folders
  CAT                         List current folder contents
  CAT "path"                  List specific folder
  CAT FLOWS                   List flow categories
  UP                          Go up one level
  BACK                        Toggle to previous folder
  CDIR "name"                 Create and enter a folder""",
                "NEW": """
  The NEW keyword controls whether flows are created or found.

  INPUT "Portland cement; at plant", 300, kg
    Finds the existing process, uses its output flow,
    and sets it as default provider.

  INPUT NEW "My custom flow", 300, kg
    Creates a new flow (no provider link).

  OUTPUT NEW "My product", 1, m3, PRODUCT
    Creates a new foreground product flow.

  FLOW NEW "name", unit, type
    Creates a new flow outside a process.""",
                "SCENARIO": """
  SCENARIO "name"
    LET param = value
  END SCENARIO
  RUN SCENARIOS ON "system" USING "method" """,
                "SENSITIVITY": """
  SENSITIVITY ON "system" USING "method" BY 20%
    VARY param1
    VARY param2
  END SENSITIVITY""",
            }
            if topic in topics:
                print(topics[topic])
            else:
                print(f"  No help for: {stmt.topic}")
                print(f"  Try: HELP PROCESS, HELP FOLDER, HELP NEW, "
                      f"HELP SCENARIO, HELP SENSITIVITY")
        else:
            print("""
  olcaBASIC Commands:

  Navigation:
    DIR                           Show current folders
    DIR "folder"                  Navigate into folder
    CAT                           List current folder contents
    CAT "path"                    List specific folder
    CAT FLOWS                     List flow categories
    CAT PROCESSES                 List process categories
    UP                            Go up one level
    BACK                          Toggle to previous folder
    CDIR "name"                   Create and enter a folder
    SET PROCESS FOLDER "path"     Default process folder
    SET FLOW FOLDER "path"        Default flow folder

  Database:
    PRINT DATABASE              Database overview
    PRINT PROCESSES("search")   Search processes
    PRINT METHODS("search")     Search impact methods
    PRINT DETAILS("process")    Process details
    FIND PROCESS "search"       Find a process
    FIND CHEMICAL "name"        Chemical synonym lookup

  Parameters:
    LET name = value            Define a parameter

  Building:
    FLOW NEW "name", unit, type Create a new flow
    BRIDGE "name", unit         Create a bridge
    PROCESS "name"              Create a process
    SYSTEM "process"            Create a product system

  Exchanges (inside PROCESS):
    INPUT "name", amt, unit         Find existing flow/process
    INPUT NEW "name", amt, unit     Create a new flow
    OUTPUT NEW "name", 1, u, PRODUCT  New output (qref)

  Calculations:
    CALCULATE "sys" USING "method"
    CONTRIBUTION "sys" USING "method" TOP 10
    MONTECARLO "sys" USING "method" RUNS 1000

  Scenarios and sensitivity:
    SCENARIO "name" ... END SCENARIO
    RUN SCENARIOS ON "sys" USING "method"
    SENSITIVITY ON "sys" USING "method" BY 20%

  Output:
    PRINT RESULTS               Show last results
    SAVE RESULTS "file.csv"     Export to CSV

  Other:
    RUN "file.baslca"           Run a program file
    HELP [topic]                Help (PROCESS, FOLDER, NEW)
    EXIT                        Quit
""")
