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

    def find_flow(self, name: str, unit: str = "",
                  category: str = "") -> Optional[Dict]:
        """Find an existing flow by name. Returns dict with flow_id or None."""
        self._require_connection()
        import olca_schema as o
        flows = self.lca._get_descriptors(o.Flow)
        for f in flows:
            if f.name == name:
                return {"flow_id": f.id, "flow_name": f.name,
                        "already_existed": True}
        # Substring match fallback
        for f in flows:
            if name.lower() in f.name.lower():
                return {"flow_id": f.id, "flow_name": f.name,
                        "already_existed": True}
        return None

    def find_process_qref_flow(self, process_name: str) -> Optional[Dict]:
        """Find a process by name and return its quantitative reference
        flow ID and the process ID (for use as default provider)."""
        self._require_connection()
        import olca_schema as o
        proc_desc = self.lca._resolve_process(process_name)
        if not proc_desc:
            return None
        proc = self.lca.client.get(o.Process, proc_desc.id)
        if not proc or not proc.exchanges:
            return None
        for ex in proc.exchanges:
            if getattr(ex, "is_quantitative_reference", False) and ex.flow:
                return {
                    "flow_id": ex.flow.id,
                    "flow_name": ex.flow.name,
                    "process_id": proc_desc.id,
                    "process_name": proc_desc.name,
                    "unit": ex.unit.name if ex.unit else "",
                }
        return None

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

    def list_category_contents(self, path: str = "",
                                entity_type: str = "") -> Dict:
        """List processes, flows, or systems in a category folder.
        Returns immediate children (subfolders and entities)."""
        self._require_connection()
        import olca_schema as o

        # Decide which entity types to scan
        types_to_scan = []
        if entity_type == "FLOWS":
            types_to_scan = [(o.Flow, "flow")]
        elif entity_type == "SYSTEMS":
            types_to_scan = [(o.ProductSystem, "system")]
        elif entity_type == "PROCESSES":
            types_to_scan = [(o.Process, "process")]
        else:
            types_to_scan = [
                (o.Process, "process"),
                (o.Flow, "flow"),
                (o.ProductSystem, "system"),
            ]

        subfolders = set()
        entities = []
        path_lower = path.lower().rstrip("/") if path else ""

        for otype, label in types_to_scan:
            for desc in self.lca._get_descriptors(otype):
                cat = getattr(desc, "category", "") or ""
                cat_lower = cat.lower()

                if path_lower:
                    if not cat_lower.startswith(path_lower):
                        continue
                    remainder = cat[len(path):].strip("/")
                else:
                    remainder = cat

                if not remainder:
                    # Entity is directly in this folder
                    entities.append({
                        "name": desc.name,
                        "type": label,
                        "category": cat,
                    })
                else:
                    # Entity is in a subfolder
                    top_segment = remainder.split("/")[0]
                    if path:
                        subfolders.add(path.rstrip("/") + "/" + top_segment)
                    else:
                        subfolders.add(top_segment)

        return {
            "path": path or "(root)",
            "subfolders": sorted(subfolders),
            "entities": entities[:50],
            "entity_count": len(entities),
            "subfolder_count": len(subfolders),
        }
