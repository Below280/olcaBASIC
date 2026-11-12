"""
The connection between the olcaBASIC interpreter and the engine.

LCABridge opens the connection to openLCA and hands every call on to
the Engine. It holds no logic of its own: name resolution, checks and
everything else that touches openLCA live in olcabasic.engine. What is
left here is the connection, the "not connected" refusal, and the
command-shaped argument names the interpreter uses.
"""

from typing import Dict, List, Optional
import logging

logger = logging.getLogger("olcaBASIC")

# Interpreter name -> engine method, where they differ.
_RENAMED = {
    "database_info": "get_database_info",
    "list_methods": "list_impact_methods",
    "list_systems": "list_product_systems",
    "get_process_details": "get_process_details_by_ref",
    "get_data_quality": "get_data_quality_by_ref",
    "create_system": "create_product_system",
    "refresh_caches": "clear_caches",
}


class LCABridge:
    """Adapter between the olcaBASIC interpreter and the Engine."""

    def __init__(self, port: int = 8080, engine=None):
        self.port = port
        self.engine = engine
        self._connected = engine is not None

    # The engine was called "lca" up to v0.3.0.
    @property
    def lca(self):
        return self.engine

    @lca.setter
    def lca(self, value):
        self.engine = value

    def connect(self) -> bool:
        """Connect to openLCA's IPC server."""
        try:
            from olca_ipc import Client
            from .engine import Engine

            client = Client(self.port)
            self.engine = Engine(client)
            # Creating the client doesn't open a connection, so make
            # one real request before reporting success.
            info = self.engine.get_database_info()
            if info.get("status") == "error":
                logger.error(f"Connection failed: {info.get('error')}")
                self.engine = None
                return False
            self._connected = True
            return True
        except ImportError:
            logger.error("olca-ipc is not installed. Run: pip install olca-ipc")
            return False
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    @property
    def connected(self) -> bool:
        return self._connected and self.engine is not None

    def _require_connection(self):
        if not self.connected:
            raise RuntimeError(
                "Not connected to openLCA. "
                "Start the IPC server in openLCA first."
            )

    def __getattr__(self, name):
        """Every other call goes straight to the engine's public API."""
        if name.startswith("_"):
            raise AttributeError(name)
        self._require_connection()
        return getattr(self.engine, _RENAMED.get(name, name))

    # ── Calls whose arguments are named after the command ─────

    def upstream_tree(self, system_ref: str, method_ref: str,
                      category: str, levels: int = 3, top: int = 5,
                      allocation: str = "", with_quality: bool = True,
                      result_handle: Optional[str] = None) -> Dict:
        self._require_connection()
        return self.engine.upstream_tree(
            system_ref, method_ref, category, levels, top,
            allocation=allocation or None, with_quality=with_quality,
            result_handle=result_handle)

    def calculate(self, system_ref: str, method_ref: str,
                  allocation: str = "") -> Dict:
        self._require_connection()
        return self.engine.calculate_impacts(
            system_ref, method_ref, allocation or None)

    def contribution(self, system_ref: str, method_ref: str,
                     top: int = 10,
                     categories: Optional[List[str]] = None,
                     allocation: str = "",
                     result_handle: Optional[str] = None) -> Dict:
        self._require_connection()
        return self.engine.contribution_analysis(
            system_ref, method_ref, categories=categories,
            max_contributors=top, allocation=allocation or None,
            result_handle=result_handle)

    def inventory(self, system_ref: str, method_ref: str,
                  max_flows: int = 50, allocation: str = "",
                  result_handle: Optional[str] = None) -> Dict:
        self._require_connection()
        return self.engine.inventory_flows(
            system_ref, method_ref, max_flows=max_flows,
            allocation=allocation or None, result_handle=result_handle)

    def monte_carlo(self, system_ref: str, method_ref: str,
                    iterations: int = 1000, allocation: str = "",
                    trial: bool = False) -> Dict:
        self._require_connection()
        return self.engine.monte_carlo(
            system_ref, method_ref, iterations, allocation or None,
            trial=trial)

    def run_scenarios(self, system_ref: str, method_ref: str,
                      scenarios: Dict, allocation: str = "") -> Dict:
        self._require_connection()
        return self.engine.run_scenarios(
            system_ref, method_ref, scenarios, allocation or None)

    def run_scenarios_csv(self, system_ref: str, method_ref: str,
                          csv_path: str, save_to: str = "",
                          allocation: str = "") -> Dict:
        self._require_connection()
        return self.engine.run_scenarios_csv(
            system_ref, method_ref, csv_path, save_to, allocation or None)

    def run_sensitivity(self, system_ref: str, method_ref: str,
                        parameters: List[str],
                        variation_pct: float = 20.0,
                        allocation: str = "") -> Dict:
        self._require_connection()
        return self.engine.run_sensitivity(
            system_ref, method_ref, parameters, variation_pct,
            allocation or None)

    def run_sensitivity_csv(self, system_ref: str, method_ref: str,
                            csv_path: str, variation_pct: float = 20.0,
                            save_to: str = "", allocation: str = "") -> Dict:
        self._require_connection()
        return self.engine.run_sensitivity_csv(
            system_ref, method_ref, csv_path, variation_pct, save_to,
            allocation or None)
