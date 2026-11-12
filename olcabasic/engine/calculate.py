"""
Single calculations on a product system: impacts, contributions,
inventory, Monte Carlo, the upstream tree.

Part of olcabasic.engine.Engine (see engine.py).
"""

from olca_ipc import Client
import olca_schema as o
from typing import Dict, List, Optional, Any
import logging
import time
import csv
import os
import uuid
import urllib.request
import urllib.parse
import json as json_module
import re
import threading

# One logger for the whole engine, under the name it has always had.
logger = logging.getLogger("olcabasic.engine.engine")

from .validators import (
    validate_category as _validate_category,
    validate_param_name as _validate_param_name,
    validate_formula as _validate_formula,
    validate_uuid as _validate_uuid,
)


class CalculateMixin:
    """Single calculations on a product system: impacts, contributions,"""

    def upstream_tree(self, system_ref: str, method_ref: str,
                      category: str, levels: int = 3, top: int = 5,
                      allocation: Optional[str] = None,
                      with_quality: bool = True,
                      result_handle: Optional[str] = None) -> Dict:
        """
        Multi-level contribution tree for one impact category, walked
        with openLCA's upstream tree (result.get_upstream_impacts_of).

        Each node carries the upstream result of that supply-chain
        branch, its share of the total, and (with_quality) the pedigree
        scores on the exchange that links it to its parent, with the
        indicator names of the parent's flow data quality system.
        Each level keeps the top N children; the rest are summed into
        'other'.
        """
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}
        method = self._resolve_method(method_ref)
        if not method:
            return {"error": f"Impact method not found: {method_ref}"}

        opened, borrowed, failed = self.borrow_result(
            result_handle, system_ref, method_ref, allocation)
        if failed:
            return failed
        result = opened.result
        try:
            totals = result.get_total_impacts()
            want = category.lower()
            match = ([t for t in totals if t.impact_category.name.lower() == want]
                     or [t for t in totals if want in t.impact_category.name.lower()])
            if not match:
                return {"error": f"Impact category '{category}' not found",
                        "available": [t.impact_category.name for t in totals]}
            if len(match) > 1:
                return {"error": f"'{category}' matches several categories",
                        "available": [t.impact_category.name for t in match]}
            total = match[0]
            impact_ref = total.impact_category
            grand = total.amount or 0.0

            proc_cache = {}

            def process(pid):
                if pid not in proc_cache:
                    proc_cache[pid] = self.client.get(o.Process, pid)
                return proc_cache[pid]

            def link_quality(parent_pid, tech_flow):
                """Pedigree on the parent's exchange for this branch."""
                parent = process(parent_pid) if parent_pid else None
                if parent is None:
                    return None, [], ""
                names = self._dq_indicator_names(
                    getattr(parent, "exchange_dq_system", None))
                prov_id = tech_flow.provider.id if tech_flow.provider else None
                candidates = [ex for ex in (parent.exchanges or [])
                              if ex.flow and ex.flow.id == tech_flow.flow.id
                              and not getattr(ex, "is_quantitative_reference", False)]
                exact = [ex for ex in candidates if ex.default_provider
                         and ex.default_provider.id == prov_id]
                ex = (exact or candidates or [None])[0]
                if ex is None:
                    return None, names, ""
                return (getattr(ex, "dq_entry", None) or None, names,
                        getattr(ex, "description", "") or "")

            def node_of(n, parent_pid, depth, path):
                tf = n.tech_flow
                prov = tf.provider
                entry, names, comment = (link_quality(parent_pid, tf)
                                         if with_quality and parent_pid else
                                         (None, [], ""))
                node = {
                    "name": prov.name if prov else tf.flow.name,
                    "flow": tf.flow.name,
                    "location": getattr(prov, "location", "") or "",
                    "amount": n.result,
                    "direct": n.direct_contribution,
                    "share": (n.result / grand * 100) if grand else 0.0,
                    "dq_entry": entry,
                    "dq_indicators": names,
                    "comment": comment,
                    "children": [],
                }
                if depth < levels and prov is not None:
                    kids = result.get_upstream_impacts_of(impact_ref, path + [tf])
                    kids = sorted(kids, key=lambda k: abs(k.result or 0),
                                  reverse=True)
                    shown, rest = kids[:top], kids[top:]
                    node["children"] = [node_of(k, prov.id, depth + 1,
                                                path + [tf]) for k in shown]
                    if rest:
                        other = sum(k.result or 0 for k in rest)
                        node["other"] = {
                            "count": len(rest), "amount": other,
                            "share": (other / grand * 100) if grand else 0.0}
                return node

            roots = result.get_upstream_impacts_of(impact_ref, [])
            if not roots:
                return {"error": "openLCA returned no upstream tree for this "
                                 "system and category"}

            # An empty path may return the root node itself or the root's
            # children, depending on the openLCA version. Compare with
            # the demand to tell which, and build paths to match.
            demand_tf = result.get_demand().tech_flow

            def same(a, b):
                return (a and b and a.flow and b.flow and a.flow.id == b.flow.id
                        and (a.provider.id if a.provider else None)
                        == (b.provider.id if b.provider else None))

            if len(roots) == 1 and same(roots[0].tech_flow, demand_tf):
                root = node_of(roots[0], None, 0, [])
            else:
                # Children came back: make the root from the demand
                prov = demand_tf.provider
                kids = sorted(roots, key=lambda k: abs(k.result or 0),
                              reverse=True)
                shown, rest = kids[:top], kids[top:]
                root = {
                    "name": prov.name if prov else demand_tf.flow.name,
                    "flow": demand_tf.flow.name,
                    "location": getattr(prov, "location", "") or "",
                    "amount": grand, "direct": None, "share": 100.0,
                    "dq_entry": None, "dq_indicators": [], "comment": "",
                    "children": [node_of(k, prov.id if prov else None, 1, [])
                                 for k in shown] if levels >= 1 else [],
                }
                if rest and levels >= 1:
                    other = sum(k.result or 0 for k in rest)
                    root["other"] = {"count": len(rest), "amount": other,
                                     "share": (other / grand * 100) if grand else 0.0}
            return {
                "system": system.name,
                "method": method.name,
                "category": impact_ref.name,
                "unit": getattr(impact_ref, "ref_unit", "") or "",
                "total": grand,
                "levels": levels,
                "top": top,
                "root": root,
            }
        finally:
            if not borrowed:
                self.close_result(opened.handle)

    def process_contributions(self, system_ref: str, method_ref: str,
                              direct: Optional[List[str]] = None,
                              upstream: Optional[List[str]] = None,
                              allocation: Optional[str] = None,
                              parameters: Optional[Dict[str, float]] = None
                              ) -> Dict:
        """
        One calculation, then the contribution of named processes to
        every impact category.

        direct: process UUIDs whose own (direct) impacts are wanted.
        upstream: process UUIDs whose total upstream impacts are wanted
            (the process and everything that supplies it).
        parameters: global parameter values to redefine for this run.

        Returns {"system", "method", "totals": {category: amount},
        "units": {category: unit}, "direct": {process_id: {category:
        amount}}, "upstream": {...}, "names": {process_id: name},
        "missing": [ids not in the system]}.

        Summing the direct impacts of the foreground processes and the
        upstream impacts of the bridges that feed them gives the system
        total, which is what a split by data source needs.
        """
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}
        found = self.find_method_strict(method_ref)
        if "error" in found:
            return {"error": found["error"]}
        method = next(m for m in self._get_descriptors(o.ImpactMethod)
                      if m.id == found["id"])
        redefs = None
        if parameters:
            targets = self._parameter_targets(system, set(parameters))
            redefs = [o.ParameterRedef(name=name, value=float(value),
                                       context=copy["context"])
                      for name, value in parameters.items()
                      for copy in targets.get(name, []) if copy["is_input"]]
            missing_params = [n for n in parameters if not targets.get(n)]
            if missing_params:
                return {"error": "Parameter(s) not found in the system: "
                                 + ", ".join(missing_params)}
        setup = o.CalculationSetup(
            target=system, impact_method=method, parameters=redefs,
            allocation=self._resolve_allocation(allocation))
        result = self.client.calculate(setup)
        result.wait_until_ready()
        try:
            totals, units = {}, {}
            for imp in result.get_total_impacts():
                totals[imp.impact_category.name] = imp.amount
                units[imp.impact_category.name] = getattr(
                    imp.impact_category, "ref_unit", "") or ""
            by_id = {tf.provider.id: tf for tf in result.get_tech_flows()
                     if tf.provider}
            out = {"system": system.name, "method": method.name,
                   "totals": totals, "units": units, "direct": {},
                   "upstream": {}, "names": {}, "missing": []}
            for kind, ids, getter in (
                    ("direct", direct or [], result.get_direct_impacts_of),
                    ("upstream", upstream or [], result.get_total_impacts_of)):
                for pid in ids:
                    tf = by_id.get(pid)
                    if tf is None:
                        if pid not in out["missing"]:
                            out["missing"].append(pid)
                        continue
                    out["names"][pid] = tf.provider.name
                    out[kind][pid] = {
                        imp.impact_category.name: imp.amount
                        for imp in getter(tf)}
            return out
        finally:
            result.dispose()

    # ── calculations ─────────────────────────────────────────

    def calculate_impacts(self, system_ref: str,
                          method_ref: str,
                          allocation: Optional[str] = None) -> Dict:
        """Run a baseline impact calculation for a product system."""
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}

        method = self._resolve_method(method_ref)
        if not method:
            return {"error": f"Impact method not found: {method_ref}"}

        setup = o.CalculationSetup(
            target=system, impact_method=method,
            allocation=self._resolve_allocation(allocation))
        result = self.client.calculate(setup)
        result.wait_until_ready()

        try:
            impacts = result.get_total_impacts()
            return {
                "system": system.name,
                "method": method.name,
                "impacts": self._impacts_to_list(impacts),
            }
        finally:
            result.dispose()

    def contribution_analysis(self, system_ref: str, method_ref: str,
                              threshold_pct: float = 0.1,
                              max_contributors: int = 30,
                              categories: Optional[List[str]] = None,
                              allocation: Optional[str] = None,
                              result_handle: Optional[str] = None) -> Dict:
        """
        Process-level contribution analysis: which processes give the
        most to each impact category. It uses this pattern:

            result.get_tech_flows()
            result.get_total_impacts_of(tech_flow)

        For each tech flow in the system, gets the full upstream impact
        total. Filters to contributions above threshold_pct of the
        category total. Returns a breakdown per impact category.

        If categories is provided, only those category names are
        analysed (substring match). Otherwise all categories are
        included.

        result_handle: an open result (open_result) to read from when
        it is this same calculation, instead of calculating again.
        """
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}

        method = self._resolve_method(method_ref)
        if not method:
            return {"error": f"Impact method not found: {method_ref}"}

        opened, borrowed, failed = self.borrow_result(
            result_handle, system_ref, method_ref, allocation)
        if failed:
            return failed
        result = opened.result

        try:
            # Get system totals
            total_impacts = result.get_total_impacts()
            totals = {}
            for imp in total_impacts:
                totals[imp.impact_category.id] = {
                    "name": imp.impact_category.name,
                    "amount": imp.amount,
                    "unit": getattr(imp.impact_category, "ref_unit", ""),
                }

            # Filter categories if requested
            active_cats = {}
            for cat_id, cat_data in totals.items():
                if categories:
                    if any(c.lower() in cat_data["name"].lower()
                           for c in categories):
                        active_cats[cat_id] = cat_data
                else:
                    active_cats[cat_id] = cat_data

            # Get all tech flows
            tech_flows = result.get_tech_flows()

            # For each tech flow, get upstream impacts
            contributions_by_cat = {cat_id: [] for cat_id in active_cats}

            for tf in tech_flows:
                tf_impacts = result.get_total_impacts_of(tf)

                for imp in tf_impacts:
                    cat_id = imp.impact_category.id
                    if cat_id not in active_cats:
                        continue

                    total_amt = active_cats[cat_id]["amount"]
                    if abs(total_amt) < 1e-30:
                        continue

                    pct = (imp.amount / total_amt) * 100

                    if abs(pct) >= threshold_pct:
                        contributions_by_cat[cat_id].append({
                            "process": tf.provider.name,
                            "process_id": tf.provider.id,
                            "flow": tf.flow.name,
                            "amount": imp.amount,
                            "pct": round(pct, 2),
                        })

            # Sort and trim each category
            output_cats = {}
            for cat_id, contribs in contributions_by_cat.items():
                cat_data = active_cats[cat_id]
                contribs.sort(key=lambda c: abs(c["amount"]), reverse=True)
                trimmed = contribs[:max_contributors]

                covered_pct = sum(abs(c["pct"]) for c in trimmed)

                output_cats[cat_data["name"]] = {
                    "total": cat_data["amount"],
                    "unit": cat_data["unit"],
                    "contributor_count": len(trimmed),
                    "covered_pct": round(covered_pct, 1),
                    "contributors": trimmed,
                }

            return {
                "system": system.name,
                "method": method.name,
                "threshold_pct": threshold_pct,
                "categories_analysed": len(output_cats),
                "categories": output_cats,
            }

        finally:
            if not borrowed:
                self.close_result(opened.handle)

    def monte_carlo(self, system_ref: str, method_ref: str,
                    iterations: int = 1000,
                    allocation: Optional[str] = None,
                    trial: bool = False) -> Dict:
        """
        Run Monte Carlo uncertainty simulation.

        Starts a simulation in openLCA (result/simulate), asks for one
        run after another (result/simulate/next), collects the impact
        totals of each and computes statistics.

        trial: stop after two runs if they give the same total for
        every category, and return {"error", "no_uncertainty": True}.
        (The caller asks for this when nothing in the foreground has an
        uncertainty distribution: every run would then be the same.)
        """
        # V07: Reject non-positive iterations
        if iterations <= 0:
            return {
                "error": f"iterations must be a positive integer (got {iterations}). "
                         f"Use at least 100 for meaningful results."
            }

        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}

        method = self._resolve_method(method_ref)
        if not method:
            return {"error": f"Impact method not found: {method_ref}"}

        import statistics

        # A simulation is its own kind of result in openLCA
        # (result/simulate): asking a plain calculation for another run
        # is refused by the server, and the client swallows the refusal,
        # so every "run" would give the same numbers.
        made = self.open_result(system_ref, method_ref, allocation,
                                simulate=True, temporary=True)
        if "error" in made:
            return made
        opened = self._results()[made["handle"]]
        result = opened.result
        try:
            distributions: Dict[str, List[float]] = {}
            cat_units = {}

            runs = max(iterations, 2) if trial else iterations
            for i in range(runs):
                state = result.simulate_next()
                err = getattr(state, "error", None)
                if not err:
                    err = getattr(result.wait_until_ready(), "error", None)
                if err:
                    return {"error": f"openLCA stopped the simulation at "
                                     f"run {i + 1}: {err}"}
                impacts = result.get_total_impacts()

                for imp in impacts:
                    name = imp.impact_category.name
                    if name not in distributions:
                        distributions[name] = []
                        cat_units[name] = getattr(
                            imp.impact_category, "ref_unit", "")
                    distributions[name].append(imp.amount)

                if trial and i == 1 and all(
                        v[0] == v[1] for v in distributions.values()):
                    return {"error": "Two trial runs gave the same result "
                                     "for every category: nothing in this "
                                     "system is uncertain.",
                            "no_uncertainty": True}

                if (i + 1) % 100 == 0:
                    logger.info(f"Monte Carlo: {i + 1}/{iterations}")

            if runs > iterations:
                distributions = {name: values[:iterations]
                                 for name, values in distributions.items()}

            stats = {}
            for name, values in distributions.items():
                n = len(values)
                if n == 0:
                    continue
                mean = statistics.mean(values)
                sd = statistics.stdev(values) if n > 1 else 0
                cv = (sd / abs(mean) * 100) if abs(mean) > 1e-30 else 0

                stats[name] = {
                    "unit": cat_units[name],
                    "iterations": n,
                    "mean": mean,
                    "std_dev": sd,
                    "cv_pct": round(cv, 2),
                    "min": min(values),
                    "max": max(values),
                    "median": statistics.median(values),
                    "p5": sorted(values)[int(n * 0.05)] if n >= 20 else None,
                    "p95": sorted(values)[int(n * 0.95)] if n >= 20 else None,
                }

            # Detect zero-variance (no uncertainty data in database)
            all_zero_variance = all(
                stats[name]["std_dev"] == 0 for name in stats
            )

            output = {
                "system": system.name,
                "method": method.name,
                "iterations": len(next(iter(distributions.values()), [])),
                "statistics": stats,
            }

            if all_zero_variance:
                output["warning"] = (
                    "All categories have zero variance across all iterations. "
                    "This means the database processes have no uncertainty "
                    "distributions defined on their exchanges. The Monte Carlo "
                    "simulation ran correctly but sampled no distributions, so "
                    "every iteration returned the same deterministic result. "
                    "These statistics are not meaningful for uncertainty analysis. "
                    "Check exchange-level uncertainty in the source processes "
                    "before relying on these numbers."
                )

            return output

        except Exception as e:
            return {"error": str(e), "note": (
                "Monte Carlo requires uncertainty distributions on exchanges. "
                "If the database has no uncertainty data, results will be "
                "identical across all iterations."
            )}
        finally:
            self.close_result(opened.handle)

    def inventory_flows(self, system_ref: str,
                        method_ref: str,
                        threshold: float = 1e-10,
                        max_flows: int = 50,
                        allocation: Optional[str] = None,
                        result_handle: Optional[str] = None) -> Dict:
        """
        Get elementary flow inventory results (LCI).

        Returns the raw biosphere flows (kg CO2, MJ energy, etc.)
        rather than characterised impact results. Uses
        result.get_total_flows() from the verified DQ script pattern.
        """
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}

        method = self._resolve_method(method_ref)
        if not method:
            return {"error": f"Impact method not found: {method_ref}"}

        opened, borrowed, failed = self.borrow_result(
            result_handle, system_ref, method_ref, allocation)
        if failed:
            return failed
        result = opened.result

        try:
            total_flows = result.get_total_flows()

            flows = []
            for fr in total_flows:
                if abs(fr.amount) < threshold:
                    continue
                ef = fr.envi_flow
                flows.append({
                    "flow": ef.flow.name,
                    "flow_id": ef.flow.id,
                    "amount": fr.amount,
                    "is_input": ef.is_input,
                    "category": getattr(ef.flow, "category", ""),
                    "ref_unit": getattr(ef.flow, "ref_unit", ""),
                })

            # Sort by absolute amount
            flows.sort(key=lambda f: abs(f["amount"]), reverse=True)
            flows = flows[:max_flows]

            return {
                "system": system.name,
                "method": method.name,
                "flow_count": len(flows),
                "total_flows_in_system": len(total_flows),
                "flows": flows,
            }

        finally:
            if not borrowed:
                self.close_result(opened.handle)
