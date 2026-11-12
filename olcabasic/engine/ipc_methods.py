"""
Every method of openLCA's IPC server (JSON-RPC, port 8080).

The list comes from the request handlers of the server itself (the
olca-ipc module of GreenDelta's olca-modules, the @Rpc annotations in
DataHandler, ResultHandler, ExportHandler and RuntimeHandler), compared
with the olca-ipc Python client. Each entry gives the client function
that wraps the method (None when the client has none, in which case the
engine calls it through client.rpc_call) and the first openLCA version
whose server has it.

A test (tests/test_ipc_coverage.py) checks that every method here is
used by at least one command in the registry, and that every method the
installed olca-ipc client calls is in this list.
"""

from typing import Dict, NamedTuple, Optional


class IpcMethod(NamedTuple):
    client: Optional[str]     # olca-ipc function, None if the client lacks it
    since: str = "2.0"        # first openLCA version with the method
    note: str = ""


# Methods the server did not always have. A server that lacks one answers
# "Does not understand"; the engine then says which openLCA version is
# needed instead of failing obscurely.
IPC_METHODS: Dict[str, IpcMethod] = {
    # ── data ────────────────────────────────────────────────
    "data/create/system": IpcMethod("create_product_system"),
    "data/delete": IpcMethod("delete"),
    "data/get": IpcMethod("get"),
    "data/get/all": IpcMethod("get_all"),
    "data/get/descriptor": IpcMethod("get_descriptor"),
    "data/get/descriptors": IpcMethod("get_descriptors"),
    "data/get/parameters": IpcMethod("get_parameters"),
    "data/get/providers": IpcMethod("get_providers"),
    "data/get/usage": IpcMethod(
        None, "2.7", "where an entity is used; not in the client"),
    "data/put": IpcMethod("put"),
    "data/put/source-file": IpcMethod("put_source_file", "2.6.2"),
    # ── export and runtime ──────────────────────────────────
    "export/json-ld": IpcMethod(
        None, note="writes a JSON-LD zip on the machine openLCA runs on; "
                   "not in the client"),
    "runtime/shutdown": IpcMethod(
        None, note="stops the IPC server and closes the database; not in "
                   "the client"),
    # ── results ─────────────────────────────────────────────
    "result/calculate": IpcMethod("calculate"),
    "result/cost-contributions": IpcMethod("get_cost_contributions"),
    "result/cost-intensities-of": IpcMethod(
        "get_cost_intensities_of", note="the server answers with a bare number, which the "
        "client's wrapper cannot read; the engine calls it directly"),
    "result/demand": IpcMethod("get_demand"),
    "result/direct-costs-of": IpcMethod(
        "get_direct_costs_of", note="the server answers with a bare number, which the "
        "client's wrapper cannot read; the engine calls it directly"),
    "result/direct-impact-of": IpcMethod("get_direct_impact_of"),
    "result/direct-impacts-of": IpcMethod("get_direct_impacts_of"),
    "result/direct-intervention-of": IpcMethod("get_direct_intervention_of"),
    "result/direct-interventions-of": IpcMethod("get_direct_interventions_of"),
    "result/dispose": IpcMethod("dispose"),
    "result/envi-flows": IpcMethod("get_envi_flows"),
    "result/flow-contributions-of": IpcMethod("get_flow_contributions_of"),
    "result/flow-impact-of": IpcMethod("get_flow_impact_of"),
    "result/flow-impacts-of": IpcMethod("get_flow_impacts_of"),
    "result/flow-intensities-of": IpcMethod("get_flow_intensities_of"),
    "result/flow-intensity-of": IpcMethod("get_flow_intensity_of"),
    "result/grouped-cost-results": IpcMethod("get_grouped_cost_results"),
    "result/grouped-flow-results-of": IpcMethod("get_grouped_flow_results_of"),
    "result/grouped-impact-results-of": IpcMethod(
        "get_grouped_impact_results_of"),
    "result/impact-categories": IpcMethod("get_impact_categories"),
    "result/impact-contributions-of": IpcMethod("get_impact_contributions_of"),
    "result/impact-factor-of": IpcMethod("get_impact_factor_of"),
    "result/impact-factors-of": IpcMethod("get_impact_factors_of"),
    "result/impact-intensities-of": IpcMethod(
        None, note="the client's get_impact_intensities_of calls "
                   "result/total-impacts-of-one, which the server does not "
                   "have; the engine calls this method directly"),
    "result/impact-intensity-of": IpcMethod("get_impact_intensity_of"),
    "result/sankey": IpcMethod("get_sankey_graph"),
    "result/scaled-tech-flows-of": IpcMethod("get_scaled_tech_flows_of"),
    "result/scaling-factors": IpcMethod("get_scaling_factors"),
    "result/simulate": IpcMethod("simulate"),
    "result/simulate/next": IpcMethod("simulate_next"),
    "result/state": IpcMethod("get_state"),
    "result/tag-results-of-costs": IpcMethod(
        None, "2.7", "results by process tag; not in the client"),
    "result/tag-results-of-flow": IpcMethod(
        None, "2.7", "results by process tag; not in the client"),
    "result/tag-results-of-impact": IpcMethod(
        None, "2.7", "results by process tag; not in the client"),
    "result/tech-flows": IpcMethod("get_tech_flows"),
    "result/total-costs": IpcMethod("get_total_costs"),
    "result/total-costs-of": IpcMethod(
        "get_total_costs_of", note="the server answers with a bare number, which the "
        "client's wrapper cannot read; the engine calls it directly"),
    "result/total-flow-value-of": IpcMethod("get_total_flow_value_of"),
    "result/total-flows": IpcMethod("get_total_flows"),
    "result/total-impact-of": IpcMethod("get_total_impact_of"),
    "result/total-impact-value-of": IpcMethod("get_total_impact_value_of"),
    "result/total-impacts": IpcMethod("get_total_impacts"),
    "result/total-impacts-of": IpcMethod("get_total_impacts_of"),
    "result/total-impacts/normalized": IpcMethod("get_normalized_impacts"),
    "result/total-impacts/weighted": IpcMethod("get_weighted_impacts"),
    "result/total-intervention-of": IpcMethod("get_total_intervention_of"),
    "result/total-interventions-of": IpcMethod("get_total_interventions_of"),
    "result/total-requirements": IpcMethod("get_total_requirements"),
    "result/total-requirements-of": IpcMethod("get_total_requirements_of"),
    "result/totality-factor-of": IpcMethod(None, note="not in the client"),
    "result/totality-factors": IpcMethod(None, note="not in the client"),
    "result/unscaled-tech-flows-of": IpcMethod("get_unscaled_tech_flows_of"),
    "result/upstream-costs-of": IpcMethod("get_upstream_costs_of"),
    "result/upstream-impacts-of": IpcMethod("get_upstream_impacts_of"),
    "result/upstream-interventions-of": IpcMethod(
        "get_upstream_interventions_of"),
}

# Method names the olca-ipc client sends that no server understands,
# with the method that does the job.
CLIENT_MISNAMED: Dict[str, str] = {
    "result/total-impacts-of-one": "result/impact-intensities-of",
}


def needs_version(method: str) -> str:
    """The openLCA version a method needs, for an error message."""
    entry = IPC_METHODS.get(method)
    return entry.since if entry else ""
