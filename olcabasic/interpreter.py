"""
Interpreter for olcaBASIC.

Walks the AST and dispatches each statement to the bridge
(for openLCA operations) or handles it locally (variables,
control flow, output).
"""

import os
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
    format_generic, results_to_csv,
)


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
            "INT": int,
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

    def _process_includes(self, source: str, base_path: str) -> str:
        """Process INCLUDE directives (textual inclusion)."""
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
                    try:
                        with open(inc_path, "r") as f:
                            inc_source = f.read()
                        # Recursive includes
                        inc_source = self._process_includes(
                            inc_source, inc_path)
                        result.append(inc_source)
                        continue
                    except FileNotFoundError:
                        result.append(
                            f'REM ERROR: Include file not found: {inc_file}')
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
            print(f"  {val}")

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
            pf = self.runtime.process_folder or "(root)"
            ff = self.runtime.flow_folder or "(root)"
            print(f"  Process folder: {pf}")
            print(f"  Flow folder:    {ff}")

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
            # Check runtime variables
            if self.runtime.has_var(name):
                return self.runtime.get_var(name)
            # Return the name as a string (for flow names, unit names, etc.)
            return name

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
            result = self.bridge.get_process_details(ref)
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
            print(format_generic(result))

        elif sub == "FAMILY":
            self._require_bridge(stmt.line)
            args = [self._eval_str(a) for a in stmt.args]
            family = args[0] if args else ""
            result = self.bridge.set_database_family(family)
            print(format_generic(result))

        elif sub == "EXPR":
            # Multiple comma-separated expressions
            vals = [self._eval(a) for a in stmt.args]
            print("  " + "  ".join(str(v) for v in vals))

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
        if stmt.direction == "AIR":
            folder = folder or "Elementary flows/emission to air"
        elif stmt.direction == "WATER":
            folder = folder or "Elementary flows/emission to water"
        elif stmt.direction == "SOIL":
            folder = folder or "Elementary flows/emission to soil"
        elif stmt.direction == "NATURE":
            folder = folder or "Elementary flows/resource/in ground"

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
            found = self.bridge.find_flow(name, stmt.unit)
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
            # Try to resolve as process name
            provider_id = self.bridge.resolve_process(prov_str)
            if not provider_id:
                raise BasicError(
                    f"Provider process not found: {prov_str}",
                    stmt.line)

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

        # Handle READ INPUTS FROM DATA
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
                stmt.exchanges.append(ex)

        # Build exchange dicts
        exchanges = []
        for ex in stmt.exchanges:
            flow_name = self._eval_str(ex.flow_name)
            unit = ex.unit

            # Determine flow type
            flow_type = "product"
            category = folder
            if ex.is_product:
                flow_type = "product"
            elif ex.is_waste:
                flow_type = "waste"
            elif ex.direction_compartment:
                flow_type = "elementary"
                if ex.direction_compartment == "AIR":
                    category = "Elementary flows/emission to air"
                elif ex.direction_compartment == "WATER":
                    category = "Elementary flows/emission to water"
                elif ex.direction_compartment == "SOIL":
                    category = "Elementary flows/emission to soil"
                elif ex.direction_compartment == "NATURE":
                    category = "Elementary flows/resource/in ground"
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
            else:
                # Default: find the existing flow in the database
                # First, try to match a process name and get its qref flow
                # (this also gives us the provider for linking)
                proc_match = self.bridge.find_process_qref_flow(flow_name)
                if proc_match:
                    flow_id = proc_match["flow_id"]
                    provider_id = proc_match["process_id"]
                else:
                    # Try to find a flow by name directly
                    flow_match = self.bridge.find_flow(flow_name, unit)
                    if flow_match:
                        flow_id = flow_match["flow_id"]
                    else:
                        # Nothing found: create it (foreground flow)
                        flow_result = self.bridge.create_flow(
                            flow_name, unit, category, flow_type)
                        if "error" in flow_result:
                            raise BasicError(
                                f"Flow '{flow_name}': {flow_result['error']}",
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
            if provider_id and not ex.provider:
                ex_dict["provider_id"] = provider_id

            # Handle amount: explicit formula, variable reference, or bare number
            if ex.formula:
                ex_dict["formula"] = self._eval_str(ex.formula)
            elif self._expr_is_variable(ex.amount):
                # Expression contains variables: pass as formula
                ex_dict["formula"] = self._expr_to_formula(ex.amount)
            else:
                # Bare number: auto-parametrised by LCAFunctions
                ex_dict["amount"] = float(self._eval(ex.amount))

            # Explicit provider overrides auto-detected one
            if ex.provider:
                prov_str = self._eval_str(ex.provider)
                prov_id = self.bridge.resolve_process(prov_str)
                if prov_id:
                    ex_dict["provider_id"] = prov_id

            exchanges.append(ex_dict)

        # Build parameter dicts from local LET statements
        parameters = []
        param_names = set()
        for let_stmt in stmt.local_params:
            val = self._eval(let_stmt.expr)
            parameters.append({
                "name": let_stmt.name,
                "value": float(val) if isinstance(val, (int, float)) else 0,
            })
            param_names.add(let_stmt.name)

        # Auto-add parameters referenced in exchange formulas
        for ex_dict in exchanges:
            formula = ex_dict.get("formula", "")
            if formula:
                for var_name, var_val in self.runtime.get_numeric_globals().items():
                    if var_name in formula and var_name not in param_names:
                        parameters.append({
                            "name": var_name,
                            "value": float(var_val),
                        })
                        param_names.add(var_name)

        result = self.bridge.create_process(
            name, folder, exchanges, parameters or None,
            description, location, flow_schema, process_schema)

        if "error" in result:
            raise BasicError(result["error"], stmt.line)

        existed = result.get("already_existed", False)
        status = "exists" if existed else "created"
        ex_count = result.get("exchange_count", 0)
        p_count = result.get("parameter_count", 0)
        print(f"  Process {status}: {name} "
              f"({ex_count} exchanges, {p_count} parameters)")

    def _exec_system(self, stmt: SystemStmt):
        self._require_bridge(stmt.line)
        proc_ref = self._eval_str(stmt.process_ref)
        folder = self._eval_str(stmt.folder) if stmt.folder else None
        linking = stmt.linking.lower()
        target_amount = float(self._eval(stmt.target_amount)) if stmt.target_amount else None
        target_unit = stmt.target_unit or None
        target_prop = self._eval_str(stmt.target_property) if stmt.target_property else None

        print(f"  Creating product system from: {proc_ref}...")
        result = self.bridge.create_system(
            proc_ref, linking, target_amount, target_unit,
            target_prop, folder)

        if "error" in result:
            raise BasicError(result["error"], stmt.line)

        existed = result.get("already_existed", False)
        status = "exists" if existed else "created"
        print(f"  System {status}: {result.get('system_name', proc_ref)}")
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
            result = self.bridge.lca.run_scenarios_csv(
                system, method, csv_path, save_to, stmt.allocation or None)
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
            result = self.bridge.lca.run_sensitivity_csv(
                system, method, csv_path, stmt.variation_pct,
                save_to, stmt.allocation or None)
        else:
            params = stmt.parameters
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
        with open(filename, "w") as f:
            f.write(csv_str)
        print(f"  Results saved to {filename}")

    def _exec_delete(self, stmt: DeleteStmt):
        self._require_bridge(stmt.line)
        ref = self._eval_str(stmt.ref)
        etype = stmt.entity_type.lower()
        if etype == "SYSTEM":
            etype = "product_system"

        if not self.runtime.confirm_delete:
            confirm = input(
                f"  Delete {stmt.entity_type} '{ref}'? (yes/no) ")
            if confirm.lower() not in ("yes", "y"):
                print("  Cancelled.")
                return

        result = self.bridge.delete_entity(etype, ref)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        print(f"  Deleted: {result.get('name', ref)}")
        # Auto-refresh cache so the deleted entity disappears
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
            print(format_generic(result))
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

        i = start
        while (step > 0 and i <= end) or (step < 0 and i >= end):
            self.runtime.set_var(stmt.variable, i)
            self._execute_block(stmt.body)
            if self._stop_requested:
                break
            i += step

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
            with open(filename, "r") as f:
                source = f.read()
            self.run_program(source, filename)
        except FileNotFoundError:
            raise BasicError(f"File not found: {filename}", stmt.line)

    def _exec_edit_process(self, stmt: EditProcessStmt):
        self._require_bridge(stmt.line)
        target = self._eval_str(stmt.target)
        proc_id = self.bridge.resolve_process(target)
        if not proc_id:
            raise BasicError(f"Process not found: {target}", stmt.line)
        # Build kwargs for edit_process — simplified for now
        print(f"  Editing process: {target}")
        # TODO: full edit implementation
        print("  EDIT PROCESS: not yet fully implemented in v0.1")

    def _exec_cat(self, stmt):
        """CAT/LS — list category contents, with optional wildcard filter."""
        self._require_bridge(stmt.line)
        if stmt.path:
            path = self._eval_str(stmt.path)
        else:
            path = self.runtime.process_folder

        result = self.bridge.list_category_contents(
            path, stmt.entity_type)

        # Apply wildcard filter if specified
        from fnmatch import fnmatch
        pattern = stmt.filter_pattern.lower() if stmt.filter_pattern else ""

        if pattern:
            print(f"  {result['path']}  (filter: {stmt.filter_pattern})")
        else:
            print(f"  {result['path']}")
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

    def _navigate_to(self, path: str):
        """Internal: navigate to a folder, saving previous for BACK."""
        self.runtime.previous_folder = self.runtime.process_folder
        self.runtime.process_folder = path

    def _exec_dir_nav(self, stmt):
        """DIR "path" or DIR (show current)."""
        if stmt.path is None:
            pf = self.runtime.process_folder or "(root)"
            ff = self.runtime.flow_folder or "(root)"
            print(f"  Process folder: {pf}")
            print(f"  Flow folder:    {ff}")
            return

        path = self._eval_str(stmt.path)

        if path == "/" or path == "":
            self._navigate_to("")
        else:
            current = self.runtime.process_folder
            if current:
                self._navigate_to(current.rstrip("/") + "/" + path)
            else:
                self._navigate_to(path)

        pf = self.runtime.process_folder or "(root)"
        print(f"  {pf}")

    def _exec_up(self):
        """UP — go up one level."""
        current = self.runtime.process_folder
        self.runtime.previous_folder = current
        if "/" in current:
            self.runtime.process_folder = current.rsplit("/", 1)[0]
        else:
            self.runtime.process_folder = ""
        pf = self.runtime.process_folder or "(root)"
        print(f"  {pf}")

    def _exec_back(self):
        """BACK — toggle to previous directory."""
        prev = self.runtime.previous_folder
        self.runtime.previous_folder = self.runtime.process_folder
        self.runtime.process_folder = prev
        pf = self.runtime.process_folder or "(root)"
        print(f"  {pf}")

    def _exec_cdir(self, stmt):
        """CDIR — create a category folder."""
        name = self._eval_str(stmt.name)
        current = self.runtime.process_folder
        if current:
            new_path = current.rstrip("/") + "/" + name
        else:
            new_path = name
        # openLCA creates categories on demand when entities are placed,
        # so we just navigate there
        self._navigate_to(new_path)
        print(f"  Created and moved to: {new_path}")

    def _exec_help(self, stmt):
        if stmt.topic:
            topic = stmt.topic.upper()
            topics = {
                "PROCESS": """
  PROCESS "name" [LOCATION "code"]
    FOLDER "path"
    OUTPUT NEW "flow", amount, unit, PRODUCT
    INPUT "existing process", amount, unit
    INPUT NEW "new flow", amount, unit
    LET param = value
  END PROCESS

  INPUT without NEW finds the existing process/flow and
  wires it up as a provider automatically.
  INPUT NEW creates a fresh flow (no provider link).
  OUTPUT NEW creates your foreground product.""",
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
