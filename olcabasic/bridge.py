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
            # Creating the client doesn't open a connection, so make
            # one real request before reporting success.
            info = self.lca.get_database_info()
            if info.get("status") == "error":
                logger.error(f"Connection failed: {info.get('error')}")
                self.lca = None
                return False
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

    # ── Global parameters ────────────────────────────────

    def create_global_parameter(self, name: str,
                                value: Optional[float] = None,
                                formula: Optional[str] = None,
                                description: str = "") -> Dict:
        self._require_connection()
        return self.lca.create_global_parameter(
            name, value, formula, description)

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

    @staticmethod
    def _flow_result(f, ambiguous: int = 0) -> Dict:
        r = {"flow_id": f.id, "flow_name": f.name,
             "category": getattr(f, "category", "") or "",
             "already_existed": True}
        if ambiguous:
            r["ambiguous"] = ambiguous
        return r

    @classmethod
    def _match_flow_name(cls, name: str, flows: list) -> Optional[Dict]:
        """Exact name match, else unique substring match, else None.
        Several exact matches: prefer an 'unspecified' sub-compartment
        (the conventional default), else take the first and flag it."""
        exact = [f for f in flows if f.name == name]
        if len(exact) == 1:
            return cls._flow_result(exact[0])
        if len(exact) > 1:
            unspec = [f for f in exact
                      if (getattr(f, "category", "") or "")
                      .lower().rstrip("/").endswith("unspecified")]
            best = unspec[0] if unspec else exact[0]
            return cls._flow_result(best, ambiguous=len(exact))
        lower = name.lower()
        partial = [f for f in flows if lower in f.name.lower()]
        if len(partial) == 1:
            return cls._flow_result(partial[0])
        return None

    def find_flow(self, name: str, unit: str = "",
                  category: str = "", strict: bool = False) -> Optional[Dict]:
        """Find an existing flow by name. Returns dict with flow_id or None.

        category is a case-insensitive prefix.
        strict=True (elementary flows): only flows under that prefix
        are considered; there is no fallback to the whole database.
        strict=False (product flows): flows under the prefix are
        preferred, then the whole database is searched.
        """
        self._require_connection()
        import olca_schema as o
        flows = self.lca._get_descriptors(o.Flow)

        if category:
            cat_lower = category.lower().rstrip("/")
            in_cat = [f for f in flows
                      if (getattr(f, "category", "") or "")
                      .lower().startswith(cat_lower)]
            if strict:
                return self._match_flow_name(name, in_cat)
            hit = self._match_flow_name(name, in_cat)
            if hit:
                return hit

        return self._match_flow_name(name, flows)

    def resolve_process_strict(self, ref: str) -> Dict:
        """Resolve a PROVIDER reference to exactly one process.
        Accepts a UUID or a name that matches one process only."""
        self._require_connection()
        import olca_schema as o
        procs = self.lca._get_descriptors(o.Process)
        by_id = [p for p in procs if p.id == ref]
        if by_id:
            return {"process_id": by_id[0].id}
        exact = [p for p in procs if p.name == ref]
        if len(exact) == 1:
            return {"process_id": exact[0].id}
        if len(exact) > 1:
            locs = sorted({getattr(p, "location", "") or "?" for p in exact})
            return {"error": (
                f"PROVIDER '{ref}' matches {len(exact)} processes "
                f"(locations: {', '.join(locs)}). Use LOCATION \"code\" "
                f"on the INPUT line, or give the provider's UUID.")}
        partial = [p for p in procs if ref.lower() in p.name.lower()]
        if len(partial) == 1:
            return {"process_id": partial[0].id}
        if partial:
            return {"error": f"PROVIDER '{ref}' matches {len(partial)} "
                             f"processes by partial name; be more specific"}
        return {"error": f"PROVIDER process not found: '{ref}'"}

    def find_process_qref_flow(self, process_name: str,
                                location: str = "") -> Optional[Dict]:
        """Find a process by name and return its quantitative reference
        flow ID and the process ID (for use as default provider).

        Returns None if no process matches, a dict with "error" if
        LOCATION rules something out, otherwise the match (with
        "ambiguous" set if several processes were equally good).
        """
        self._require_connection()
        import olca_schema as o

        processes = self.lca._get_descriptors(o.Process)
        exact = [p for p in processes if p.name == process_name]

        if not exact:
            # Partial match (only returns if unique)
            proc_desc = self.lca._resolve_process(process_name)
            if not proc_desc:
                return None
            exact = [proc_desc]

        if location:
            loc_lower = location.strip().lower()
            available = sorted({getattr(p, "location", "") or ""
                                for p in exact})
            filtered = [p for p in exact
                        if (getattr(p, "location", "") or "").lower()
                        == loc_lower]
            if not filtered:
                shown = ", ".join(a or "(none)" for a in available)
                if not any(available):
                    return {"error": (
                        f"LOCATION \"{location}\" given for "
                        f"'{process_name}', but no location codes came "
                        f"back from openLCA for these processes, so it "
                        f"can't be used to choose. Use PROVIDER with a "
                        f"UUID instead.")}
                return {"error": (
                    f"No '{process_name}' with LOCATION \"{location}\". "
                    f"Available: {shown}")}
            exact = filtered

        proc_desc = exact[0]
        ambiguous = len(exact) if len(exact) > 1 else 0

        proc = self.lca.client.get(o.Process, proc_desc.id)
        if not proc or not proc.exchanges:
            return None
        for ex in proc.exchanges:
            if getattr(ex, "is_quantitative_reference", False) and ex.flow:
                result = {
                    "flow_id": ex.flow.id,
                    "flow_name": ex.flow.name,
                    "process_id": proc_desc.id,
                    "process_name": proc_desc.name,
                    "location": getattr(proc_desc, "location", "") or "",
                    "unit": ex.unit.name if ex.unit else "",
                }
                if ambiguous:
                    result["ambiguous"] = ambiguous
                return result
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
                    # Whole segments only: "31" must not match
                    # "31-33: Manufacturing", "Test" not "Test Model"
                    if not (cat_lower == path_lower or
                            cat_lower.startswith(path_lower + "/")):
                        continue
                    remainder = cat[len(path_lower):].strip("/")
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
