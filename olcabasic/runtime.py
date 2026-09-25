"""
Runtime state for olcaBASIC.

Manages variables, scopes, the DATA queue, SUB/FUNCTION
definitions, and results storage.
"""

from typing import Any, Dict, List, Optional
from collections import deque


class Scope:
    """A variable scope (global or local)."""

    def __init__(self, parent: Optional["Scope"] = None):
        self.variables: Dict[str, Any] = {}
        self.parent = parent

    def get(self, name: str) -> Any:
        if name in self.variables:
            return self.variables[name]
        if self.parent:
            return self.parent.get(name)
        raise NameError(f"Variable '{name}' is not defined")

    def set(self, name: str, value: Any):
        self.variables[name] = value

    def has(self, name: str) -> bool:
        if name in self.variables:
            return True
        if self.parent:
            return self.parent.has(name)
        return False

    def all_variables(self) -> Dict[str, Any]:
        """Get all variables visible from this scope."""
        result = {}
        if self.parent:
            result.update(self.parent.all_variables())
        result.update(self.variables)
        return result


class Runtime:
    """Runtime state for the olcaBASIC interpreter."""

    def __init__(self):
        self.global_scope = Scope()
        self.current_scope = self.global_scope

        # Default folders for created entities
        self.process_folder: str = ""
        self.flow_folder: str = ""
        self.previous_folder: str = ""  # for BACK command

        # DATA queue for DATA/READ statements
        self.data_queue: deque = deque()

        # SUB and FUNCTION definitions
        self.subs: Dict[str, Any] = {}      # name → SubDef node
        self.functions: Dict[str, Any] = {}  # name → FunctionDef node

        # Most recent calculation results
        self.last_results: Optional[Dict] = None
        self.last_results_type: str = ""  # calculate, scenarios, etc.

        # Expressions for variables defined from other variables
        # (LET water_mass = cement_mass * ratio). These become
        # formula parameters in openLCA so they follow scenarios.
        self.var_exprs: Dict[str, Any] = {}

        # Global parameters already written to openLCA this session:
        # name -> ("value", v) or ("formula", f)
        self.synced_globals: Dict[str, tuple] = {}

        # Scenario accumulator
        self.scenarios: Dict[str, Dict[str, float]] = {}

        # Confirm delete flag
        self.confirm_delete: bool = False

        # Error handling mode
        self.error_mode: str = "STOP"  # STOP, PRINT, SKIP

    def push_scope(self) -> Scope:
        """Create a new local scope."""
        new_scope = Scope(parent=self.current_scope)
        self.current_scope = new_scope
        return new_scope

    def pop_scope(self):
        """Return to the parent scope."""
        if self.current_scope.parent:
            self.current_scope = self.current_scope.parent

    def get_var(self, name: str) -> Any:
        return self.current_scope.get(name)

    def set_var(self, name: str, value: Any):
        self.current_scope.set(name, value)

    def has_var(self, name: str) -> bool:
        return self.current_scope.has(name)

    def get_global_vars(self) -> Dict[str, Any]:
        """Get all global-scope variables (for parameter export)."""
        return dict(self.global_scope.variables)

    def get_numeric_globals(self) -> Dict[str, float]:
        """Get global variables that are numeric (for openLCA parameters)."""
        return {
            k: v for k, v in self.global_scope.variables.items()
            if isinstance(v, (int, float)) and not k.endswith("$")
        }

    # ── DATA queue ───────────────────────────────────────

    def push_data(self, *values):
        """Add values to the DATA queue."""
        for v in values:
            self.data_queue.append(v)

    def read_data(self) -> Any:
        """Read one value from the DATA queue."""
        if not self.data_queue:
            raise RuntimeError("No more DATA to READ")
        return self.data_queue.popleft()

    def has_data(self) -> bool:
        return len(self.data_queue) > 0

    def clear_data(self):
        self.data_queue.clear()

    # ── Results ──────────────────────────────────────────

    def store_results(self, results: Dict, results_type: str = ""):
        self.last_results = results
        self.last_results_type = results_type

    # ── Reset ────────────────────────────────────────────

    def reset(self):
        """Clear all state (for NEW command)."""
        self.global_scope = Scope()
        self.current_scope = self.global_scope
        self.process_folder = ""
        self.flow_folder = ""
        self.previous_folder = ""
        self.data_queue.clear()
        self.subs.clear()
        self.functions.clear()
        self.last_results = None
        self.last_results_type = ""
        self.scenarios.clear()
        self.var_exprs.clear()
        self.synced_globals.clear()
        self.confirm_delete = False
