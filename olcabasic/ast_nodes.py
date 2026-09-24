"""
AST node types for olcaBASIC.

Each node represents a parsed statement. The interpreter walks
these and dispatches the appropriate LCAFunctions calls.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


# ── Expressions ──────────────────────────────────────────

@dataclass
class Expr:
    """Base class for expressions."""
    pass


@dataclass
class NumberLiteral(Expr):
    value: float


@dataclass
class StringLiteral(Expr):
    value: str


@dataclass
class Identifier(Expr):
    name: str


@dataclass
class BinOp(Expr):
    left: Expr
    op: str  # +, -, *, /
    right: Expr


@dataclass
class UnaryOp(Expr):
    op: str  # -, NOT
    operand: Expr


@dataclass
class FuncCall(Expr):
    name: str
    args: List[Expr]


@dataclass
class StringConcat(Expr):
    left: Expr
    right: Expr


@dataclass
class Comparison(Expr):
    left: Expr
    op: str  # =, <>, <, >, <=, >=
    right: Expr


@dataclass
class LogicalOp(Expr):
    left: Expr
    op: str  # AND, OR
    right: Expr


# ── Statements ───────────────────────────────────────────

@dataclass
class Statement:
    """Base class for statements."""
    line: int = 0


@dataclass
class CommentStmt(Statement):
    text: str = ""


@dataclass
class LetStmt(Statement):
    """LET name = expression"""
    name: str = ""
    expr: Expr = None


@dataclass
class PrintStmt(Statement):
    """PRINT with various sub-commands."""
    sub_command: str = ""  # DATABASE, PROCESSES, METHODS, etc.
    args: List[Expr] = field(default_factory=list)


@dataclass
class PrintResultsStmt(Statement):
    """PRINT RESULTS"""
    pass


@dataclass
class PrintExprStmt(Statement):
    """PRINT expression (plain print)"""
    expr: Expr = None


# ── Data input ───────────────────────────────────────────

@dataclass
class DataStmt(Statement):
    """DATA "name", amount, unit [, PROVIDER "x"]"""
    values: List[Any] = field(default_factory=list)


@dataclass
class InputStmt(Statement):
    """INPUT "prompt", variable"""
    prompt: str = ""
    variable: str = ""


# ── Flow creation ────────────────────────────────────────

@dataclass
class FlowStmt(Statement):
    """FLOW "name", unit, type [, FOLDER "path"]"""
    name: Expr = None
    unit: str = ""
    flow_type: str = "PRODUCT"
    folder: Expr = None
    direction: str = ""  # AIR, WATER, SOIL, NATURE (for elementary)
    is_new: bool = False  # NEW marker: always create


# ── Exchange (inside a process) ──────────────────────────

@dataclass
class ExchangeDef:
    """An INPUT or OUTPUT line inside a PROCESS block."""
    direction: str = "INPUT"   # INPUT or OUTPUT
    flow_name: Expr = None
    amount: Expr = None        # number, variable, or expression
    unit: str = ""
    is_new: bool = False       # NEW marker: create flow instead of finding
    is_product: bool = False   # PRODUCT marker (qref)
    is_waste: bool = False     # WASTE marker
    direction_compartment: str = ""  # TO AIR, TO WATER, etc.
    provider: Expr = None      # PROVIDER "name-or-uuid"
    formula: Expr = None       # explicit FORMULA "expr"


# ── Bridge ───────────────────────────────────────────────

@dataclass
class BridgeStmt(Statement):
    """BRIDGE block or single-line bridge."""
    name: Expr = None
    unit: str = ""
    is_waste: bool = False
    folder: Expr = None
    provider: Expr = None
    provider_flow: Expr = None


# ── Process ──────────────────────────────────────────────

@dataclass
class ProcessStmt(Statement):
    """PROCESS block with exchanges and local parameters."""
    name: Expr = None
    location: Expr = None
    folder: Expr = None
    description: Expr = None
    flow_schema: Expr = None
    process_schema: Expr = None
    exchanges: List[ExchangeDef] = field(default_factory=list)
    local_params: List[LetStmt] = field(default_factory=list)
    read_data: bool = False  # READ INPUTS FROM DATA


# ── Edit process ─────────────────────────────────────────

@dataclass
class EditProcessStmt(Statement):
    """EDIT PROCESS block."""
    target: Expr = None  # name or UUID
    add_exchanges: List[ExchangeDef] = field(default_factory=list)
    update_exchanges: List[Dict] = field(default_factory=list)
    remove_exchanges: List[str] = field(default_factory=list)
    add_params: List[LetStmt] = field(default_factory=list)
    update_params: Dict[str, float] = field(default_factory=dict)
    set_description: Expr = None
    set_category: Expr = None
    set_location: Expr = None


# ── System ───────────────────────────────────────────────

@dataclass
class SystemStmt(Statement):
    """SYSTEM block — create a product system."""
    process_ref: Expr = None
    linking: str = "PREFER_DEFAULTS"
    target_amount: Expr = None
    target_unit: str = ""
    target_property: Expr = None
    folder: Expr = None


# ── Calculation ──────────────────────────────────────────

@dataclass
class CalculateStmt(Statement):
    """CALCULATE "system" USING "method" [ALLOCATE x]"""
    system: Expr = None
    method: Expr = None
    allocation: str = ""


@dataclass
class ContributionStmt(Statement):
    """CONTRIBUTION block."""
    system: Expr = None
    method: Expr = None
    top: int = 10
    categories: List[Expr] = field(default_factory=list)
    allocation: str = ""


@dataclass
class InventoryStmt(Statement):
    """INVENTORY "system" USING "method" [MAX n]"""
    system: Expr = None
    method: Expr = None
    max_flows: int = 50
    allocation: str = ""


@dataclass
class MonteCarloStmt(Statement):
    """MONTECARLO "system" USING "method" RUNS n"""
    system: Expr = None
    method: Expr = None
    runs: int = 1000
    allocation: str = ""


# ── Scenarios ────────────────────────────────────────────

@dataclass
class ScenarioDef:
    """A SCENARIO block."""
    name: str = ""
    overrides: Dict[str, Expr] = field(default_factory=dict)


@dataclass
class ScenarioStmt(Statement):
    """SCENARIO "name" ... END SCENARIO (accumulated by interpreter)."""
    name: str = ""
    overrides: List[LetStmt] = field(default_factory=list)


@dataclass
class RunScenariosStmt(Statement):
    """RUN SCENARIOS ON "system" USING "method" [FROM csv] [SAVE csv]"""
    system: Expr = None
    method: Expr = None
    from_csv: Expr = None
    save_to: Expr = None
    allocation: str = ""


# ── Sensitivity ──────────────────────────────────────────

@dataclass
class SensitivityStmt(Statement):
    """SENSITIVITY block."""
    system: Expr = None
    method: Expr = None
    variation_pct: float = 20.0
    parameters: List[str] = field(default_factory=list)
    from_csv: Expr = None
    save_to: Expr = None
    allocation: str = ""


# ── Audit / validation ──────────────────────────────────

@dataclass
class ValidateStmt(Statement):
    """VALIDATE "system" [WITH CALCULATION]"""
    system: Expr = None
    with_calc: bool = False


@dataclass
class CheckStmt(Statement):
    """CHECK "system" TIER n [AGAINST "file"]"""
    system: Expr = None
    tier: int = 1
    against: Expr = None


@dataclass
class ExtractStmt(Statement):
    """EXTRACT FOLDER "path" """
    folder: Expr = None


@dataclass
class AuditStmt(Statement):
    """AUDIT FOLDER "path" """
    folder: Expr = None


# ── Delete ───────────────────────────────────────────────

@dataclass
class DeleteStmt(Statement):
    """DELETE PROCESS/FLOW/SYSTEM "ref" """
    entity_type: str = ""  # PROCESS, FLOW, SYSTEM
    ref: Expr = None


# ── Output ───────────────────────────────────────────────

@dataclass
class SaveResultsStmt(Statement):
    """SAVE RESULTS "filename" """
    filename: Expr = None


@dataclass
class ExportResultsStmt(Statement):
    """EXPORT RESULTS TO "filename" """
    filename: Expr = None


# ── Control flow ─────────────────────────────────────────

@dataclass
class IfStmt(Statement):
    """IF condition THEN ... [ELSE ...] END IF"""
    condition: Expr = None
    then_body: List[Statement] = field(default_factory=list)
    else_body: List[Statement] = field(default_factory=list)


@dataclass
class ForStmt(Statement):
    """FOR var = start TO end [STEP n] ... NEXT"""
    variable: str = ""
    start: Expr = None
    end: Expr = None
    step: Expr = None
    body: List[Statement] = field(default_factory=list)


@dataclass
class ForEachStmt(Statement):
    """FOR EACH var IN val1, val2 ... NEXT"""
    variable: str = ""
    values: List[Expr] = field(default_factory=list)
    body: List[Statement] = field(default_factory=list)


@dataclass
class WhileStmt(Statement):
    """WHILE condition ... WEND"""
    condition: Expr = None
    body: List[Statement] = field(default_factory=list)


# ── Subroutines ──────────────────────────────────────────

@dataclass
class SubDef(Statement):
    """SUB name(params) ... END SUB"""
    name: str = ""
    params: List[str] = field(default_factory=list)
    body: List[Statement] = field(default_factory=list)


@dataclass
class SubCall(Statement):
    """name arg1, arg2, ..."""
    name: str = ""
    args: List[Expr] = field(default_factory=list)


@dataclass
class FunctionDef(Statement):
    """FUNCTION name(params) AS type ... END FUNCTION"""
    name: str = ""
    params: List[str] = field(default_factory=list)
    body: List[Statement] = field(default_factory=list)


# ── File operations ──────────────────────────────────────

@dataclass
class RunFileStmt(Statement):
    """RUN "filename.baslca" """
    filename: Expr = None


@dataclass
class IncludeStmt(Statement):
    """INCLUDE "filename.baslca" """
    filename: Expr = None


# ── Find ─────────────────────────────────────────────────

@dataclass
class FindStmt(Statement):
    """LET var = FIND PROCESS/FLOW/METHOD/CHEMICAL "term" [AT "loc"]"""
    entity_type: str = ""  # PROCESS, FLOW, METHOD, CHEMICAL
    search_term: Expr = None
    location: Expr = None
    category: Expr = None
    assign_to: str = ""  # variable name to store result


# ── REPL commands ────────────────────────────────────────

@dataclass
class SetFolderStmt(Statement):
    """SET PROCESS FOLDER / SET FLOW FOLDER"""
    folder: Expr = None
    target: str = "PROCESS"  # PROCESS or FLOW


@dataclass
class CatStmt(Statement):
    """CAT/LS [path] [*pattern*] — list category contents"""
    path: Expr = None
    entity_type: str = ""  # FLOWS, PROCESSES, SYSTEMS, or empty
    filter_pattern: str = ""  # wildcard filter like *concrete*


@dataclass
class DirStmt(Statement):
    """DIR "path" — navigate to folder"""
    path: Expr = None


@dataclass
class CdStmt(Statement):
    """CD [path] — alias for DIR (undocumented)"""
    path: Expr = None


@dataclass
class UpStmt(Statement):
    """UP — go up one level"""
    pass


@dataclass
class PwdStmt(Statement):
    """PWD — show current folders"""
    pass


@dataclass
class BackStmt(Statement):
    """BACK — toggle to previous directory"""
    pass


@dataclass
class CdirStmt(Statement):
    """CDIR "name" — create a category folder"""
    name: Expr = None


@dataclass
class HelpStmt(Statement):
    topic: str = ""


@dataclass
class ClearStmt(Statement):
    pass


@dataclass
class RefreshStmt(Statement):
    pass


@dataclass
class ExitStmt(Statement):
    pass


@dataclass
class ConfirmDeleteStmt(Statement):
    """CONFIRM DELETE ON/OFF"""
    enabled: bool = True
