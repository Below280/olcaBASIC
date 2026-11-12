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
from .output import OutputSink, PrintSink, NoInteraction
from .parser import parse, parse_line, ParseError
from .errors import BasicError, split_hint
from .enforce import EnforcementMixin, TIER_1_CAVEAT
from .workflows.epd import (
    EpdWorkflow, TAG_PREFIX, LOCATION_SWITCH, provenance_tags,
    provenance_documentation, tag_value,
)
from .formatting import (
    format_impacts, format_scenarios, format_sensitivity,
    format_processes, format_methods, format_systems,
    format_process_details, format_database_info, format_params,
    format_generic, format_flows, format_table, format_tree, results_to_csv,
    format_dq_systems, exchange_amount, param_values_of, format_flow_details,
)


# Commands about the program in memory: running them does not add to it.
PROGRAM_COMMANDS = (SaveProgramStmt, HelpStmt, LoadStmt, ListStmt,
                    RunMemoryStmt)

# A flow named by its UUID in place of its name (USE FLOW "uuid").
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}$")

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


class _QuietSink(OutputSink):
    """Swallows output during a look-up-only pass, keeping the line."""

    def __init__(self, real: OutputSink):
        self.real = real
        self.line = real.line
        self.interactive = real.interactive

    def write(self, text: str = "") -> None:
        pass

    def ask(self, prompt: str) -> str:
        return self.real.ask(prompt)


def _command_word(stmt) -> str:
    """CalculateStmt -> CALCULATE, RunScenariosStmt -> RUN SCENARIOS."""
    name = type(stmt).__name__
    for suffix in ("Stmt", "Def"):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).upper()


