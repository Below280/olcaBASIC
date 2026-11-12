"""
Reading a whole model: what a set of processes holds, which parameters
it uses, one indicator split by elementary flow, and the model written
out for a verifier. Used by the EPD toolkit.

Part of olcabasic.engine.Engine (see engine.py).
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import olca_schema as o

from .fields import uncertainty_dict

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _enum(value) -> Optional[str]:
    return value.name if value is not None else None


def _ref(ref) -> Optional[Dict]:
    return {"name": ref.name, "id": ref.id} if ref is not None else None


def _text(value) -> Optional[str]:
    return None if value is None else str(value)


class ModelMixin:
    """Whole-model reads."""

    # ── what stands behind a dataset ─────────────────────────

    def dataset_metadata(self, process_id: str) -> Dict:
        """What a process says about itself: name, location, validity,
        the technology, geography and time descriptions, its data
        quality system, and the first provider it buys from (what
        stands behind a bridge)."""
        try:
            p = self.client.get(o.Process, process_id)
            if p is None:
                return {"error": f"Process not found: {process_id}"}
            doc = p.process_documentation
            loc = p.location
            dq = p.exchange_dq_system or p.dq_system
            provider = None
            for ex in p.exchanges or []:
                if ex.is_input and ex.default_provider is not None:
                    provider = ex.default_provider
                    break
            return {
                "id": p.id, "name": p.name,
                "category": getattr(p, "category", "") or "",
                "location": (loc.name or "") if loc is not None else "",
                "valid_from": (_text(doc.valid_from)[:10]
                               if doc and doc.valid_from else ""),
                "valid_until": (_text(doc.valid_until)[:10]
                                if doc and doc.valid_until else ""),
                "technology": (doc.technology_description or "")
                if doc else "",
                "geography": (doc.geography_description or "") if doc else "",
                "time": (doc.time_description or "") if doc else "",
                "dq_system": dq.name if dq is not None else "",
                "provider_id": provider.id if provider is not None else "",
                "provider_name": (provider.name or "")
                if provider is not None else "",
            }
        except Exception as ex:
            return {"error": str(ex)}

    # ── parameters a set of processes uses ───────────────────

    def model_parameters(self, process_ids: List[str]) -> Dict:
        """
        The parameters a set of processes can be varied through:
        {"local": {name: [process ids]}, "global": [names], "dependent":
        [names]}. local: input parameters of the processes themselves.
        global: global input parameters that a formula in those
        processes uses, directly or through other global parameters.
        dependent: names that are calculated from a formula.
        """
        try:
            globals_by_name = {
                g.name: g for g in self.client.get_all(o.Parameter)}
            local: Dict[str, List[str]] = {}
            dependent = set()
            used = set()
            for pid in process_ids:
                p = self.client.get(o.Process, pid)
                if p is None:
                    continue
                own = set()
                formulas = []
                for param in p.parameters or []:
                    own.add(param.name)
                    if param.is_input_parameter:
                        local.setdefault(param.name, []).append(pid)
                    else:
                        dependent.add(param.name)
                        formulas.append(param.formula or "")
                for ex in p.exchanges or []:
                    for f in (ex.amount_formula, ex.cost_formula):
                        if f:
                            formulas.append(f)
                for f in formulas:
                    used.update(n for n in _NAME.findall(f) if n not in own)
            reached = set()
            stack = [n for n in used if n in globals_by_name]
            while stack:
                name = stack.pop()
                if name in reached:
                    continue
                reached.add(name)
                g = globals_by_name[name]
                if not g.is_input_parameter and g.formula:
                    stack.extend(n for n in _NAME.findall(g.formula)
                                 if n in globals_by_name)
            inputs = sorted(n for n in reached
                            if globals_by_name[n].is_input_parameter)
            dependent.update(n for n in reached
                             if not globals_by_name[n].is_input_parameter)
            return {"local": local, "global": inputs,
                    "dependent": sorted(dependent)}
        except Exception as ex:
            return {"error": str(ex)}

    def calculate_scaled(self, system_ref: str, method_ref: str,
                         names: List[str], factor: float,
                         allocation: Optional[str] = None) -> Dict:
        """
        Calculate a system with every input parameter in names
        multiplied by factor: each copy of a name (the global one and
        each process's own) from its own value. Returns {"impacts":
        {category: amount}, "scaled": {name: copies}}.
        """
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}
        found = self.find_method_strict(method_ref)
        if "error" in found:
            return {"error": found["error"]}
        method = next(m for m in self._get_descriptors(o.ImpactMethod)
                      if m.id == found["id"])
        try:
            targets = self._parameter_targets(system, set(names))
            redefs, scaled = [], {}
            for name in names:
                copies = [c for c in targets.get(name, []) if c["is_input"]]
                if not copies:
                    return {"error": f"'{system.name}' has no parameter "
                                     f"'{name}' that can be set."}
                scaled[name] = len(copies)
                for c in copies:
                    redefs.append(o.ParameterRedef(
                        name=name, value=float(c["value"]) * factor,
                        context=c["context"]))
            setup = o.CalculationSetup(
                target=system, impact_method=method, parameters=redefs,
                allocation=self._resolve_allocation(allocation))
            result = self.client.calculate(setup)
            try:
                state = result.wait_until_ready()
                if getattr(state, "error", None):
                    return {"error": f"openLCA could not calculate "
                                     f"'{system.name}': {state.error}"}
                impacts = {i.impact_category.name: i.amount
                           for i in result.get_total_impacts()}
            finally:
                result.dispose()
            return {"system": system.name, "impacts": impacts,
                    "scaled": scaled}
        except Exception as ex:
            return {"error": str(ex)}

    # ── one indicator, split by elementary flow ──────────────

    def flow_split(self, system_ref: str, method_ref: str, category: str,
                   name_holds: str,
                   allocation: Optional[str] = None) -> Dict:
        """
        One calculation, then one impact category split between the
        elementary flows whose name holds name_holds (case does not
        matter) and the rest. Returns {"impacts": {category: amount},
        "total", "matching", "other", "flows": [{"flow", "amount"}]}.
        """
        opened = self.open_result(system_ref, method_ref,
                                  allocation=allocation, temporary=True)
        if "error" in opened:
            return opened
        try:
            got = self.result_query(opened["handle"], "contribution_flow",
                                    category=category)
            if "error" in got:
                return got
            needle = name_holds.lower()
            flows = [{"flow": r["flow"], "amount": r["amount"]}
                     for r in got["rows"]
                     if r["amount"] and needle in (r["flow"] or "").lower()]
            matching = sum(f["amount"] for f in flows)
            return {"impacts": {i["category"]: i["amount"]
                                for i in opened["impacts"]},
                    "total": got["total"], "matching": matching,
                    "other": got["total"] - matching, "flows": flows}
        finally:
            self.close_result(opened["handle"])

    # ── the model, written out ───────────────────────────────

    @staticmethod
    def _exchange_out(ex) -> Dict:
        out = {
            "flow_name": ex.flow.name if ex.flow else None,
            "flow_id": ex.flow.id if ex.flow else None,
            "is_input": bool(ex.is_input),
            "is_quantitative_reference": bool(ex.is_quantitative_reference),
            "is_avoided_product": bool(ex.is_avoided_product),
            "amount": ex.amount,
            "amount_formula": ex.amount_formula,
            "unit": ex.unit.name if ex.unit else None,
            "flow_property": (ex.flow_property.name
                              if ex.flow_property else None),
            "internal_id": ex.internal_id,
            "description": ex.description,
            "dq_entry": ex.dq_entry,
            "base_uncertainty": ex.base_uncertainty,
            "cost_value": ex.cost_value,
            "cost_formula": ex.cost_formula,
            "currency": ex.currency.name if ex.currency else None,
            "location": ex.location.name if ex.location else None,
            "default_provider": _ref(ex.default_provider),
            "uncertainty": uncertainty_dict(ex.uncertainty),
        }
        return out

    @staticmethod
    def _parameter_out(p) -> Dict:
        return {
            "name": p.name, "description": p.description, "value": p.value,
            "formula": p.formula,
            "is_input_parameter": bool(p.is_input_parameter),
            "parameter_scope": _enum(p.parameter_scope),
            "uncertainty": uncertainty_dict(p.uncertainty),
        }

    @staticmethod
    def _documentation_out(doc) -> Optional[Dict]:
        if doc is None:
            return None
        text_fields = (
            "time_description", "geography_description",
            "technology_description", "data_collection_description",
            "completeness_description", "data_selection_description",
            "data_treatment_description", "inventory_method_description",
            "modeling_constants_description", "sampling_description",
            "restrictions_description", "intended_application",
            "project_description", "use_advice")
        out: Dict[str, Any] = {k: getattr(doc, k, None) for k in text_fields}
        for key in ("creation_date", "valid_from", "valid_until"):
            out[key] = _text(getattr(doc, key, None))
        out["copyright"] = getattr(doc, "is_copyright_protected", None)
        for key in ("data_set_owner", "data_generator", "data_documentor",
                    "publication"):
            ref = getattr(doc, key, None)
            out[key] = ref.name if ref is not None else None
        out["sources"] = [_ref(s) for s in (doc.sources or [])]
        out["reviews"] = [
            {"type": r.review_type,
             "report": r.report.name if r.report is not None else None,
             "details": r.details,
             "reviewers": [a.name for a in (r.reviewers or [])]}
            for r in (getattr(doc, "reviews", None) or [])]
        return out

    def export_model(self, folder: str, system_ids: List[str],
                     title: str = "") -> Dict:
        """
        Everything a verifier needs to read a model, as one dictionary:
        every process in a folder (and the folders below it) with every
        exchange field, parameters, allocation factors, documentation
        and tags; the flows those processes use; the global parameters
        the model uses; and the product systems named. Read only.
        """
        try:
            base = (folder or "").strip("/").lower()
            procs = []
            for d in self._get_descriptors(o.Process):
                cat = (getattr(d, "category", "") or "").strip("/").lower()
                if cat == base or cat.startswith(base + "/"):
                    procs.append(d)
            procs.sort(key=lambda d: ((getattr(d, "category", "") or ""),
                                      d.name or ""))
            out_procs: Dict[str, Dict] = {}
            flow_ids: Dict[str, None] = {}
            for d in procs:
                p = self.client.get(o.Process, d.id)
                if p is None:
                    continue
                loc = None
                if p.location is not None:
                    loc = {"name": p.location.name, "id": p.location.id}
                    full = self.client.get(o.Location, p.location.id)
                    if full is not None:
                        loc["code"] = full.code
                out_procs[p.id] = {
                    "id": p.id, "name": p.name,
                    "description": p.description,
                    "category": getattr(p, "category", None),
                    "process_type": _enum(p.process_type),
                    "location": loc, "dq_entry": p.dq_entry,
                    "dq_system": p.dq_system.name if p.dq_system else None,
                    "exchange_dq_system": (p.exchange_dq_system.name
                                           if p.exchange_dq_system else None),
                    "default_allocation_method": _enum(
                        p.default_allocation_method),
                    "is_infrastructure_process": bool(
                        p.is_infrastructure_process),
                    "last_change": _text(p.last_change),
                    "version": p.version, "tags": list(p.tags or []),
                    "exchanges": [self._exchange_out(ex)
                                  for ex in p.exchanges or []],
                    "parameters": [self._parameter_out(x)
                                   for x in p.parameters or []],
                    "allocation_factors": [
                        {"allocation_type": _enum(a.allocation_type),
                         "value": a.value, "formula": a.formula,
                         "product": a.product.name if a.product else None,
                         "exchange_internal_id": (a.exchange.internal_id
                                                  if a.exchange else None)}
                        for a in p.allocation_factors or []],
                    "documentation": self._documentation_out(
                        p.process_documentation),
                }
                for ex in p.exchanges or []:
                    if ex.flow is not None:
                        flow_ids[ex.flow.id] = None
            flows: Dict[str, Dict] = {}
            for fid in flow_ids:
                f = self.client.get(o.Flow, fid)
                if f is None:
                    continue
                flows[f.id] = {
                    "id": f.id, "name": f.name, "description": f.description,
                    "category": getattr(f, "category", None),
                    "flow_type": _enum(f.flow_type), "cas": f.cas,
                    "formula": f.formula, "synonyms": f.synonyms,
                    "tags": list(f.tags or []),
                    "last_change": _text(f.last_change),
                    "version": f.version,
                    "flow_property_factors": [
                        {"flow_property": (x.flow_property.name
                                           if x.flow_property else None),
                         "flow_property_id": (x.flow_property.id
                                              if x.flow_property else None),
                         "conversion_factor": x.conversion_factor,
                         "is_ref_flow_property": bool(
                             x.is_ref_flow_property)}
                        for x in f.flow_properties or []],
                }
            used = self.model_parameters(list(out_procs))
            if "error" in used:
                return used
            wanted = set(used["global"]) | {
                n for n in used["dependent"]}
            global_params = [
                self._parameter_out(g)
                for g in sorted(self.client.get_all(o.Parameter),
                                key=lambda g: g.name or "")
                if g.name in wanted]
            systems = []
            for sid in system_ids:
                s = self.client.get(o.ProductSystem, sid)
                if s is None:
                    continue
                systems.append({
                    "id": s.id, "name": s.name,
                    "description": s.description,
                    "category": getattr(s, "category", None),
                    "reference_process": _ref(s.ref_process),
                    "target_amount": s.target_amount,
                    "target_unit": (s.target_unit.name
                                    if s.target_unit else None),
                    "target_flow_property": (
                        s.target_flow_property.name
                        if s.target_flow_property else None),
                    "processes": [_ref(r) for r in (s.processes or [])],
                    "process_links": len(s.process_links or []),
                    "parameter_sets": [
                        {"name": ps.name,
                         "is_baseline": bool(ps.is_baseline),
                         "parameters": [
                             {"name": r.name, "value": r.value,
                              "context": (r.context.name
                                          if r.context else None)}
                             for r in ps.parameters or []]}
                        for ps in s.parameter_sets or []],
                    "analysis_groups": [
                        {"name": g.name,
                         "processes": [r.name for r in g.processes or []]}
                        for g in getattr(s, "analysis_groups", None) or []],
                })
            exchanges = sum(len(p["exchanges"]) for p in out_procs.values())
            return {
                "metadata": {
                    "exported": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "model": title, "folder": folder,
                    "process_count": len(out_procs),
                    "flow_count": len(flows),
                    "global_parameter_count": len(global_params),
                    "system_count": len(systems),
                    "total_exchanges": exchanges,
                    "total_process_parameters": sum(
                        len(p["parameters"]) for p in out_procs.values()),
                    "parameterised_exchanges": sum(
                        1 for p in out_procs.values()
                        for ex in p["exchanges"] if ex["amount_formula"]),
                },
                "processes": out_procs, "flows": flows,
                "global_parameters": global_params, "systems": systems,
            }
        except Exception as ex:
            return {"error": str(ex)}
