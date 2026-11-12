# The engine

`olcabasic.engine.Engine` is the layer that talks to openLCA through `olca-ipc`. The interpreter, `Session` and the MCP server all go through it. It is the class that was `b280_olca_mcp.functions.LCAFunctions` up to B280-olca-MCP 1.16 (`LCAFunctions` is kept as an alias).

```python
from olca_ipc import Client
from olcabasic.engine import Engine

engine = Engine(Client(8080))
engine.search_processes("cement", limit=5)
```

Most methods return a dictionary, and report a failure as `{"error": "..."}` and not as an exception. Names that start with an underscore are private and may change.

For most uses `olcabasic.Session` is the better entry point: it runs programs, serialises access to openLCA and applies the language's rules. The engine applies none of them: it will, for example, accept part of a method name.

## Public methods (67)

This list is generated from the code: `python docs/make_engine_doc.py`.

| Method | What it does |
|---|---|
| `audit_model(category: str)` | Run structural checks on all processes in a category folder |
| `cache_size()` | Number of cached entries (descriptor lists and unit lookups) |
| `calculate_impacts(system_ref: str, method_ref: str, allocation: Optional[str] = None)` | Run a baseline impact calculation for a product system |
| `chemical_synonyms(chemical_name: str, search_database: bool = True, max_synonyms: int = 20)` | Look up chemical synonyms via PubChem (US NIH, free, no key) |
| `clear_caches()` | Forget cached descriptor lists so the next call reads them from openLCA again |
| `contribution_analysis(system_ref: str, method_ref: str, threshold_pct: float = 0.1, max_contributors: int = 30, categories: Optional[List[str]] = None, allocation: Optional[str] = None)` | Process-level contribution analysis |
| `create_bridge(name: str, unit_name: str, category: str = '', provider_id: Optional[str] = None, provider_flow_id: Optional[str] = None, waste: bool = False)` | Create a bridge flow AND bridge process in one call |
| `create_flow(name: str, unit_name: str, category: str = '', flow_type: str = 'product')` | Create a flow, or return the existing one if a flow with the same name and category already exists |
| `create_global_parameter(name: str, value: Optional[float] = None, formula: Optional[str] = None, description: str = '')` | Create or update a global (database-level) parameter |
| `create_process(name: str, category: str, exchanges: List[Dict], parameters: Optional[List[Dict]] = None, description: str = '', location: Optional[str] = None, flow_schema: Optional[str] = None, process_schema: Optional[str] = None)` | Create a process, or return the existing one if a process with the same name and category already exists |
| `create_product_system(process_ref: str, linking: str = 'prefer_defaults', target_amount: Optional[float] = None, target_unit: Optional[str] = None, target_flow_property: Optional[str] = None, category: Optional[str] = None)` | Create a product system from a process |
| `delete_entity(entity_type: str, entity_id: str, usage_checked: bool = False, prefer_categories=None)` | Delete a process, flow, or product system from the database |
| `describe_process(process_id: str)` | {"id", "name", "location", "category"} of a process, from its descriptor (no full read) |
| `edit_flow(flow_id: str, operations: List[Dict])` | Add or update a flow's properties, or change its reference property |
| `edit_process(process_id: str, add_exchanges: Optional[List[Dict]] = None, update_exchanges: Optional[List[Dict]] = None, remove_exchanges: Optional[List[str]] = None, add_parameters: Optional[List[Dict]] = None, update_parameters: Optional[Dict[str, float]] = None, description: Optional[str] = None, category: Optional[str] = None, location: Optional[str] = None)` | Edit an existing process in place |
| `extract_model(category: str)` | Extract all processes within a category folder and its subfolders |
| `find_flow(name: str, unit: str = '', category='', strict: bool = False)` | Find an existing flow by name |
| `find_flow_usage(flow_id: str, max_hits: int = 10, progress=None, prefer_categories=None, workers: int = 8)` | Find where a flow is used |
| `find_method(ref: str)` | Descriptor of an impact method by UUID, name or unique part of a name |
| `find_method_strict(ref: str)` | An impact method by UUID or by its full name |
| `find_process(ref: str)` | Descriptor of the process with this UUID or exact name, or the single process whose name contains it |
| `find_process_qref_flow(process_name: str, location: str = '')` | Find a process by name and return its quantitative reference flow ID and the process ID (for use as default provider) |
| `find_system(ref: str)` | Descriptor of a product system by UUID, name or unique part of a name |
| `find_unit(unit_name: str)` | Look up a unit and its flow property by name |
| `folder_exists(path: str, entity_type: str = '')` | True if any entity of this type (any type if empty) sits in this folder or below it (whole path segments) |
| `get_data_quality(process_id: str)` | Extract pedigree matrix / data quality entries for a process and all its exchanges |
| `get_data_quality_by_ref(ref: str)` | get_data_quality for a name or a UUID |
| `get_database_info()` | Counts of key entities in the connected database |
| `get_descriptors(entity_type)` | Descriptors (id, name, category and so on) of every entity of one olca_schema type |
| `get_flow_details(flow_id: str)` | A flow with its properties, factors and reference units |
| `get_global_parameters(name_filter: str = '', limit: int = 50)` | Look up global (database-level) parameters |
| `get_method_categories(method_ref: str)` | The impact categories of a method, in the method's order |
| `get_process_details(process_id: str)` | Full process information including exchanges and parameters |
| `get_process_details_by_ref(ref: str)` | get_process_details for a name or a UUID |
| `get_process_object(process_id: str)` | The full openLCA process (exchanges with flow and provider references), for EDIT to match exchanges by name |
| `get_process_tags(process_id: str, prefix: str = '')` | The tags of a process that have the form 'key=value' (and, if prefix is given, start with 'prefix:'), as {key |
| `get_system_links(system_ref: str, search_term: str = '', limit: int = 50)` | Show which providers are linked to which exchanges in a product system |
| `get_system_parameters(system_ref: str, name_filter: str = '')` | List parameters for a product system, with optional name filter |
| `inventory_flows(system_ref: str, method_ref: str, threshold: float = 1e-10, max_flows: int = 50, allocation: Optional[str] = None)` | Get elementary flow inventory results (LCI) |
| `list_category_contents(path: str = '', entity_type: str = '')` | List processes, flows, or systems in a category folder |
| `list_dq_systems()` | List all DQ (Data Quality) systems in the database |
| `list_impact_methods(search_term: str = '')` | List impact methods, optionally those whose name contains search_term |
| `list_product_systems(search_term: str = '')` | List product systems, optionally those whose name contains search_term |
| `monte_carlo(system_ref: str, method_ref: str, iterations: int = 1000, allocation: Optional[str] = None)` | Run Monte Carlo uncertainty simulation |
| `move_entity(entity_type: str, entity_id: str, category: str)` | Move a process, flow or product system to another folder |
| `parameterise_process(process_id: str, dry_run: bool = False)` | Replace the fixed amounts of a process with parameters |
| `process_candidates(name: str, location: str = '')` | Every process called exactly this (optionally at one location code), as [{"id", "name", "location", "category"}], sorted by location |
| `process_contributions(system_ref: str, method_ref: str, direct: Optional[List[str]] = None, upstream: Optional[List[str]] = None, allocation: Optional[str] = None, parameters: Optional[Dict[str, float]] = None)` | One calculation, then the contribution of named processes to every impact category |
| `process_structure(process_id: str)` | How a process is wired, from one read |
| `processes_in_folder(path: str, deep: bool = True)` | Every process in a folder (and, with deep, in the folders below it), as [{"id", "name", "location", "category"}] sorted by category then name |
| `read_scenarios_csv(csv_path: str)` | Read a scenarios CSV file |
| `read_sensitivity_csv(csv_path: str)` | Read a sensitivity CSV file |
| `resolve_entity_strict(entity_type: str, ref: str)` | Resolve a process, flow or product_system name (or UUID) to exactly one ID |
| `resolve_flow_id(name: str, unit: str = '', category: str = '', flow_type: str = 'product')` | Find or create a flow by name and return its ID |
| `resolve_process(name_or_id: str)` | UUID of the process with this UUID, exact name or unique partial name |
| `resolve_process_strict(ref: str)` | Resolve a PROVIDER reference to exactly one process |
| `run_scenarios(system_ref: str, method_ref: str, scenarios: Dict[str, Dict[str, float]], allocation: Optional[str] = None)` | Run scenario calculations |
| `run_scenarios_csv(system_ref: str, method_ref: str, csv_path: str, output_path: str = '', allocation: Optional[str] = None)` | Full scenario pipeline |
| `run_sensitivity(system_ref: str, method_ref: str, parameter_names: List[str], variation_pct: float = 20.0, allocation: Optional[str] = None)` | Run +/- sensitivity analysis on named parameters |
| `run_sensitivity_csv(system_ref: str, method_ref: str, csv_path: str, variation_pct: float = 20.0, output_path: str = '', allocation: Optional[str] = None)` | Full sensitivity pipeline |
| `search_flows(search_term: str = '', category_filter: str = '', limit: int = 20)` | Search flows by name and/or category folder |
| `search_processes(search_term: str, category_filter: str = '', location_filter: str = '', limit: int = 20, with_location: bool = False)` | Search processes by name, category, and/or location |
| `set_database_family(family: str)` | Set the database family manually from user input |
| `set_process_tags(process_id: str, tags: Dict[str, Any], prefix: str = '', documentation: Optional[Dict[str, str]] = None)` | Set 'prefix:key=value' tags on a process, replacing any tag with the same prefix and key |
| `set_switched_provider(process_id: str, provider_id: str, parameter: str)` | Give a bridge a second provider that a global parameter switches to |
| `upstream_tree(system_ref: str, method_ref: str, category: str, levels: int = 3, top: int = 5, allocation: Optional[str] = None, with_quality: bool = True)` | Multi-level contribution tree for one impact category, walked with openLCA's upstream tree (result.get_upstream_impacts_of) |
| `validate_system(system_ref: str, test_calculate: bool = False)` | Validate a product system structure |
