"""
Bridge between olcaBASIC and openLCA via LCAFunctions.

Translates interpreted BASIC commands into LCAFunctions method
calls. This is the only file that imports olca-ipc.
"""

from typing import Dict, Optional, Any, List
import logging

logger = logging.getLogger("olcaBASIC")


class LCABridge:
    """Adapter between olcaBASIC interpreter and LCAFunctions."""

    def __init__(self, port: int = 8080):
        self.port = port
        self.lca = None
        self._connected = False

    def connect(self) -> bool:
        """Connect to openLCA IPC server."""
        try:
            from olca_ipc import Client
            from b280_olca_mcp.functions import LCAFunctions

            client = Client(self.port)
            self.lca = LCAFunctions(client)
            self._connected = True
            return True
        except ImportError:
            logger.error(
                "b280-olca-mcp not installed. "
                "Run: pip install b280-olca-mcp"
            )
            return False
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    @property
    def connected(self) -> bool:
        return self._connected and self.lca is not None

    def _require_connection(self):
        if not self.connected:
            raise RuntimeError(
                "Not connected to openLCA. "
                "Start the IPC server in openLCA first."
            )

    # ── Database info ────────────────────────────────────

    def database_info(self) -> Dict:
        self._require_connection()
        return self.lca.get_database_info()

    def set_database_family(self, family: str) -> Dict:
        self._require_connection()
        return self.lca.set_database_family(family)

    # ── Search ───────────────────────────────────────────

    def search_processes(self, term: str, category: str = "",
                         location: str = "",
                         limit: int = 20) -> Dict:
        self._require_connection()
        return self.lca.search_processes(term, category, location, limit)

    def search_flows(self, term: str = "", category: str = "",
                     limit: int = 20) -> Dict:
        self._require_connection()
        return self.lca.search_flows(term, category, limit)

    def list_methods(self, term: str = "") -> Dict:
        self._require_connection()
        return self.lca.list_impact_methods(term)

    def list_systems(self, term: str = "") -> Dict:
        self._require_connection()
        return self.lca.list_product_systems(term)

    def get_process_details(self, ref: str) -> Dict:
        self._require_connection()
        # Try by name first, then by ID
        proc = self.lca._resolve_process(ref)
        if proc:
            return self.lca.get_process_details(proc.id)
        return self.lca.get_process_details(ref)

    def get_system_parameters(self, ref: str,
                               name_filter: str = "") -> Dict:
        self._require_connection()
        return self.lca.get_system_parameters(ref, name_filter)

    def get_global_parameters(self, name_filter: str = "") -> Dict:
        self._require_connection()
        return self.lca.get_global_parameters(name_filter)

    def get_data_quality(self, ref: str) -> Dict:
        self._require_connection()
        proc = self.lca._resolve_process(ref)
        if proc:
            return self.lca.get_data_quality(proc.id)
        return self.lca.get_data_quality(ref)

    def get_system_links(self, ref: str, search: str = "",
                          limit: int = 50) -> Dict:
        self._require_connection()
        return self.lca.get_system_links(ref, search, limit)

    def find_unit(self, name: str) -> Dict:
        self._require_connection()
        return self.lca.find_unit(name)

    def list_dq_systems(self) -> Dict:
        self._require_connection()
        return self.lca.list_dq_systems()

    def chemical_synonyms(self, name: str) -> Dict:
        self._require_connection()
        return self.lca.chemical_synonyms(name)

    # ── Flow creation ────────────────────────────────────

    def create_flow(self, name: str, unit: str,
                    category: str = "",
                    flow_type: str = "product") -> Dict:
        self._require_connection()
        return self.lca.create_flow(name, unit, category, flow_type)

    # ── Bridge creation ──────────────────────────────────

    def create_bridge(self, name: str, unit: str,
                      category: str = "",
                      provider_id: Optional[str] = None,
                      provider_flow_id: Optional[str] = None,
                      waste: bool = False) -> Dict:
        self._require_connection()
        return self.lca.create_bridge(
            name, unit, category, provider_id, provider_flow_id, waste)

    def resolve_process(self, name_or_id: str) -> Optional[str]:
        """Resolve a process name to its UUID."""
        self._require_connection()
        proc = self.lca._resolve_process(name_or_id)
        return proc.id if proc else None

    # ── Process creation ─────────────────────────────────

    def create_process(self, name: str, category: str,
                       exchanges: List[Dict],
                       parameters: Optional[List[Dict]] = None,
                       description: str = "",
                       location: Optional[str] = None,
                       flow_schema: Optional[str] = None,
                       process_schema: Optional[str] = None) -> Dict:
        self._require_connection()
        return self.lca.create_process(
            name, category, exchanges, parameters,
            description, location, flow_schema, process_schema)

    def edit_process(self, process_id: str, **kwargs) -> Dict:
        self._require_connection()
        return self.lca.edit_process(process_id, **kwargs)

    # ── System creation ──────────────────────────────────

    def create_system(self, process_ref: str,
                      linking: str = "prefer_defaults",
                      target_amount=None, target_unit=None,
                      target_flow_property=None,
                      category=None) -> Dict:
        self._require_connection()
        return self.lca.create_product_system(
            process_ref, linking, target_amount,
            target_unit, target_flow_property, category)

    # ── Calculations ─────────────────────────────────────

    def calculate(self, system_ref: str, method_ref: str,
                  allocation: str = "") -> Dict:
        self._require_connection()
        if allocation:
            return self.lca.calculate_impacts(system_ref, method_ref, allocation.lower())
        return self.lca.calculate_impacts(system_ref, method_ref)

    def contribution(self, system_ref: str, method_ref: str,
                     top: int = 10,
                     categories: Optional[List[str]] = None,
                     allocation: str = "") -> Dict:
        self._require_connection()
        kwargs = {"categories": categories, "max_contributors": top}
        if allocation:
            kwargs["allocation"] = allocation.lower()
        return self.lca.contribution_analysis(system_ref, method_ref, **kwargs)

    def inventory(self, system_ref: str, method_ref: str,
                  max_flows: int = 50,
                  allocation: str = "") -> Dict:
        self._require_connection()
        kwargs = {"max_flows": max_flows}
        if allocation:
            kwargs["allocation"] = allocation.lower()
        return self.lca.inventory_flows(system_ref, method_ref, **kwargs)

    def monte_carlo(self, system_ref: str, method_ref: str,
                    iterations: int = 1000,
                    allocation: str = "") -> Dict:
        self._require_connection()
        if allocation:
            return self.lca.monte_carlo(system_ref, method_ref, iterations, allocation.lower())
        return self.lca.monte_carlo(system_ref, method_ref, iterations)

    def run_scenarios(self, system_ref: str, method_ref: str,
                      scenarios: Dict,
                      allocation: str = "") -> Dict:
        self._require_connection()
        if allocation:
            return self.lca.run_scenarios(system_ref, method_ref, scenarios, allocation.lower())
        return self.lca.run_scenarios(system_ref, method_ref, scenarios)

    def run_sensitivity(self, system_ref: str, method_ref: str,
                        parameters: List[str],
                        variation_pct: float = 20.0,
                        allocation: str = "") -> Dict:
        self._require_connection()
        if allocation:
            return self.lca.run_sensitivity(system_ref, method_ref, parameters, variation_pct, allocation.lower())
        return self.lca.run_sensitivity(system_ref, method_ref, parameters, variation_pct)

    # ── Audit ────────────────────────────────────────────

    def validate_system(self, ref: str,
                         test_calculate: bool = False) -> Dict:
        self._require_connection()
        return self.lca.validate_system(ref, test_calculate)

    def audit_model(self, category: str) -> Dict:
        self._require_connection()
        return self.lca.audit_model(category)

    def extract_model(self, category: str) -> Dict:
        self._require_connection()
        return self.lca.extract_model(category)

    # ── Delete ───────────────────────────────────────────

    def delete_entity(self, entity_type: str,
                       entity_id: str) -> Dict:
        self._require_connection()
        return self.lca.delete_entity(entity_type, entity_id)

    # ── Resolve helpers ──────────────────────────────────

    def resolve_flow_id(self, name: str, unit: str = "",
                         category: str = "",
                         flow_type: str = "product") -> Optional[str]:
        """Find or create a flow by name and return its ID."""
        self._require_connection()
        result = self.lca.create_flow(name, unit, category, flow_type)
        if "error" in result:
            return None
        return result.get("flow_id")

    def refresh_caches(self):
        """Clear internal caches to force re-read from openLCA."""
        if self.lca:
            self.lca._cache.clear()
            self.lca._cache_ts.clear()