class Interpreter(EnforcementMixin):
    """Executes olcaBASIC AST nodes."""

    def __init__(self, bridge: Optional[LCABridge] = None,
                 out: Optional[OutputSink] = None,
                 runtime: Optional[Runtime] = None):
        self.bridge = bridge
        self.runtime = runtime or Runtime()
        self.out = out or PrintSink()      # where output goes
        self._stop_requested = False
        self._line = 0                     # line being executed
        self._command = ""                 # command word of that line

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
            self.out.write(f"Parse error: {e}")
            return

        self._stop_requested = False
        self._execute_block(statements)

    # ── Output helpers ───────────────────────────────────

    def _emit(self, call: str, result):
        """Hand a structured engine result to the sink (Session.run
        returns these as RunResult.data). Failures are reported as
        errors, not as data."""
        if isinstance(result, dict) and "error" in result:
            return
        self.out.data(self._command, call, result)

    def _ask(self, prompt: str, line: int = 0, hint: str = "") -> str:
        """Ask the person at the terminal. In a Session nobody is
        there, so the program has to say what it wants instead."""
        try:
            return self.out.ask(prompt)
        except NoInteraction:
            raise BasicError(
                "This needs an answer from the keyboard "
                f"({prompt.strip()}), and nobody is there to give one "
                "when a program runs through a Session.",
                line, hint=hint or "Run it in the olcaBASIC terminal, or "
                                   "give the value in the program.")

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
            self.out.write(f"  Error: {e}")
            return True

        failed = False
        for stmt in statements:
            if stmt is None:
                continue
            if isinstance(stmt, ExitStmt):
                return False
            try:
                self._execute(stmt)
            except BasicError as e:
                failed = True
                self.out.write(f"  Error: {e}")
            except RuntimeError as e:
                failed = True
                self.out.write(f"  Error: {e}")
            except Exception as e:
                failed = True
                self.out.write(f"  Error: {e}")
        if not failed and not all(isinstance(st, PROGRAM_COMMANDS)
                                  for st in statements):
            self.runtime.program_history.append(text)

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
        """Execute a single statement. An error raised without a line
        number (from deep inside an expression, say) gets the line of
        the statement, or of the line inside a block, being run."""
        outer = (self._line, self._command)
        self._line = stmt.line or self._line
        self._command = _command_word(stmt)
        self.out.line = self._line
        try:
            self._dispatch(stmt)
        except BasicError as e:
            if not e.line and self._line:
                raise e.at(self._line) from None
            raise
        finally:
            self._line, self._command = outer
            self.out.line = self._line

    def _at(self, line: int):
        """Note the line being worked on inside a block."""
        if line:
            self._line = line
            self.out.line = line

    def _dispatch(self, stmt: Statement):
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
            self.out.write(f"  {_fmt_num(val)}")

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

        elif isinstance(stmt, LoadStmt):
            self._exec_load(stmt)

        elif isinstance(stmt, ListStmt):
            self._exec_list(stmt)

        elif isinstance(stmt, RunMemoryStmt):
            self._exec_run_memory(stmt)

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
                self.out.write(f"  Flow folder set: {folder}")
            else:
                self.runtime.previous_folder = self.runtime.process_folder
                self.runtime.process_folder = folder
                self.out.write(f"  Process folder set: {folder}")

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
            self.out.write(f"  Browsing:         [{mode.title()}] {here}")
            self.out.write(f"  Build processes:  {pf}")
            self.out.write(f"  Build flows:      {ff}")

        elif isinstance(stmt, UpStmt):
            self._exec_up()

        elif isinstance(stmt, BackStmt):
            self._exec_back()

        elif isinstance(stmt, CdirStmt):
            self._exec_cdir(stmt)

        elif isinstance(stmt, MkdirStmt):
            self._exec_mkdir(stmt)

        elif isinstance(stmt, SaveProgramStmt):
            self._exec_save_program(stmt)

        elif isinstance(stmt, EpdStmt):
            EpdWorkflow.define(self, stmt)

        elif isinstance(stmt, ModuleStmt):
            self._require_bridge(stmt.line)
            self._require_epd(stmt.line, f"MODULE {stmt.code}").run_module(stmt)

        elif isinstance(stmt, EpdCommandStmt):
            self._exec_epd_command(stmt)

        elif isinstance(stmt, NewFromTemplateStmt):
            self._exec_new_from_template(stmt)

        elif isinstance(stmt, ParameteriseStmt):
            self._exec_parameterise(stmt)

        elif isinstance(stmt, ClearStmt):
            self.out.clear_screen()

        elif isinstance(stmt, RefreshStmt):
            if self.bridge:
                self.bridge.refresh_caches()
                self.out.write("  Caches cleared.")

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
        response = self._ask(f"  {stmt.prompt} ", stmt.line)
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
                "Not connected to openLCA.", line,
                hint="Open a database in openLCA, start the IPC server "
                     "(Tools > Developer Tools > IPC Server), then run "
                     "this again.")

    def _exec_print(self, stmt: PrintStmt):
        sub = stmt.sub_command.upper()

        if sub == "DATABASE":
            self._require_bridge(stmt.line)
            result = self.bridge.database_info()
            self._emit("database_info", result)
            self.out.write(format_database_info(result))

        elif sub == "PROCESSES":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            term = args[0] if len(args) > 0 else ""
            cat = args[1] if len(args) > 1 else ""
            loc = args[2] if len(args) > 2 else ""
            result = self.bridge.search_processes(term, cat, loc)
            self._emit("search_processes", result)
            self.out.write(format_processes(result))

        elif sub == "METHODS":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            term = args[0] if args else ""
            result = self.bridge.list_methods(term)
            self._emit("list_methods", result)
            self.out.write(format_methods(result))

        elif sub == "SYSTEMS":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            term = args[0] if args else ""
            result = self.bridge.list_systems(term)
            self._emit("list_systems", result)
            self.out.write(format_systems(result))

        elif sub == "PARAMS":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            ref = args[0] if args else ""
            result = self.bridge.get_system_parameters(ref)
            self._emit("get_system_parameters", result)
            self.out.write(format_params(result))

        elif sub == "GLOBAL_PARAMS":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            filt = args[0] if args else ""
            result = self.bridge.get_global_parameters(filt)
            self._emit("get_global_parameters", result)
            self.out.write(format_params(result))

        elif sub == "DETAILS":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            ref = args[0] if args else ""
            proc = self.bridge.resolve_process_strict(ref)
            if "error" in proc:
                raise BasicError(proc["error"], stmt.line)
            result = self.bridge.get_process_details(proc["process_id"])
            self._emit("get_process_details", result)
            self.out.write(format_process_details(result))

        elif sub == "QUALITY":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            ref = args[0] if args else ""
            result = self.bridge.get_data_quality(ref)
            self._emit("get_data_quality", result)
            self.out.write(format_generic(result))

        elif sub == "LINKS":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            ref = args[0] if args else ""
            filt = args[1] if len(args) > 1 else ""
            result = self.bridge.get_system_links(ref, filt)
            self._emit("get_system_links", result)
            self.out.write(format_generic(result))

        elif sub == "UNITS":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            name = args[0] if args else ""
            result = self.bridge.find_unit(name)
            self._emit("find_unit", result)
            self.out.write(format_generic(result))

        elif sub == "DQ_SYSTEMS":
            self._require_bridge(stmt.line)
            result = self.bridge.list_dq_systems()
            self._emit("list_dq_systems", result)
            if "error" in result:
                raise BasicError(result["error"], stmt.line)
            self.out.write(format_dq_systems(result))

        elif sub == "FAMILY":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            family = args[0] if args else ""
            result = self.bridge.set_database_family(family)
            self._emit("set_database_family", result)
            self.out.write(format_generic(result))

        elif sub == "EXPR":
            # Multiple comma-separated expressions
            vals = [self._eval(a) for a in stmt.args]
            self.out.write("  " + "  ".join(_fmt_num(v) for v in vals))

        else:
            self.out.write(f"  Unknown PRINT sub-command: {sub}")

    def _exec_print_results(self):
        results = self.runtime.last_results
        if not results:
            self.out.write("  No results to display. Run a calculation first.")
            return

        rtype = self.runtime.last_results_type
        if rtype == "calculate":
            self.out.write(format_impacts(results))
        elif rtype == "scenarios":
            self.out.write(format_scenarios(results))
        elif rtype == "sensitivity":
            self.out.write(format_sensitivity(results))
        else:
            self.out.write(format_generic(results))

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
            self._require_family(stmt.line, "MAKE FLOW")
            result = self.bridge.create_flow(name, stmt.unit, folder, ft)
            self._emit("create_flow", result)
            if "error" in result:
                raise BasicError(result["error"], stmt.line)
            existed = result.get("already_existed", False)
            status = "exists" if existed else "created"
            self.out.write(f"  Flow {status}: {name} ({stmt.unit}, {ft})")
        else:
            # Default: find existing
            found = self.bridge.find_flow(
                name, stmt.unit, search_cat, strict=bool(search_cat))
            if found:
                self.out.write(f"  Flow found: {found['flow_name']}")
            else:
                # Not found: create it
                self._require_family(stmt.line, "FLOW")
                result = self.bridge.create_flow(name, stmt.unit, folder, ft)
                self._emit("create_flow", result)
                if "error" in result:
                    raise BasicError(result["error"], stmt.line)
                self.out.write(f"  Flow created: {name} ({stmt.unit}, {ft})")

    def _exec_bridge(self, stmt: BridgeStmt):
        self._require_bridge(stmt.line)
        given = self._eval_str(stmt.name)
        name = self._bridge_name(given, stmt.unit, stmt.line)
        epd = self.runtime.epd
        if stmt.folder:
            folder = self._eval_str(stmt.folder)
        elif epd is not None:
            folder = epd.bridges_folder     # the EPD keeps its bridges together
        else:
            folder = self.runtime.process_folder
        self._require_family(stmt.line, "BRIDGE")
        if stmt.electricity and stmt.country is None:
            raise BasicError(
                f"ELECTRICITY {stmt.electricity} needs the country the "
                f"electricity is used in.", stmt.line,
                hint='Add COUNTRY "code" inside the block, for example '
                     'COUNTRY "GB".')
        if not stmt.electricity and (stmt.country is not None
                                     or stmt.region is not None
                                     or stmt.energy_source is not None
                                     or stmt.location_based_provider is not None):
            raise BasicError(
                "COUNTRY, REGION, ENERGY SOURCE and LOCATION BASED PROVIDER "
                "describe an electricity bridge, and this one has no "
                "ELECTRICITY line.", stmt.line,
                hint="Add ELECTRICITY CONTRACT, ELECTRICITY RESIDUAL or "
                     "ELECTRICITY CONSUMPTION.")
        if stmt.location_based_provider is not None and \
                stmt.electricity == "CONSUMPTION":
            raise BasicError(
                "A consumption-mix bridge is location-based already, so it "
                "takes no LOCATION BASED PROVIDER.", stmt.line,
                hint="Remove the LOCATION BASED PROVIDER line.")
        # A bridge made before 0.4.0 may carry the plain name: reuse it
        # rather than building a second one beside it.
        if name != given:
            old = [c for c in self.bridge.process_candidates(given)
                   if not folder or folder in c["category"]]
            if old:
                self.out.write(
                    f"  NOTE: a bridge called '{given}' already exists and "
                    f"is reused. New bridges are named '{name}'.")
                name = given
        provider_id = None

        if stmt.provider:
            prov_str = self._eval_str(stmt.provider)
            prov = self.bridge.resolve_process_strict(prov_str)
            if "error" in prov:
                raise BasicError(prov["error"], stmt.line)
            provider_id = prov["process_id"]

        second_id = None
        if stmt.location_based_provider is not None:
            prov = self.bridge.resolve_process_strict(
                self._eval_str(stmt.location_based_provider))
            if "error" in prov:
                raise BasicError(f"LOCATION BASED PROVIDER: {prov['error']}",
                                 stmt.line)
            second_id = prov["process_id"]
        if epd is not None:
            info = (self.bridge.describe_process(provider_id)
                    if provider_id else None)
            epd.check_bridge(stmt, name, info["name"] if info else "")

        provider_flow_id = None
        if stmt.provider_flow:
            provider_flow_id = self._eval_str(stmt.provider_flow)

        result = self.bridge.create_bridge(
            name, stmt.unit, folder, provider_id,
            provider_flow_id, stmt.is_waste)
        self._emit("create_bridge", result)

        if "error" in result:
            raise BasicError(result["error"], stmt.line)

        existed = result.get("already_existed", False)
        status = "exists" if existed else "created"
        self.out.write(f"  Bridge {status}: {name} ({stmt.unit})")
        if result.get("note"):
            self.out.write(f"  NOTE: this bridge has no provider yet. Add "
                           f"PROVIDER \"process name or uuid\" to the BRIDGE "
                           f"block, or it supplies nothing.")
        if result.get("warning"):
            self.out.write(f"  WARNING: {result['warning']}")

        # What the block declares about the data and the electricity
        tags = provenance_tags(stmt.provenance, self._eval_str)
        if stmt.electricity:
            tags["electricity"] = stmt.electricity
            tags["country"] = tag_value(self._eval_str(stmt.country)).upper()
            tags["region"] = (tag_value(self._eval_str(stmt.region))
                              if stmt.region is not None else None)
            tags["energy_source"] = (
                tag_value(self._eval_str(stmt.energy_source))
                if stmt.energy_source is not None else None)
        if second_id:
            done = self.bridge.set_switched_provider(
                result["process_id"], second_id, LOCATION_SWITCH)
            if "error" in done:
                raise BasicError(f"LOCATION BASED PROVIDER: {done['error']}",
                                 stmt.line)
            tags["switch"] = LOCATION_SWITCH
            if not done.get("already_set"):
                self.out.write(
                    f"  Location-based provider set. The bridge uses it "
                    f"when the global parameter {LOCATION_SWITCH} is 1 "
                    f"(EPD REPORT ... LOCATION BASED does that).")
        if tags or epd is not None:
            tags["role"] = "bridge"
            done = self.bridge.set_process_tags(
                result["process_id"], tags, TAG_PREFIX,
                provenance_documentation(stmt.provenance))
            if "error" in done:
                raise BasicError(done["error"], stmt.line)
            if existed and (stmt.provenance or stmt.electricity):
                self.out.write("  Declarations on the bridge updated.")
        if epd is not None:
            epd._reset_progress()

    def _exec_process(self, stmt: ProcessStmt):
        self._require_bridge(stmt.line)
        name = self._eval_str(stmt.name)
        folder = self._eval_str(stmt.folder) if stmt.folder else self.runtime.process_folder
        description = self._eval_str(stmt.description) if stmt.description else ""
        location = self._eval_str(stmt.location) if stmt.location else None
        flow_schema = self._eval_str(stmt.flow_schema) if stmt.flow_schema else None
        process_schema = self._eval_str(stmt.process_schema) if stmt.process_schema else None
        epd = self.runtime.epd if self.runtime.epd_module else None
        if epd is not None:
            name, folder = epd.begin_process(stmt, name)

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
        self._flows_made = []
        self._direct_background = []
        self._last_created = None
        try:
            done = self._exec_process_body(stmt, name, folder, description,
                                           location, flow_schema,
                                           process_schema, ex_list)
            self._lint_direct_background()
            created = self._last_created
            if epd is not None:
                epd.end_process(stmt, created)
            elif created and not created.get("already_existed"):
                self._declare(created["process_id"], stmt)
            return done
        except BasicError as e:
            self._direct_background = None
            if self._flows_made:
                made = ", ".join(f'"{n}"' for n in self._flows_made)
                note = (f"The process was not created. Flows this block "
                        f"had already created stay in the database "
                        f"({made}); running the block again reuses them.")
                raise BasicError(e.message, e.line or stmt.line,
                                 hint=f"{e.hint} {note}".strip()) from None
            raise

    def _exec_process_body(self, stmt, name, folder, description, location,
                           flow_schema, process_schema, ex_list):
        self.runtime.push_scope()
        try:
            for let_stmt in stmt.local_params:
                self._at(let_stmt.line)
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
                    let_stmt.line or stmt.line)
            parameters.append({"name": let_stmt.name, "value": float(val)})
            param_names.add(let_stmt.name)

        # Top-level variables used in exchange formulas become openLCA
        # GLOBAL parameters (not per-process copies), so a variable
        # shared by several processes is one parameter, and scenarios
        # and sensitivity change it everywhere. Local LETs above stay
        # process-scope and take precedence inside this process.
        ex_lines = [ex.line or stmt.line for ex in ex_list]
        for ex_dict, ex_line in zip(exchanges, ex_lines):
            formula = ex_dict.get("formula", "")
            if formula:
                self._at(ex_line)
                for var_name in self._referenced_globals(formula):
                    if var_name not in param_names:
                        self._sync_global(var_name, ex_line)
        self._at(stmt.line)

        return self._create_process(
            stmt, name, folder, exchanges, parameters, description,
            location, flow_schema, process_schema, ex_lines=ex_lines,
            param_lines=[l.line or stmt.line for l in stmt.local_params])

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
            self._emit("create_global_parameter", result)
        else:
            result = self.bridge.create_global_parameter(
                name, value=desired[1])
            self._emit("create_global_parameter", result)
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
            self.out.write(f"  NOTE: global parameter '{name}' already existed "
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
        """Resolve the exchanges of a PROCESS or EDIT block.

        Done twice: a first pass that looks everything up but creates
        nothing, so a wrong name on any line stops the block before a
        single flow is written; then the real pass."""
        if any(ex.is_new or not ex.direction_compartment for ex in ex_list):
            real_out, self.out = self.out, _QuietSink(self.out)
            try:
                self._resolve_exchanges(stmt, folder, ex_list, check_only=True)
            finally:
                self.out = real_out
        return self._resolve_exchanges(stmt, folder, ex_list)

    def _resolve_exchanges(self, stmt, folder: str, ex_list: list,
                           check_only: bool = False) -> list:
        exchanges = []
        for ex in ex_list:
            # errors below report this exchange's own line
            line = ex.line or stmt.line
            self._at(line)
            if (ex.legacy_new and not check_only
                    and "NEW" not in self.runtime.deprecation_shown):
                self.runtime.deprecation_shown.add("NEW")
                self.out.write("  NOTE: INPUT NEW and OUTPUT NEW are deprecated. Use "
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

            if ex.is_new and check_only:
                self._require_family(line, "MAKE FLOW")
                flow_id = "(to be created)"

            elif ex.is_new:
                # NEW keyword: always create a fresh flow
                flow_result = self.bridge.create_flow(
                    flow_name, unit, category, flow_type)
                if "error" in flow_result:
                    raise BasicError(
                        f"Flow '{flow_name}': {flow_result['error']}",
                        line)
                flow_id = flow_result["flow_id"]
                if not flow_result.get("already_existed"):
                    self._made_flow(flow_name)

            elif ex.direction_compartment:
                # Elementary flow (TO AIR, TO WATER, etc.)
                # Never try process lookup; search flows by category
                flow_match = self.bridge.find_flow(
                    flow_name, unit, search_cats, strict=True)
                if flow_match:
                    flow_id = flow_match["flow_id"]
                    if flow_match.get("ambiguous"):
                        self.out.write(f"  NOTE: '{flow_name}' exists in "
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
                        line)

            else:
                # Product/waste flow: find existing process or flow.
                # USE FLOW skips the process lookup; USE PROCESS
                # insists on one (it's how you get a provider).
                location_filter = (self._eval_str(ex.location)
                                   if ex.location else "")
                flow_folder = (self._eval_str(ex.flow_folder)
                               if ex.flow_folder else "")
                if flow_folder and ex.use_type != "FLOW":
                    raise BasicError(
                        "FOLDER picks between flows, so it goes with "
                        "USE FLOW", line,
                        hint=("Write INPUT USE FLOW \"name\", amount, unit "
                              "FOLDER \"path\". To pick between processes "
                              "use LOCATION or PROVIDER."))
                if ex.use_type == "FLOW":
                    if location_filter:
                        raise BasicError(
                            "LOCATION picks between processes, so it "
                            "can't be used with USE FLOW", line)
                    proc_match = None
                else:
                    proc_match = self.bridge.find_process_qref_flow(
                        flow_name, location_filter)
                if proc_match and "error" in proc_match:
                    raise BasicError(proc_match["error"], line)
                if not proc_match and ex.use_type == "PROCESS":
                    raise BasicError(
                        f"No process found matching '{flow_name}'. "
                        f"FIND PROCESS shows the names in your database, "
                        f"or use USE FLOW to link a flow without a "
                        f"provider.", line)
                if proc_match:
                    flow_id = proc_match["flow_id"]
                    provider_id = proc_match["process_id"]
                    if proc_match.get("ambiguous") and not ex.provider:
                        # Never pick between same-named processes
                        self._ambiguous_process(
                            proc_match["process_name"], location_filter,
                            line, self.bridge.process_candidates(
                                proc_match["process_name"], location_filter))
                    if not ex.provider:
                        self._note_provider(provider_id, folder, line,
                                            check_only)
                else:
                    # Try to find a flow by name directly: a UUID,
                    # then FOLDER if given, then by name.
                    flow_match = (self.bridge.flow_by_id(flow_name)
                                  if _UUID_RE.match(flow_name) else None)
                    if flow_match:
                        pass
                    elif flow_folder:
                        flow_match = self.bridge.find_flow_in_folder(
                            flow_name, flow_folder)
                        if "error" in flow_match:
                            raise BasicError(
                                flow_match["error"], line,
                                hint=(f"FIND FLOW \"{flow_name}\" shows "
                                      f"which folders it is in."))
                    else:
                        flow_match = self.bridge.find_flow(
                            flow_name, unit, category)
                    if flow_match and flow_match.get("ambiguous"):
                        # Never pick between same-named flows
                        scope = flow_folder
                        cands = self.bridge.flow_candidates(
                            flow_name, flow_folder)
                        if not flow_folder and category:
                            local = self.bridge.flow_candidates(
                                flow_name, category)
                            if len(local) > 1:
                                cands, scope = local, category
                        self._ambiguous_flow(flow_name, scope, line, cands)
                    if flow_match and location_filter:
                        raise BasicError(
                            f"LOCATION was given, but '{flow_name}' "
                            f"matched a flow rather than a process, so "
                            f"there is no provider to choose between",
                            line)
                    if flow_match:
                        flow_id = flow_match["flow_id"]
                    else:
                        # Nothing found
                        if ex.direction == "INPUT":
                            raise BasicError(
                                f"No process or flow found matching "
                                f"'{flow_name}'. Check the spelling, "
                                f"or use INPUT MAKE FLOW to create a "
                                f"new flow.",
                                line)
                        elif check_only:
                            self._require_family(line, "a new output flow")
                            flow_id = "(to be created)"
                        else:
                            self.out.write(f"  NOTE: Creating new flow "
                                  f"'{flow_name}' (use OUTPUT NEW to "
                                  f"suppress this message)")
                            flow_result = self.bridge.create_flow(
                                flow_name, unit, category, flow_type)
                            if "error" in flow_result:
                                raise BasicError(
                                    f"Flow '{flow_name}': "
                                    f"{flow_result['error']}",
                                    line)
                            flow_id = flow_result["flow_id"]
                            if not flow_result.get("already_existed"):
                                self._made_flow(flow_name)

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
                                     line)
                ex_dict["provider_id"] = prov["process_id"]
                self._note_provider(prov["process_id"], folder, line,
                                    check_only)

            exchanges.append(ex_dict)
        return exchanges

    def _note_provider(self, provider_id: str, folder: str, line: int,
                       check_only: bool):
        """Keep count of background processes used directly, for the
        lint note at the end of the block. (Inside an EPD module this
        is an error: see workflows/epd.py.)"""
        info = self.bridge.describe_process(provider_id)
        if info is None:
            return
        own = (folder or self.runtime.process_folder or "").split("/")[0].lower()
        mine = bool(own) and info["category"].lower().split("/")[0] == own
        bridged = self._is_bridge(info["name"], info["category"])
        epd = getattr(self.runtime, "epd", None)
        if epd is not None and self.runtime.epd_module:
            epd.check_provider(info, line)
        if check_only or mine or bridged or not own:
            return
        direct = getattr(self, "_direct_background", None)
        if direct is not None and info["name"] not in direct:
            direct.append(info["name"])

    def _lint_direct_background(self):
        direct = getattr(self, "_direct_background", None) or []
        self._direct_background = None
        if not direct:
            return
        n = len(direct)
        self.out.write(
            f"  NOTE: {n} input{'s use' if n > 1 else ' uses'} a background "
            f"process directly. A BRIDGE keeps each background choice in "
            f"one place, so it can be swapped without editing every "
            f"process (HELP BRIDGE).")

    @staticmethod
    def _engine_error_line(message: str, ex_lines, param_lines, default: int) -> int:
        """The engine numbers the exchange or parameter it objects to
        ("Exchange 2: ..."). Turn that into the line it was written on."""
        m = re.match(r"(Exchange|Parameter) (\d+)\b", message or "")
        if m:
            lines = ex_lines if m.group(1) == "Exchange" else param_lines
            index = int(m.group(2))
            if lines and 0 <= index < len(lines):
                return lines[index]
        return default

    def _made_flow(self, name: str):
        made = getattr(self, "_flows_made", None)
        if made is not None and name not in made:
            made.append(name)

    def _create_process(self, stmt, name, folder, exchanges, parameters,
                        description, location, flow_schema,
                        process_schema, ex_lines=None, param_lines=None):
        result = self.bridge.create_process(
            name, folder, exchanges, parameters or None,
            description, location, flow_schema, process_schema)
        self._emit("create_process", result)

        if "error" in result:
            # Put the engine's wording into olcaBASIC terms
            msg = result["error"].replace(
                "Set flow_schema.",
                'Add a FLOW SCHEMA "name" line to the PROCESS block '
                '(PRINT DQ SYSTEMS lists the names).')
            raise BasicError(msg, self._engine_error_line(
                result["error"], ex_lines, param_lines, stmt.line))

        self._last_created = result
        if result.get("already_existed", False):
            where = folder or "(root)"
            self.out.write(f"  WARNING: process '{name}' already exists in {where}. "
                  f"It was NOT changed, so the exchanges above were not "
                  f"applied. DELETE PROCESS \"{name}\" first to rebuild it.")
            return
        ex_count = result.get("exchange_count", 0)
        p_count = result.get("parameter_count", 0)
        self.out.write(f"  Process created: {name} "
              f"({ex_count} exchanges, {p_count} parameters)")

    def _declare(self, process_id: str, stmt) -> bool:
        """Store what the DATA and CONTROL lines of a PROCESS or EDIT
        block declare, as tags on the process. True if there were any."""
        tags = provenance_tags(stmt.provenance, self._eval_str)
        if stmt.control:
            tags["control"] = stmt.control
        if not tags:
            return False
        done = self.bridge.set_process_tags(
            process_id, tags, TAG_PREFIX,
            provenance_documentation(stmt.provenance))
        if "error" in done:
            raise BasicError(done["error"], stmt.line)
        return True

    # ── EPD workflow ─────────────────────────────────────

    def _require_epd(self, line: int, command: str):
        epd = self.runtime.epd
        if epd is None:
            raise BasicError(
                f"{command} needs an EPD, and none is defined in this "
                f"session.", line,
                hint='Define one first: EPD "name" ... END EPD. HELP EPD '
                     'shows the block, and NEW FROM TEMPLATE '
                     '"epd_skeleton" AS "my_epd.baslca" writes a starting '
                     'point.')
        return epd

    def _exec_epd_command(self, stmt):
        command = stmt.command
        if command == "CLOSE":
            if self.runtime.epd is None:
                self.out.write("  No EPD is active.")
            else:
                self.out.write(f"  EPD '{self.runtime.epd.name}' closed. "
                               f"What it built stays in the database.")
            self.runtime.epd = None
            self.runtime.epd_module = ""
            return
        if command == "STATUS" and self.runtime.epd is None:
            self.out.write("  No EPD is active. EPD \"name\" ... END EPD "
                           "defines one.")
            return
        self._require_bridge(stmt.line)
        epd = self._require_epd(stmt.line, f"EPD {command}")
        if self.runtime.epd_module:
            raise BasicError(
                f"EPD {command} cannot run inside MODULE "
                f"{self.runtime.epd_module}.", stmt.line,
                hint="Close the module with END MODULE first.")
        if command == "SYSTEMS":
            epd.systems(stmt.line)
        elif command == "CHECK":
            epd.check(stmt.line, stmt.skip,
                      self._eval_str(stmt.argument) if stmt.skip else "")
        elif command == "CALCULATE":
            epd.calculate(stmt.line)
        elif command == "DATA QUALITY":
            epd.data_quality(stmt.line)
        elif command == "REPORT":
            epd.report(stmt.line, self._eval_str(stmt.argument),
                       stmt.location_based)
        elif command == "STATUS":
            epd.status()

    BACKUP_WARNING = (
        "This changes the process in the database for good. It cannot be "
        "undone without restoring a backup of the database.")

    ALL_NEEDS_A_PERSON = (
        "PARAMETERISE ... ALL asks twice before it writes anything, so it "
        "only runs in the olcaBASIC terminal with a person there to "
        "answer. Without ALL, elementary flows are left alone and CONFIRM "
        "is enough.")

    def _confirm_parameterise_all(self, name: str, n: int, elementary: int,
                                  line: int):
        """ALL rewrites every fixed amount, emissions and resources
        included. It asks twice, and only a person can answer: in a
        Session (and so through the MCP) it is refused."""
        self.out.write(
            f"  PARAMETERISE ... ALL will replace {n} fixed amounts in "
            f"'{name}' with parameters, {elementary} of them elementary "
            f"flows (emissions and resources).")
        self.out.write(f"  {self.BACKUP_WARNING}")
        first = self._ask("  Are you sure? Type YES to go on: ", line,
                          self.ALL_NEEDS_A_PERSON)
        if first.strip().upper() != "YES":
            raise BasicError("PARAMETERISE ... ALL cancelled. Nothing was "
                             "changed.", line)
        self.out.write(
            f"  All {n} amounts will be rewritten in the database, and "
            f"there is no going back without a backup.")
        second = self._ask("  Are you really sure? Type PARAMETERISE to go "
                           "ahead: ", line, self.ALL_NEEDS_A_PERSON)
        if second.strip().upper() not in ("PARAMETERISE", "PARAMETERIZE"):
            raise BasicError("PARAMETERISE ... ALL cancelled. Nothing was "
                             "changed.", line)

    def _exec_parameterise(self, stmt):
        """PARAMETERISE PROCESS "name" CONFIRM: turn the fixed amounts
        of a process into parameters. Refused without CONFIRM."""
        self._require_bridge(stmt.line)
        ref = self._eval_str(stmt.target)
        location = self._eval_str(stmt.location) if stmt.location else ""
        candidates = self.bridge.process_candidates(ref, location)
        if len(candidates) > 1:
            self._ambiguous_process(ref, location, stmt.line, candidates)
        if candidates:
            process_id, name = candidates[0]["id"], candidates[0]["name"]
        else:
            found = self.bridge.describe_process(ref)       # a UUID
            if found is None:
                where = f" at LOCATION \"{location}\"" if location else ""
                raise BasicError(
                    f"No process is called '{ref}'{where}.", stmt.line,
                    hint=f"Give the full name or the UUID. FIND PROCESS "
                         f"\"{ref}\" lists what matches.")
            process_id, name = found["id"], found["name"]

        plan = self.bridge.parameterise_process(process_id, True,
                                                stmt.all_flows)
        if "error" in plan:
            raise BasicError(plan["error"], stmt.line)
        n = plan["parameterised"]
        if n == 0:
            kinds = ("exchange" if stmt.all_flows
                     else "product or waste exchange")
            self.out.write(f"  Nothing to parameterise in '{name}': it has no "
                           f"{kinds} with a fixed amount.")
            return
        amounts = f"{n} fixed amount{'s' if n != 1 else ''}"
        if not stmt.confirm:
            location_part = f' LOCATION "{location}"' if location else ""
            all_part = " ALL" if stmt.all_flows else ""
            raise BasicError(
                f"PARAMETERISE PROCESS refused without CONFIRM. It would "
                f"replace {amounts} in '{name}' with parameters. "
                f"{self.BACKUP_WARNING}", stmt.line,
                hint=f"Back up the database in openLCA first. Then: "
                     f"PARAMETERISE PROCESS \"{ref}\"{location_part}"
                     f"{all_part} CONFIRM")
        if stmt.all_flows:
            elementary = sum(1 for p in plan["parameters"]
                             if p.get("elementary"))
            self._confirm_parameterise_all(name, n, elementary, stmt.line)
        self.out.write(f"  WARNING: {self.BACKUP_WARNING}")
        result = self.bridge.parameterise_process(process_id, False,
                                                  stmt.all_flows)
        self._emit("parameterise_process", result)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        self.out.write(f"  Parameterised: {name}")
        self.out.write(f"  {amounts} replaced with parameters. Each "
                       f"parameter holds the amount it replaced, so results "
                       f"are unchanged until one is varied.")
        for p in result["parameters"][:20]:
            self.out.write(f"    {p['name']} = {_fmt_num(p['value'])} "
                           f"({p['flow']}, {p['unit']})")
        if n > 20:
            self.out.write(f"    ... and {n - 20} more (SHOW PROCESS "
                           f"\"{name}\" PARAMS lists them all)")
        left = []
        if result["already_formula"]:
            left.append(f"{result['already_formula']} already had a formula")
        if result["elementary_left"]:
            left.append(f"{result['elementary_left']} elementary flows are "
                        f"left as fixed amounts")
        if left:
            self.out.write("  Not changed: " + "; ".join(left) + ".")
        self.bridge.refresh_caches()

    def _exec_new_from_template(self, stmt):
        """NEW FROM TEMPLATE "name" AS "file": copy a template that
        ships with olcaBASIC into the working folder."""
        from . import templates
        name = self._eval_str(stmt.template).strip()
        target = self._eval_str(stmt.filename).strip()
        source = templates.read(name)
        if source is None:
            raise BasicError(
                f"There is no template called '{name}'.", stmt.line,
                hint="Templates: " + ", ".join(
                    f'"{n}"' for n in templates.names()) + ".")
        if not target:
            raise BasicError("NEW FROM TEMPLATE needs a file name after AS.",
                             stmt.line)
        if "." not in os.path.basename(target):
            target += ".baslca"
        if os.path.exists(target):
            raise BasicError(
                f"'{target}' already exists, and NEW FROM TEMPLATE does "
                f"not write over a file.", stmt.line,
                hint="Choose another name, or remove the file first.")
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(source)
        self.out.write(f"  Template '{name}' copied to {target}")
        self.out.write(f"  Edit it, then: RUN \"{target}\"")

    def _exec_system(self, stmt: SystemStmt):
        self._require_bridge(stmt.line)
        proc_ref = self._eval_str(stmt.process_ref)
        folder = self._eval_str(stmt.folder) if stmt.folder else None
        linking = stmt.linking.lower()
        target_amount = float(self._eval(stmt.target_amount)) if stmt.target_amount else 1.0
        target_unit = stmt.target_unit or None
        target_prop = self._eval_str(stmt.target_property) if stmt.target_property else None

        self._defaults(stmt)
        self.out.write(f"  Creating product system from: {proc_ref}...")
        result = self.bridge.create_system(
            proc_ref, linking, target_amount, target_unit,
            target_prop, folder)
        self._emit("create_system", result)

        if "error" in result:
            if result.get("partial"):
                # openLCA made the system but the engine could not
                # finish setting it up
                raise BasicError(
                    f"The product system for '{proc_ref}' was created, but "
                    f"setting it up did not finish ({result['error']}).",
                    stmt.line,
                    hint=f"Run VALIDATE \"{proc_ref}\" to see what state "
                         f"it is in. If it is not usable: DELETE SYSTEM "
                         f"\"{proc_ref}\", then SYSTEM \"{proc_ref}\" "
                         f"again.")
            raise BasicError(result["error"], stmt.line)

        sys_name = result.get("system_name", proc_ref)
        if result.get("already_existed", False):
            self.out.write(f"  WARNING: product system '{sys_name}' already exists "
                  f"and was reused as it is. If the process changed, "
                  f"DELETE SYSTEM \"{sys_name}\" first to rebuild it. "
                  f"VALIDATE \"{sys_name}\" checks the one that is there.")
        else:
            self.out.write(f"  System created: {sys_name}")
            self._forget_validation(result.get("system_id", ""))
        if result.get("warnings"):
            for w in result["warnings"]:
                self.out.write(f"  WARNING: {w}")

    def _exec_calculate(self, stmt: CalculateStmt):
        self._require_bridge(stmt.line)
        system = self._eval_str(stmt.system)
        method = self._method(self._eval_str(stmt.method), stmt.line)
        self._require_valid(system, stmt.line, "CALCULATE")
        self._defaults(stmt)
        self.out.write(f"  Calculating: {system} using {method}...")
        result = self.bridge.calculate(system, method, stmt.allocation)
        self._emit("calculate", result)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        self.runtime.store_results(result, "calculate")
        self.out.write(format_impacts(result))

    def _exec_contribution(self, stmt: ContributionStmt):
        self._require_bridge(stmt.line)
        system = self._eval_str(stmt.system)
        method = self._method(self._eval_str(stmt.method), stmt.line)
        self._require_valid(system, stmt.line, "CONTRIBUTION")
        self._defaults(stmt, TOP=stmt.top)
        cats = [self._eval_str(c) for c in stmt.categories] or None
        self.out.write(f"  Contribution analysis: {system}...")
        result = self.bridge.contribution(
            system, method, stmt.top, cats, stmt.allocation)
        self._emit("contribution", result)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        self.runtime.store_results(result, "contribution")
        self.out.write(format_generic(result))

    def _exec_inventory(self, stmt: InventoryStmt):
        self._require_bridge(stmt.line)
        system = self._eval_str(stmt.system)
        method = self._method(self._eval_str(stmt.method), stmt.line)
        self._require_valid(system, stmt.line, "INVENTORY")
        self._defaults(stmt, MAX=stmt.max_flows)
        self.out.write(f"  Inventory: {system}...")
        result = self.bridge.inventory(
            system, method, stmt.max_flows, stmt.allocation)
        self._emit("inventory", result)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        self.runtime.store_results(result, "inventory")
        self.out.write(format_generic(result))

    def _exec_montecarlo(self, stmt: MonteCarloStmt):
        self._require_bridge(stmt.line)
        system = self._eval_str(stmt.system)
        method = self._method(self._eval_str(stmt.method), stmt.line)
        self._require_valid(system, stmt.line, "MONTECARLO")
        self._defaults(stmt, RUNS=stmt.runs)
        self.out.write(f"  Monte Carlo ({stmt.runs} runs): {system}...")
        result = self.bridge.monte_carlo(
            system, method, stmt.runs, stmt.allocation)
        self._emit("monte_carlo", result)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        self.runtime.store_results(result, "montecarlo")
        self.out.write(format_generic(result))

    def _exec_scenario(self, stmt: ScenarioStmt):
        """Accumulate a scenario definition."""
        overrides = {}
        for let_stmt in stmt.overrides:
            self._at(let_stmt.line)
            self._check_overridable([let_stmt.name], "SCENARIO",
                                    let_stmt.line or stmt.line)
            val = self._eval(let_stmt.expr)
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise BasicError(
                    f"'{let_stmt.name}' must be set to a number in a "
                    f"SCENARIO, not {val!r}.", let_stmt.line or stmt.line)
            overrides[let_stmt.name] = float(val)
        self.runtime.scenarios[stmt.name] = overrides

    def _exec_run_scenarios(self, stmt: RunScenariosStmt):
        self._require_bridge(stmt.line)
        system = self._eval_str(stmt.system)
        method = self._method(self._eval_str(stmt.method), stmt.line)
        self._require_valid(system, stmt.line, "RUN SCENARIOS")
        self._defaults(stmt)

        if stmt.from_csv:
            # CSV-based scenarios
            csv_path = self._eval_str(stmt.from_csv)
            save_to = self._eval_str(stmt.save_to) if stmt.save_to else ""
            self.out.write(f"  Running scenarios from {csv_path}...")
            result = self.bridge.run_scenarios_csv(
                system, method, csv_path, save_to, stmt.allocation)
            self._emit("run_scenarios_csv", result)
        else:
            # Use accumulated SCENARIO blocks
            scenarios = self.runtime.scenarios
            if not scenarios:
                raise BasicError(
                    "No scenarios defined. Use SCENARIO blocks before "
                    "RUN SCENARIOS.", stmt.line)
            self.out.write(f"  Running {len(scenarios)} scenarios...")
            result = self.bridge.run_scenarios(
                system, method, scenarios, stmt.allocation)
            self._emit("run_scenarios", result)

        if "error" in result:
            raise BasicError(result["error"], stmt.line)

        self.runtime.store_results(result, "scenarios")
        self.out.write(format_scenarios(result))

        # Clear accumulated scenarios after running
        self.runtime.scenarios.clear()

    def _exec_sensitivity(self, stmt: SensitivityStmt):
        self._require_bridge(stmt.line)
        system = self._eval_str(stmt.system)
        method = self._method(self._eval_str(stmt.method), stmt.line)
        self._require_valid(system, stmt.line, "SENSITIVITY")
        self._defaults(stmt)

        if stmt.from_csv:
            csv_path = self._eval_str(stmt.from_csv)
            save_to = self._eval_str(stmt.save_to) if stmt.save_to else ""
            self.out.write(f"  Running sensitivity from {csv_path}...")
            result = self.bridge.run_sensitivity_csv(
                system, method, csv_path, stmt.variation_pct,
                save_to, stmt.allocation)
            self._emit("run_sensitivity_csv", result)
        else:
            params = stmt.parameters
            lines = stmt.parameter_lines or []
            for i, pname in enumerate(params):
                self._check_overridable(
                    [pname], "SENSITIVITY",
                    lines[i] if i < len(lines) else stmt.line)
            self.out.write(f"  Sensitivity +/-{stmt.variation_pct}% on "
                  f"{len(params)} parameters...")
            result = self.bridge.run_sensitivity(
                system, method, params, stmt.variation_pct,
                stmt.allocation)
            self._emit("run_sensitivity", result)

        if "error" in result:
            raise BasicError(result["error"], stmt.line)

        self.runtime.store_results(result, "sensitivity")
        self.out.write(format_sensitivity(result))

    def _exec_validate(self, stmt: ValidateStmt):
        self._require_bridge(stmt.line)
        ref = self._eval_str(stmt.system)
        self.out.write(f"  Validating: {ref}...")
        result = self.bridge.validate_system(ref, stmt.with_calc)
        self._emit("validate_system", result)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        self._record_validation(result)
        self.out.write(format_generic(result))
        if not result.get("valid", True):
            self.out.write(
                f"  WARNING: '{result.get('system', ref)}' did not pass. "
                f"Calculations on it are refused in this session until it "
                f"is fixed (or deleted and rebuilt) and VALIDATE passes.")

    def _exec_check(self, stmt: CheckStmt):
        """CHECK "system" [TIER n]: the three tiers of model checking.
        Tier 1 is structural and always says so."""
        self._require_bridge(stmt.line)
        ref = self._eval_str(stmt.system)
        if stmt.tier not in (1, 2, 3):
            raise BasicError(f"There is no tier {stmt.tier}.", stmt.line,
                             hint="Use TIER 1, TIER 2 or TIER 3.")
        self._defaults(stmt)
        self.out.write(f"  Checking: {ref} (Tier {stmt.tier})...")
        if stmt.tier == 1:
            result = self.bridge.validate_system(ref)
            self._emit("validate_system", result)
            if "error" in result:
                raise BasicError(result["error"], stmt.line)
            self._record_validation(result)
            self.out.write(format_generic(result))
            self.out.write(TIER_1_CAVEAT.format(
                system=result.get("system", ref)))
        elif stmt.tier == 2:
            against = (f' against "{self._eval_str(stmt.against)}"'
                       if stmt.against else "")
            self.out.write(
                f"  Tier 2 compares every exchange in the model with the "
                f"source data{against}. olcaBASIC lists the model; the "
                f"comparison is yours to make, line by line.")
            desc = self.bridge.find_system(ref)
            if desc is None:
                raise BasicError(f"Product system not found: {ref}",
                                 stmt.line)
            folder = getattr(desc, "category", "") or ""
            proc = self.bridge.find_process(desc.name)
            if proc is not None:
                folder = getattr(proc, "category", "") or folder
            if not folder:
                self.out.write("  The model is not in a folder, so there is "
                               "nothing to list. EXTRACT FOLDER \"path\" "
                               "lists a folder you name.")
                return
            result = self.bridge.extract_model(folder.split("/")[0])
            self._emit("extract_model", result)
            if "error" in result:
                raise BasicError(result["error"], stmt.line)
            self.out.write(format_generic(result))
        else:
            self.out.write(
                f"  Tier 3 asks whether the results are plausible. Run "
                f"CALCULATE \"{ref}\" USING \"method\" and CONTRIBUTION "
                f"\"{ref}\" USING \"method\" TOP 5, then compare the "
                f"totals and the main contributors with published values "
                f"for similar products. olcaBASIC cannot judge that for you.")

    def _exec_extract(self, stmt: ExtractStmt):
        self._require_bridge(stmt.line)
        folder = self._eval_str(stmt.folder)
        self.out.write(f"  Extracting: {folder}...")
        result = self.bridge.extract_model(folder)
        self._emit("extract_model", result)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        self.out.write(format_generic(result))

    def _exec_audit(self, stmt: AuditStmt):
        self._require_bridge(stmt.line)
        folder = self._eval_str(stmt.folder)
        self.out.write(f"  Auditing: {folder}...")
        result = self.bridge.audit_model(folder)
        self._emit("audit_model", result)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        self.out.write(format_generic(result))

    def _exec_save_results(self, stmt: SaveResultsStmt):
        if not self.runtime.last_results:
            self.out.write("  No results to save.")
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
        self.out.write(f"  Results saved to {filename}")

    def _exec_delete(self, stmt: DeleteStmt):
        self._require_bridge(stmt.line)
        ref = self._eval_str(stmt.ref)
        if not stmt.entity_type:
            raise BasicError("Say what to delete.", stmt.line,
                             hint='DELETE PROCESS "name", DELETE SYSTEM '
                                  '"name" or DELETE FLOW "name"')
        etype = stmt.entity_type.lower()
        if etype == "system":
            etype = "product_system"

        # The engine deletes by UUID, so resolve the name first.
        # (Passing the name always came back 'not found'.)
        target = self.bridge.resolve_entity_strict(etype, ref)
        if "error" in target:
            raise BasicError(target["error"], stmt.line)
        if target.get("not_found"):
            self.out.write(f"  Not found: {ref} (nothing to delete)")
            return

        if etype == "flow":
            # Deleting a flow that is still used leaves processes and
            # impact categories broken, so look for uses first. Every
            # process is read: this is slow on a large database.
            self.out.write(f"  Checking where '{target['name']}' is used "
                           f"(this reads every process)...")
            usage = self.bridge.find_flow_usage(
                target["id"], 1, prefer_categories=[
                    f for f in (self.runtime.process_folder,
                                self.runtime.flow_folder) if f])
            self._emit("find_flow_usage", usage)
            if "error" in usage:
                raise BasicError(
                    f"Could not check where '{target['name']}' is used "
                    f"({usage['error']}), so it was not deleted.", stmt.line)
            if usage["in_use"]:
                users = usage["used_by_processes"] + [
                    f"{c} (impact category)"
                    for c in usage["used_in_impact_categories"]
                ] + list(usage.get("used_elsewhere", []))
                raise BasicError(
                    f"Flow '{target['name']}' is still used by "
                    f"{', '.join(users)}, so it was not deleted.", stmt.line,
                    hint=f"Remove it from there first. SHOW FLOW "
                         f"\"{target['name']}\" USAGE lists every use.")

        if not self.runtime.confirm_delete:
            confirm = self._ask(
                f"  Delete {stmt.entity_type} '{target['name']}'? (yes/no) ",
                stmt.line,
                'Put CONFIRM DELETE ON before the DELETE line.')
            if confirm.lower() not in ("yes", "y"):
                self.out.write("  Cancelled.")
                return
        else:
            self.out.write(f"  Deleting {stmt.entity_type} '{target['name']}'...")

        if etype == "flow":
            # the usage was checked just above, completely
            result = self.bridge.delete_entity(etype, target["id"], True)
        else:
            result = self.bridge.delete_entity(etype, target["id"])
        self._emit("delete_entity", result)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        self.out.write(f"  Deleted: {result.get('name', ref)}")
        if etype == "product_system":
            self._forget_validation(target["id"])
        self.bridge.refresh_caches()

    def _exec_find(self, stmt: FindStmt):
        self._require_bridge(stmt.line)
        term = self._eval_str(stmt.search_term)
        etype = stmt.entity_type.upper()

        if etype == "PROCESS":
            loc = self._eval_str(stmt.location) if stmt.location else ""
            cat = self._eval_str(stmt.category) if stmt.category else ""
            result = self.bridge.search_processes(term, cat, loc, 20, True)
            self._emit("search_processes", result)
            if "error" in result:
                raise BasicError(result["error"], stmt.line)
            self.out.write(format_processes(result))
        elif etype == "SYSTEM":
            result = self.bridge.list_systems(term)
            self._emit("list_systems", result)
            self.out.write(format_systems(result))
        elif etype == "FLOW":
            cat = self._eval_str(stmt.category) if stmt.category else ""
            result = self.bridge.search_flows(term, cat)
            self._emit("search_flows", result)
            if "error" in result:
                raise BasicError(result["error"], stmt.line)
            self.out.write(format_flows(result))
        elif etype == "METHOD":
            result = self.bridge.list_methods(term)
            self._emit("list_methods", result)
            self.out.write(format_methods(result))
        elif etype == "CHEMICAL":
            result = self.bridge.chemical_synonyms(term)
            self._emit("chemical_synonyms", result)
            self.out.write(format_generic(result))
        elif etype == "UNIT":
            result = self.bridge.find_unit(term)
            self._emit("find_unit", result)
            self.out.write(format_generic(result))
        else:
            self.out.write(f"  Unknown FIND type: {etype}")

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

    def _exec_load(self, stmt: LoadStmt):
        """LOAD "file": the program in memory becomes the file, as on a
        BBC Micro. Nothing runs until RUN. A file that does not parse is
        refused and the program in memory stays as it was."""
        filename = self._eval_str(stmt.filename)
        try:
            with open(filename, "r", encoding="utf-8") as f:
                source = f.read()
        except FileNotFoundError:
            raise BasicError(f"File not found: {filename}", stmt.line)
        try:
            parse(self._process_includes(source, filename))
        except ParseError as e:
            raise BasicError(
                f"{filename} was not loaded: {e}", stmt.line,
                hint="Fix the file and LOAD it again. The program in "
                     "memory has not changed.")
        self.runtime.program_history[:] = [source]
        lines = len(source.rstrip("\n").splitlines())
        self.out.write(f"  Loaded {filename} ({lines} lines). "
                       f"LIST shows it, RUN runs it.")

    def _memory_text(self) -> str:
        return "\n".join(part.rstrip("\n")
                         for part in self.runtime.program_history)

    def _exec_list(self, stmt: ListStmt):
        """LIST: the program in memory, numbered for reference (the
        numbers are not part of the program)."""
        text = self._memory_text()
        if not text.strip():
            self.out.write("  No program in memory. LOAD \"file\" puts one "
                           "there; so does anything you run.")
            return
        lines = text.splitlines()
        width = len(str(len(lines)))
        for i, row in enumerate(lines, 1):
            self.out.write(f"  {i:>{width}}  {row}")

    def _exec_run_memory(self, stmt: RunMemoryStmt):
        """RUN on its own: run the program in memory."""
        text = self._memory_text()
        if not text.strip():
            raise BasicError(
                "There is no program in memory to run.", stmt.line,
                hint='LOAD "file.baslca" then RUN, or RUN "file.baslca".')
        try:
            statements = parse(self._process_includes(text, ""))
        except ParseError as e:
            raise BasicError(f"The program in memory does not parse: {e}",
                             stmt.line)
        self._stop_requested = False
        self._execute_block(statements)

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
        self.out.write(f"  Global parameter {stmt.name} = {shown}{was}")

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
        self._emit("edit_flow", result)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        self.out.write(f"  Edited flow: {result.get('flow_name', target)}")
        for c in result.get("changes", []):
            self.out.write(f"    {c}")
        # A flow outside your own folders is shared with other models
        cat = (result.get("category") or found.get("category") or "").lower()
        mine = [f.lower().rstrip("/") for f in (self.runtime.flow_folder,
                                                self.runtime.process_folder) if f]
        if not any(cat == m or cat.startswith(m + "/") for m in mine):
            self.out.write(f"  NOTE: '{target}' isn't in your build folders, so this "
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

        def describe(ex, n):
            prov = ex.default_provider
            where = ""
            if prov is not None:
                loc = getattr(prov, "location", "") or ""
                where = f", provider {prov.name}" + (f" [{loc}]" if loc else "")
            amount = ex.amount_formula or _fmt_num(ex.amount)
            unit = ex.unit.name if ex.unit else ""
            return f"    INDEX {n}: {amount} {unit}{where}"

        def find_exchange(spec, action):
            """One exchange matching a flow or provider name. If the
            name matches several, PROVIDER, LOCATION, AMOUNT or INDEX
            on the line says which."""
            self._at(spec.get("line", stmt.line))
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
            everything = list(hits)
            # REMOVE reads PROVIDER, LOCATION and AMOUNT as "which one";
            # UPDATE reads them as new values, so it only takes INDEX.
            if action == "remove":
                if "provider" in spec:
                    wanted = self._eval_str(spec["provider"]).lower()
                    hits = [ex for ex in hits if ex.default_provider and wanted in (
                        (ex.default_provider.name or "").lower(),
                        ex.default_provider.id.lower())]
                if "location" in spec:
                    wanted = self._eval_str(spec["location"]).lower()
                    hits = [ex for ex in hits if ex.default_provider and (
                        getattr(ex.default_provider, "location", "") or ""
                    ).lower() == wanted]
                if "amount" in spec:
                    amount = self._eval(spec["amount"])
                    values = {p.name: p.value for p in (proc.parameters or [])}

                    def value_of(ex):
                        if ex.amount_formula in values:
                            return values[ex.amount_formula]
                        return ex.amount

                    hits = [ex for ex in hits if value_of(ex) is not None
                            and abs(value_of(ex) - amount) <= 1e-9 * max(
                                1.0, abs(amount))]
            if "index" in spec:
                n = spec["index"]
                if not 1 <= n <= len(everything):
                    raise BasicError(
                        f"INDEX {n} is out of range: '{name}' appears "
                        f"{len(everything)} time(s) in '{target}'.", line,
                        hint=f"Use INDEX 1 to {len(everything)}.")
                hits = [ex for ex in hits if ex is everything[n - 1]]
            if not hits:
                listing = "\n".join(describe(ex, i + 1)
                                    for i, ex in enumerate(everything))
                raise BasicError(
                    f"None of the {len(everything)} exchanges called "
                    f"'{name}' in '{target}' fits what the line asks for:\n"
                    f"{listing}", line,
                    hint="Pick one with INDEX n.")
            if len(hits) > 1:
                same_flow = len({ex.flow.id for ex in hits if ex.flow}) == 1
                if not same_flow or "index" in spec:
                    raise BasicError(
                        f"'{name}' matches {len(hits)} exchanges in "
                        f"'{target}'. Say INPUT or OUTPUT to pick one.", line)
                listing = "\n".join(describe(ex, everything.index(ex) + 1)
                                    for ex in hits)
                extra = (" (or PROVIDER, LOCATION or AMOUNT)"
                         if action == "remove" else "")
                raise BasicError(
                    f"'{name}' appears {len(hits)} times in '{target}':\n"
                    f"{listing}", line,
                    hint=f"Add INDEX n to the line to say which{extra}.")
            return name, hits[0], line

        def is_repeated(ex):
            return sum(1 for e in current
                       if e.flow and ex.flow and e.flow.id == ex.flow.id) > 1

        # Removals. The engine removes by flow, so a flow that appears
        # more than once can't be removed on its own.
        remove_ids = []
        for spec in stmt.remove_exchanges:
            name, ex, line = find_exchange(spec, "remove")
            if getattr(ex, "is_quantitative_reference", False):
                raise BasicError(
                    f"'{name}' is the reference product of '{target}' and "
                    f"can't be removed. Delete the process instead.", line)
            if is_repeated(ex):
                # one of several exchanges of the same flow
                remove_ids.append({"flow_id": ex.flow.id,
                                   "internal_id": ex.internal_id})
            else:
                remove_ids.append(ex.flow.id)

        # Updates
        updates = []
        for spec in stmt.update_exchanges:
            name, ex, line = find_exchange(spec, "update")
            upd = {"flow_id": ex.flow.id}
            if is_repeated(ex):
                upd["internal_id"] = ex.internal_id
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
        add_lines = [ex.line or stmt.line for ex in stmt.add_exchanges]
        for ex_dict, ex_line in zip(added, add_lines):
            for var_name in self._referenced_globals(ex_dict.get("formula", "")):
                self._sync_global(var_name, ex_line)
        self._at(stmt.line)

        add_params = []
        for let_stmt in stmt.add_params:
            self._at(let_stmt.line)
            val = self._eval(let_stmt.expr)
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise BasicError(f"Parameter '{let_stmt.name}' must be a "
                                 f"number", let_stmt.line or stmt.line)
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
            if self._declare(proc_id, stmt):
                self.out.write(f"  Edited process: {target}")
                self.out.write("    data declaration updated")
                if self.runtime.epd is not None:
                    self.runtime.epd._reset_progress()
            else:
                self.out.write(f"  Nothing to change in '{target}'.")
            return

        result = self.bridge.edit_process(proc_id, **kwargs)
        self._emit("edit_process", result)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        changes = result.get("changes", [])
        warnings = [c for c in changes if str(c).startswith("WARNING")]
        self.out.write(f"  Edited process: {target}")
        for c in changes:
            if c not in warnings:
                self.out.write(f"    {c}")
        if self._declare(proc_id, stmt):
            self.out.write("    data declaration updated")
        if self.runtime.epd is not None:
            self.runtime.epd._reset_progress()
        for w in warnings:
            self.out.write(f"  {w}")
        if (stmt.set_location is not None and
                not any("location set" in str(c) for c in changes)):
            self.out.write(f"  WARNING: location '{kwargs['location']}' wasn't found, "
                  f"so the location is unchanged.")
        if added or remove_ids or any("provider_id" in u for u in updates):
            self.out.write("  NOTE: product systems that already use this process "
                  "keep their old links. DELETE SYSTEM and SYSTEM again "
                  "to include these changes.")
        self.bridge.refresh_caches()

    def _exec_show(self, stmt: ShowStmt):
        """SHOW PROCESS/FLOW/PARAMETER with optional sub-command."""
        self._require_bridge(stmt.line)
        ref = self._eval_str(stmt.ref) if stmt.ref is not None else ""
        sub = stmt.sub_command.upper()
        etype = stmt.entity_type.upper()
        flt = self._eval_str(stmt.filter) if stmt.filter is not None else ""

        if etype == "GLOBAL_PARAMS":
            result = self.bridge.get_global_parameters(flt)
            self._emit("get_global_parameters", result)
            self.out.write(format_params(result))
            return

        if etype == "SYSTEM":
            if sub == "LINKS":
                result = self.bridge.get_system_links(ref, flt)
                self._emit("get_system_links", result)
                if "error" in result:
                    raise BasicError(result["error"], stmt.line)
                self.out.write(format_generic(result))
            elif sub == "PARAMS":
                result = self.bridge.get_system_parameters(ref, flt)
                self._emit("get_system_parameters", result)
                if "error" in result:
                    raise BasicError(result["error"], stmt.line)
                self.out.write(format_params(result))
            else:
                desc = self.bridge.find_system(ref)
                if desc is None:
                    raise BasicError(
                        f"Product system not found: {ref}", stmt.line,
                        hint=f"FIND SYSTEM \"{ref}\" searches by part of "
                             f"a name.")
                last = self.runtime.validation.get(desc.id)
                state = ("not validated in this session" if last is None
                         else "passed VALIDATE" if last.get("valid")
                         else "FAILED VALIDATE")
                self.out.write(f"  Name:      {desc.name}")
                self.out.write(f"  Folder:    "
                               f"{getattr(desc, 'category', '') or '(root)'}")
                self.out.write(f"  UUID:      {desc.id}")
                self.out.write(f"  Validated: {state}")
                self.out.write(f"  SHOW SYSTEM \"{desc.name}\" PARAMS and "
                               f"... LINKS [\"text\"] show more.")
            return

        if etype == "PROCESS" and sub == "QUALITY":
            result = self.bridge.get_data_quality(ref)
            self._emit("get_data_quality", result)
            if "error" in result:
                raise BasicError(result["error"], stmt.line)
            self.out.write(format_generic(result))
            return

        if etype == "PROCESS":
            proc = self.bridge.resolve_process_strict(ref)
            if "error" in proc:
                raise BasicError(proc["error"], stmt.line)
            result = self.bridge.get_process_details(proc["process_id"])
            self._emit("get_process_details", result)
            if "error" in result:
                raise BasicError(result["error"], stmt.line)

            if not sub:
                self.out.write(format_process_details(result))
            elif sub == "INPUTS":
                exchanges = result.get("exchanges", [])
                inputs = [e for e in exchanges if e.get("is_input")]
                if not inputs:
                    self.out.write(f"  {result.get('name', ref)}: no inputs")
                else:
                    self.out.write(f"  {result.get('name', ref)}: "
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
                    self.out.write(format_table(headers, rows,
                                       max_widths=[45, 30, 8, 30]))
            elif sub == "OUTPUTS":
                exchanges = result.get("exchanges", [])
                outputs = [e for e in exchanges if not e.get("is_input")]
                if not outputs:
                    self.out.write(f"  {result.get('name', ref)}: no outputs")
                else:
                    self.out.write(f"  {result.get('name', ref)}: "
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
                    self.out.write(format_table(headers, rows,
                                       max_widths=[45, 30, 8, 4]))
            elif sub == "LOCATION":
                self.out.write(f"  {result.get('location', '(none)')}")
            elif sub == "DESCRIPTION":
                desc = result.get("description", "(none)")
                self.out.write(f"  {desc}")
            elif sub == "PARAMS":
                params = result.get("parameters", [])
                if not params:
                    self.out.write(f"  {result.get('name', ref)}: no parameters")
                else:
                    headers = ["Name", "Value", "Formula"]
                    rows = [[p.get("name", "?"),
                             str(p.get("value", "")),
                             p.get("formula", "") or ""]
                            for p in params]
                    self.out.write(format_table(headers, rows))

        elif etype == "FLOW":
            found = self.bridge.find_flow(ref, "", "")
            if not found:
                raise BasicError(f"Flow not found: {ref}", stmt.line)
            if found.get("ambiguous"):
                raise BasicError(f"'{ref}' matches {found['ambiguous']} flows. "
                                 f"Give the exact name of the one you mean.",
                                 stmt.line)
            if sub == "USAGE":
                limit = stmt.limit or 10
                if not stmt.limit:
                    self._default("USAGE LIMIT", limit)
                self.out.write(f"  Looking for uses of '{found['flow_name']}' "
                               f"(this reads processes until {limit} uses "
                               f"are found)...")
                usage = self.bridge.find_flow_usage(
                    found["flow_id"], limit, prefer_categories=[
                        f for f in (self.runtime.process_folder,
                                    self.runtime.flow_folder) if f])
                self._emit("find_flow_usage", usage)
                if "error" in usage:
                    raise BasicError(usage["error"], stmt.line)
                users = usage["used_by_processes"]
                cats = usage["used_in_impact_categories"]
                other = usage.get("used_elsewhere", [])
                if not usage["in_use"]:
                    self.out.write(
                        f"  Not used anywhere ({usage['processes_checked']} "
                        f"of {usage['processes_total']} processes checked).")
                for u in users:
                    self.out.write(f"    [P]    {u}")
                for c in cats:
                    self.out.write(f"    [I]    {c} (impact category)")
                for x in other:
                    self.out.write(f"    [O]    {x}")
                if usage["in_use"]:
                    total = len(users) + len(cats) + len(other)
                    tail = ("" if usage["complete"] else
                            f" The search stopped at LIMIT {limit}: there "
                            f"may be more.")
                    self.out.write(f"  {total} use(s) found.{tail}")
                return
            flow = self.bridge.get_flow_details(found["flow_id"])
            if "error" in flow:
                raise BasicError(flow["error"], stmt.line)
            if sub == "DESCRIPTION":
                self.out.write(f"  {flow['description'] or '(none)'}")
            else:
                self.out.write(format_flow_details(flow, units_only=(sub == "UNITS")))

        elif etype == "PARAMETER":
            result = self.bridge.get_global_parameters(ref)
            self._emit("get_global_parameters", result)
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
                    self.out.write(f"  {name} = {p['formula']}{now_txt}")
                else:
                    self.out.write(f"  {name} = {_fmt_num(p.get('value', '?'))}")
            elif sub == "DESCRIPTION":
                self.out.write(f"  {p.get('description', '(none)')}")

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
        self._emit("edit_process", result)

        if "error" in result:
            raise BasicError(result["error"], stmt.line)

        self.out.write(f"  Linked: {source_name} -> {target_name} "
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
            self.out.write(f"  Now browsing: {stmt.target.title()}")
        else:
            # Show menu
            modes = ["PROCESSES", "FLOWS", "METHODS", "SYSTEMS"]
            labels = ["Processes", "Flows", "Methods and parameters",
                      "Product systems"]
            self.out.write("  Browse:")
            for i, label in enumerate(labels, 1):
                marker = " *" if modes[i-1] == self.runtime.navigation_mode else ""
                self.out.write(f"    {i}. {label}{marker}")
            try:
                choice = self._ask("\n  : ", stmt.line, "Say which: NAVIGATE PROCESSES, NAVIGATE FLOWS, NAVIGATE METHODS or NAVIGATE SYSTEMS.").strip()
                if choice.isdigit() and 1 <= int(choice) <= 4:
                    self.runtime.navigation_mode = modes[int(choice) - 1]
                    self.out.write(f"  Now browsing: {labels[int(choice) - 1]}")
                elif choice.upper() in modes:
                    self.runtime.navigation_mode = choice.upper()
                    self.out.write(f"  Now browsing: {choice.title()}")
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
        self._emit("list_category_contents", result)
        known = {sf.lower() for sf in result["subfolders"]}
        created = [p for p in self._pending_subfolders(path)
                   if p.lower() not in known]
        if created:
            result = dict(result)
            result["subfolders"] = sorted(result["subfolders"] + created)
            result["subfolder_count"] = len(result["subfolders"])

        from fnmatch import fnmatch
        pattern = stmt.filter_pattern.lower() if stmt.filter_pattern else ""

        mode_label = self.runtime.navigation_mode.title()
        if pattern:
            self.out.write(f"  [{mode_label}] {result['path']}  "
                  f"(filter: {stmt.filter_pattern})")
        else:
            self.out.write(f"  [{mode_label}] {result['path']}")
        self.out.write()

        shown_folders = 0
        if result["subfolders"]:
            for sf in result["subfolders"]:
                last = sf.split("/")[-1]
                if pattern and not fnmatch(last.lower(), pattern):
                    continue
                self.out.write(f"    [DIR]  {last}/")
                shown_folders += 1

        shown_entities = 0
        if result["entities"]:
            for e in result["entities"]:
                if pattern and not fnmatch(e["name"].lower(), pattern):
                    continue
                tag = e["type"][0].upper()
                self.out.write(f"    [{tag}]    {e['name']}")
                shown_entities += 1

        if shown_folders == 0 and shown_entities == 0:
            if pattern:
                self.out.write(f"    No matches for {stmt.filter_pattern}")
            else:
                self.out.write("    (empty)")

        self.out.write()
        if pattern:
            self.out.write(f"  {shown_folders} folders, "
                  f"{shown_entities} entities (filtered)")
        else:
            self.out.write(f"  {result['subfolder_count']} folders, "
                  f"{result['entity_count']} entities")

    def _exec_dir_nav(self, stmt):
        """DIR "path" — navigate within the active tree."""
        if stmt.path is None:
            mode = self.runtime.navigation_mode
            folder = self._active_folder() or "(root)"
            self.out.write(f"  {mode.title()}: {folder}")
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
            if current and self._folder_exists(relative, entity_type):
                self._set_active_folder(relative)
            elif self._folder_exists(path, entity_type):
                self._set_active_folder(path)
            else:
                # Don't invent a folder: that silently sends later
                # PROCESS and CDIR commands somewhere that isn't there
                raise BasicError(
                    f"Folder not found: '{path}'. Use CAT (or LS) to list "
                    f"folders, CDIR to create one and go into it, or MKDIR "
                    f"to create one and stay where you are.", stmt.line)

        folder = self._active_folder() or "(root)"
        self.out.write(f"  {folder}")

    def _folder_exists(self, path: str, entity_type: str) -> bool:
        """A folder exists if openLCA has something in it, or if CDIR or
        MKDIR created it in this session."""
        wanted = path.strip("/").lower()
        for pending in self.runtime.pending_folders:
            p = pending.lower()
            if p == wanted or p.startswith(wanted + "/"):
                return True
        return self.bridge.folder_exists(path, entity_type)

    def _pending_subfolders(self, path: str) -> list:
        """Folders created this session, directly under path, that
        openLCA does not hold yet."""
        base = path.strip("/")
        out = set()
        for pending in self.runtime.pending_folders:
            if base:
                if not pending.lower().startswith(base.lower() + "/"):
                    continue
                rest = pending[len(base) + 1:]
            else:
                rest = pending
            if rest:
                out.add((base + "/" if base else "") + rest.split("/")[0])
        return sorted(out)

    def _exec_mkdir(self, stmt):
        """MKDIR "name": create a folder and stay where you are (the
        Linux meaning). CDIR creates it and goes in (the Acorn one)."""
        name = self._eval_str(stmt.name).strip("/")
        if not name:
            raise BasicError("MKDIR needs a folder name.", stmt.line,
                             hint='For example: MKDIR "00: My model"')
        current = self._active_folder()
        new_path = (current.rstrip("/") + "/" + name) if current else name
        if self.bridge and self.bridge.connected and self.bridge.folder_exists(
                new_path, self._nav_entity_type()):
            self.out.write(f"  Folder already exists: {new_path}")
            return
        self.runtime.pending_folders.add(new_path)
        self.out.write(f"  Created: {new_path}")
        self.out.write("  You are still in: "
                       f"{current or '(root)'}. The folder shows in openLCA "
                       "once something is built in it.")

    def _exec_save_program(self, stmt):
        """SAVE "file.baslca": write out the programs run so far in
        this session, so the work can be repeated with RUN."""
        filename = self._eval_str(stmt.filename)
        history = self.runtime.program_history
        if not history:
            raise BasicError(
                "There is nothing to save yet: no program has run "
                "without an error in this session.", stmt.line)
        text = "\n".join(part.rstrip("\n") for part in history) + "\n"
        with open(filename, "w", newline="\n", encoding="utf-8") as f:
            f.write(text)
        self.out.write(f"  Program saved to {filename} "
                       f"({len(text.splitlines())} lines). "
                       f"RUN \"{filename}\" repeats it.")

    def _exec_up(self):
        """UP — go up one level in the active tree."""
        current = self._active_folder()
        if "/" in current:
            self._set_active_folder(current.rsplit("/", 1)[0])
        else:
            self._set_active_folder("")
        folder = self._active_folder() or "(root)"
        self.out.write(f"  {folder}")

    def _exec_back(self):
        """BACK — toggle to previous folder in the active tree."""
        mode = self.runtime.navigation_mode
        prev = self.runtime.nav_previous.get(mode, "")
        self.runtime.nav_previous[mode] = self.runtime.nav_folders[mode]
        self.runtime.nav_folders[mode] = prev
        folder = prev or "(root)"
        self.out.write(f"  {folder}")

    def _exec_cdir(self, stmt):
        """CDIR — create and enter a folder in the active tree."""
        name = self._eval_str(stmt.name)
        current = self._active_folder()
        if current:
            new_path = current.rstrip("/") + "/" + name
        else:
            new_path = name
        self._set_active_folder(new_path)
        self.runtime.pending_folders.add(new_path)
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
        self.out.write(f"  Created and moved to: {new_path}")
        self.out.write(f"  {what} will be built here.")

    def _exec_tree(self, stmt: TreeStmt):
        """TREE: multi-level contribution tree for one impact category,
        with the pedigree scores on each branch's link."""
        self._require_bridge(stmt.line)
        system = self._eval_str(stmt.system)
        method = self._method(self._eval_str(stmt.method), stmt.line)
        self._require_valid(system, stmt.line, "TREE")
        if stmt.category is None:
            calc = self.bridge.calculate(system, method, stmt.allocation)
            if "error" in calc:
                raise BasicError(calc["error"], stmt.line)
            cats = ", ".join(i.get("category", "?") for i in calc.get("impacts", []))
            raise BasicError(f"TREE needs CATEGORY. Categories in "
                             f"{method}: {cats}", stmt.line)
        category = self._eval_str(stmt.category)
        self._defaults(stmt, LEVELS=stmt.levels, TOP=stmt.top)
        self.out.write(f"  Building contribution tree: {system}...")
        result = self.bridge.upstream_tree(
            system, method, category, stmt.levels, stmt.top,
            stmt.allocation, stmt.with_quality)
        self._emit("upstream_tree", result)
        if "error" in result:
            extra = result.get("available")
            msg = result["error"] + (f". Available: {', '.join(extra)}" if extra else "")
            raise BasicError(msg, stmt.line)
        self.runtime.store_results(result, "tree")
        self.out.write(format_tree(result, stmt.with_quality))

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

        if not etype:
            raise BasicError("Say what to move.", stmt.line,
                             hint='MOVE PROCESS "name" TO "folder", MOVE FLOW '
                                  '... or MOVE SYSTEM ...')
        kind = {"PROCESS": "process", "FLOW": "flow",
                "SYSTEM": "product_system"}[etype]
        # Strict: moving the wrong one of two same-named entries could
        # pull a background dataset out of its folder
        if etype == "PROCESS":
            proc = self.bridge.resolve_process_strict(ref)
            if "error" in proc:
                raise BasicError(proc["error"], stmt.line)
            found = {"id": proc["process_id"]}
        else:
            found = self.bridge.resolve_entity_strict(kind, ref)
        if "error" in found:
            raise BasicError(
                found["error"].replace("Nothing was deleted. Delete by UUID "
                                       "instead.", "Nothing was moved."),
                stmt.line, hint="Use the UUID instead of the name "
                                f"(FIND {etype} shows it).")
        if found.get("not_found"):
            raise BasicError(f"No {etype.lower()} is called '{ref}'.",
                             stmt.line,
                             hint=f"FIND {etype} \"{ref}\" searches by "
                                  f"part of a name.")
        result = self.bridge.move_entity(kind, found["id"], dest)
        self._emit("move_entity", result)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)

        self.out.write(f"  Moved {etype.lower()} '{ref}' to '{dest}'")
        self.bridge.refresh_caches()

    def _exec_help(self, stmt):
        """HELP, HELP <topic>, HELP <command>: all from the registry."""
        from . import registry
        self.out.write(registry.render(stmt.topic))
