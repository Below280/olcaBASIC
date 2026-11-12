"""
Writing to the database: flows, bridges, processes, product systems,
parameters, and the edits, moves and deletions of them.

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


class BuildMixin:
    """Writing to the database: flows, bridges, processes, product systems,"""

    def create_global_parameter(self, name: str,
                                value: Optional[float] = None,
                                formula: Optional[str] = None,
                                description: str = "") -> Dict:
        """
        Create or update a global (database-level) parameter.

        Give a value for an input parameter, or a formula for a
        dependent parameter that openLCA calculates from others
        (e.g. formula="cement_mass * water_ratio"). Any process
        formula in the database can reference a global parameter by
        name, and scenarios and sensitivity redefine it once for the
        whole model.

        If a global parameter with this name already exists it is
        updated in place (same ID) and the previous value/formula is
        returned, so callers can tell when they've changed something
        another model may also use.
        """
        err = _validate_param_name(name, 0)
        if err:
            return {"error": err.replace("Parameter 0: ", "")}
        if (value is None) == (not formula):
            return {"error": "Give exactly one of value (input parameter) "
                             "or formula (dependent parameter)."}
        if formula:
            ferr = _validate_formula(formula, 0)
            if ferr:
                return {"error": ferr.replace("Exchange 0: ", "")}
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])",
                         formula):
                return {"error": f"Formula for '{name}' refers to itself."}

        try:
            existing = None
            for desc in self._get_descriptors(o.Parameter):
                if desc.name == name:
                    existing = self.client.get(o.Parameter, desc.id)
                    break

            if existing:
                previous = {"value": existing.value,
                            "formula": existing.formula or None,
                            "is_input": bool(existing.is_input_parameter)}
                param = existing
            else:
                previous = None
                param = o.Parameter()
                param.id = str(uuid.uuid4())
                param.name = name
                param.parameter_scope = o.ParameterScope.GLOBAL_SCOPE

            if formula:
                param.formula = formula
                param.value = None
                param.is_input_parameter = False
            else:
                param.value = float(value)
                param.formula = None
                param.is_input_parameter = True
            if description:
                param.description = description

            ref = self.client.put(param)
            self._cache.pop("Parameter", None)

            result = {
                "parameter_id": ref.id,
                "name": name,
                "scope": "global",
                "is_input": formula is None,
                "value": None if formula else float(value),
                "formula": formula or None,
                "already_existed": existing is not None,
            }
            if previous:
                result["previous"] = previous
                # openLCA stores a calculated value on formula
                # parameters, so compare formulas for those and
                # values only for input parameters
                norm = lambda f: re.sub(r"\s+", "", f or "")
                if formula:
                    changed = (previous["is_input"]
                               or norm(previous["formula"]) != norm(formula))
                else:
                    changed = (not previous["is_input"]
                               or previous["value"] != float(value))
                if changed:
                    result["changed"] = True
            return result
        except Exception as ex:
            return {"error": str(ex)}

    @staticmethod
    def _clean_param_segment(text: str, length: int = 10) -> str:
        """Normalise one segment of an auto-parameter name.

        Every character that isn't a letter, digit, or underscore
        is replaced with an underscore, repeated underscores collapse,
        and the result is truncated to ``length`` characters.

        Previous versions only handled commas and spaces, letting
        semicolons, hyphens, parentheses, and slashes through.
        FLCAC flow names like 'Steel; sections; at plant' produced
        parameter names containing ';' which broke formula evaluation.
        """
        text = (text or "").strip()
        text = re.sub(r'[^a-zA-Z0-9_]', '_', text)
        while "__" in text:
            text = text.replace("__", "_")
        return text.strip("_")[:length]

    def _make_param_name(self, index: int, process_name: str,
                         flow_name: str, unit_name: str,
                         used_names: Optional[set] = None) -> str:
        """Build an auto-parameter name in Below280's convention:

            pNN_processname__flowname_unit

        pNN is a letter-prefixed zero-padded two-digit index
        (guarantees uniqueness within the process and produces a
        valid identifier — openLCA's formula evaluator requires
        names to start with a letter or underscore, not a digit),
        the process and unit segments are truncated to 10 characters
        and the flow segment to 20 (flow names like 'BRIDGE |
        Steel sections | kg' need the extra room), with
        non-alphanumeric characters normalised to underscores, and
        the process/flow segments are joined with a DOUBLE underscore
        so the process-name/flow-name boundary stays visually
        distinct from the other single-underscore joins.
        """
        base = (
            f"p{index:02d}_{self._clean_param_segment(process_name)}"
            f"__{self._clean_param_segment(flow_name, 20)}"
            f"_{self._clean_param_segment(unit_name)}"
        )
        name = base
        if used_names is not None:
            suffix = 1
            while name in used_names:
                name = f"{base}_{suffix}"
                suffix += 1
            used_names.add(name)
        return name

    def _exchange_unit(self, flow_id: str, unit_name: str) -> tuple:
        """The flow property and unit for an exchange of this flow in
        this unit: (property Ref, unit Ref, None) or (None, None, error).

        An exchange must name the flow property its unit belongs to.
        Left unset, openLCA uses the flow's reference property, and a
        unit that isn't in it is silently replaced by that property's
        reference unit (so 0.2 m3 of a mass-referenced flow became
        0.2 kg). Matching here means the unit is kept or refused.
        """
        flow = self.client.get(o.Flow, flow_id)
        if flow is None:
            return None, None, f"flow {flow_id} not found"
        options = []
        for f in flow.flow_properties or []:
            if not f.flow_property:
                continue
            key = ("fp_units", f.flow_property.id)
            if key not in self._cache:
                fp = self.client.get(o.FlowProperty, f.flow_property.id)
                ug = (self.client.get(o.UnitGroup, fp.unit_group.id)
                      if fp and fp.unit_group else None)
                self._cache[key] = (fp.name if fp else f.flow_property.name,
                                    list(ug.units or []) if ug else [])
            fp_name, units = self._cache[key]
            for u in units:
                if u.name == unit_name or unit_name in (u.synonyms or []):
                    return (o.Ref(id=f.flow_property.id, name=fp_name,
                                  ref_type=o.RefType.FlowProperty),
                            o.Ref(id=u.id, name=u.name, ref_type=o.RefType.Unit),
                            None)
            options.append(f"{fp_name}: " + ", ".join(u.name for u in units[:8]))
        return None, None, (
            f"unit '{unit_name}' isn't available for flow '{flow.name}'. "
            f"Its properties allow " + "; ".join(options) +
            ". Add a property with EDIT FLOW if another unit is needed.")

    @staticmethod
    def _parse_dq_entry(value) -> tuple:
        """Normalise pedigree scores to openLCA's dq_entry string.

        Accepts a list/tuple of ints or a string such as "(1;2;1;1;3)"
        or "1,2,1,1,3". Returns (entry, None) or (None, error).
        """
        if isinstance(value, (list, tuple)):
            parts = list(value)
        else:
            parts = str(value).strip().strip("()").replace(",", ";").split(";")
        scores = []
        for part in parts:
            try:
                n = int(str(part).strip())
            except ValueError:
                return None, f"pedigree score '{part}' is not a whole number"
            if not 1 <= n <= 5:
                return None, f"pedigree scores run from 1 to 5, got {n}"
            scores.append(n)
        if not scores:
            return None, "no pedigree scores given"
        return "(" + ";".join(str(n) for n in scores) + ")", None

    def _dq_indicator_names(self, dq_ref) -> List[str]:
        """Indicator names of a DQ system, in position order."""
        if dq_ref is None:
            return []
        key = ("dq_names", dq_ref.id)
        if key in self._cache:
            return self._cache[key]
        dq = self.client.get(o.DQSystem, dq_ref.id)
        names = [i.name for i in sorted(dq.indicators or [],
                                        key=lambda i: i.position or 0)] if dq else []
        self._cache[key] = names
        return names

    def _check_dq_entries(self, ex_defs, dq_ref) -> Optional[str]:
        """Every exchange with pedigree scores needs a flow schema, and
        the right number of scores for it. Normalises dq_entry in place."""
        for i, ex_def in enumerate(ex_defs or []):
            if not ex_def.get("dq_entry"):
                continue
            entry, err = self._parse_dq_entry(ex_def["dq_entry"])
            if err:
                return f"Exchange {i} ({ex_def.get('flow_name', '')}): {err}"
            if dq_ref is None:
                return (f"Exchange {i} ({ex_def.get('flow_name', '')}) has "
                        f"pedigree scores but the process has no flow "
                        f"(exchange) data quality system. Set flow_schema.")
            names = self._dq_indicator_names(dq_ref)
            n = entry.count(";") + 1
            if names and n != len(names):
                return (f"Exchange {i} ({ex_def.get('flow_name', '')}) has "
                        f"{n} pedigree scores, but '{dq_ref.name}' has "
                        f"{len(names)} indicators ({', '.join(names)}).")
            ex_def["dq_entry"] = entry
        return None

    def _resolve_dq_system(self, name_or_id: str):
        """Internal: resolve a DQ system by name or UUID. Returns Ref or None."""
        for desc in self.client.get_descriptors(o.DQSystem):
            if desc.id == name_or_id or desc.name == name_or_id:
                return o.Ref(
                    id=desc.id, name=desc.name,
                    ref_type=o.RefType.DQSystem,
                )
        # Substring fallback
        lower = name_or_id.lower()
        for desc in self.client.get_descriptors(o.DQSystem):
            if lower in desc.name.lower():
                return o.Ref(
                    id=desc.id, name=desc.name,
                    ref_type=o.RefType.DQSystem,
                )
        return None

    def _get_fp_ref(self, unit_name: str):
        """Internal: get flow property Ref for a unit.

        Uses the auto-detected database family to pick the right
        flow property name. ecoinvent uses 'Time', 'Mass transport';
        FLCAC uses 'Duration', 'Goods transport (mass*distance)'.
        """
        self._ensure_unit_cache()
        fp_name = self.UNIT_FP_MAP.get(unit_name)
        if not fp_name:
            return None
        fp_ref = self._fp_lookup.get(fp_name)
        if not fp_ref:
            # Substring fallback
            for name, ref in self._fp_lookup.items():
                if fp_name.lower() in name.lower():
                    return ref
        return fp_ref

    def parameterise_process(self, process_id: str,
                             dry_run: bool = False,
                             include_elementary: bool = False) -> Dict:
        """Replace the fixed amounts of a process with parameters.

        Each product or waste exchange that has a fixed amount (no
        formula) and is not the reference exchange gets a process
        parameter holding that amount, and the exchange gets the
        parameter's name as its formula. Results do not change; the
        amounts can then be varied by scenarios and sensitivity.
        Elementary flows are left as they are unless
        include_elementary is True (PARAMETERISE ... ALL).

        This changes the process for good: there is no undo short of
        restoring a backup of the database. dry_run=True reports what
        would change and writes nothing.

        Returns {"process_id", "process_name", "parameters": [{"name",
        "value", "flow", "unit", "is_input"}], "parameterised",
        "already_formula", "elementary_left", "written"}."""
        try:
            process = self.client.get(o.Process, process_id)
            if not process:
                return {"error": f"Process not found: {process_id}"}
            used = {p.name for p in process.parameters or []}
            made, new_params = [], []
            already = elementary = 0
            flow_types: Dict[str, Any] = {}
            for index, ex in enumerate(process.exchanges or []):
                if getattr(ex, "is_quantitative_reference", False) or not ex.flow:
                    continue
                if ex.amount_formula:
                    already += 1
                    continue
                flow_type = getattr(ex.flow, "flow_type", None)
                if flow_type is None:
                    if ex.flow.id not in flow_types:
                        flow = self.client.get(o.Flow, ex.flow.id)
                        flow_types[ex.flow.id] = getattr(flow, "flow_type", None)
                    flow_type = flow_types[ex.flow.id]
                is_elementary = flow_type == o.FlowType.ELEMENTARY_FLOW
                if is_elementary and not include_elementary:
                    elementary += 1
                    continue
                unit = ex.unit.name if ex.unit else ""
                name = self._make_param_name(
                    index, process.name, ex.flow.name or "", unit, used)
                made.append({"name": name, "value": ex.amount,
                             "flow": ex.flow.name or "", "unit": unit,
                             "is_input": bool(ex.is_input),
                             "elementary": is_elementary})
                if dry_run:
                    continue
                param = o.Parameter()
                param.id = str(uuid.uuid4())
                param.name = name
                param.value = ex.amount
                param.parameter_scope = o.ParameterScope.PROCESS_SCOPE
                param.is_input_parameter = True
                new_params.append(param)
                ex.amount_formula = name
            written = False
            if new_params:
                process.parameters = list(process.parameters or []) + new_params
                self.client.put(process)
                written = True
            return {"process_id": process.id, "process_name": process.name,
                    "parameters": made, "parameterised": len(made),
                    "already_formula": already, "elementary_left": elementary,
                    "written": written}
        except Exception as ex:
            return {"error": str(ex)}

    def create_flow(self, name: str, unit_name: str,
                    category: str = "",
                    flow_type: str = "product") -> Dict:
        """
        Create a flow, or return the existing one if a flow with
        the same name and category already exists.
        """
        # B01: Reject empty or whitespace-only names
        if not name or not name.strip():
            return {"error": "Flow name cannot be empty or whitespace-only."}

        # V01: Reject path traversal in category
        cat_err = _validate_category(category)
        if cat_err:
            return {"error": cat_err}

        # W04: Length limits
        if len(name) > 250:
            return {
                "error": f"Flow name is {len(name)} characters (max 250). "
                         f"Use a shorter name.",
            }

        # Pre-flight: check if this flow already exists
        existing = self._get_descriptors(o.Flow)
        for f in existing:
            f_cat = getattr(f, "category", "") or ""
            if f.name == name and (not category or category in f_cat):
                return {
                    "flow_id": f.id,
                    "flow_name": f.name,
                    "unit": unit_name,
                    "flow_type": flow_type,
                    "category": f_cat,
                    "already_existed": True,
                }

        fp_ref = self._get_fp_ref(unit_name)
        if not fp_ref:
            return {"error": f"No flow property mapping for unit '{unit_name}'"}

        type_map = {
            "product": o.FlowType.PRODUCT_FLOW,
            "waste": o.FlowType.WASTE_FLOW,
            "elementary": o.FlowType.ELEMENTARY_FLOW,
        }
        ft = type_map.get(flow_type)
        if not ft:
            return {"error": f"Invalid flow_type: {flow_type}. Use product/waste/elementary"}

        try:
            f = o.Flow()
            f.id = str(uuid.uuid4())
            f.name = name
            f.category = category
            f.flow_type = ft
            f.flow_properties = [o.FlowPropertyFactor(
                flow_property=fp_ref,
                conversion_factor=1.0,
                is_ref_flow_property=True,
            )]
            ref = self.client.put(f)
            # Clear flow cache so new flow is findable immediately
            self._cache.pop("Flow", None)
            return {
                "flow_id": ref.id,
                "flow_name": ref.name,
                "unit": unit_name,
                "flow_property": fp_ref.name,
                "flow_type": flow_type,
                "category": category,
            }
        except Exception as ex:
            return {"error": str(ex)}

    def create_bridge(self, name: str, unit_name: str,
                      category: str = "",
                      provider_id: Optional[str] = None,
                      provider_flow_id: Optional[str] = None,
                      waste: bool = False) -> Dict:
        """
        Create a bridge flow AND bridge process in one call.

        A bridge connects the foreground model to a background
        database process. The bridge process has TWO exchanges:

        For product bridges:
          OUTPUT: the bridge flow (quantitative reference)
          INPUT:  the background flow from the provider process

        For waste bridges (waste=True):
          INPUT:  the bridge flow (quantitative reference)
          OUTPUT: the background waste flow to the treatment process

        If provider_id is given, the function looks up the provider
        process, finds its quantitative reference flow, and creates
        the input exchange automatically. If provider_flow_id is
        also given, it uses that flow instead of auto-detecting.
        """
        # B01: Reject empty or whitespace-only names
        if not name or not name.strip():
            return {"error": "Bridge name cannot be empty or whitespace-only."}

        # V01: Reject path traversal in category
        cat_err = _validate_category(category)
        if cat_err:
            return {"error": cat_err}

        # V05: Validate provider_id is a valid UUID
        if provider_id:
            uuid_err = _validate_uuid(provider_id, "provider_id")
            if uuid_err:
                return {"error": uuid_err}

        # W04: Length limits
        if len(name) > 250:
            return {
                "error": f"Bridge name is {len(name)} characters (max 250). "
                         f"Use a shorter name.",
            }

        # Pre-flight: check if a bridge process with this name exists
        existing = self._get_descriptors(o.Process)
        for p in existing:
            p_cat = getattr(p, "category", "") or ""
            if p.name == name and (not category or category in p_cat):
                # Bridge process exists, find its bridge flow too
                bridge_flow_id = None
                proc = self.client.get(o.Process, p.id)
                if proc and proc.exchanges:
                    for ex in proc.exchanges:
                        if getattr(ex, "is_quantitative_reference", False) and ex.flow:
                            bridge_flow_id = ex.flow.id
                            break
                return {
                    "flow_id": bridge_flow_id,
                    "flow_name": name,
                    "process_id": p.id,
                    "process_name": p.name,
                    "category": p_cat,
                    "already_existed": True,
                }

        # Create the bridge flow
        flow_type = "waste" if waste else "product"
        flow_result = self.create_flow(name, unit_name, category, flow_type)
        if "error" in flow_result:
            return flow_result

        flow_id = flow_result["flow_id"]
        unit_ref = self._get_unit_ref(unit_name)

        # Build the bridge flow exchange (quantitative reference)
        qref_x = o.Exchange()
        qref_x.flow = o.Ref(id=flow_id, name=name, ref_type=o.RefType.Flow)
        qref_x.amount = 1.0
        qref_x.unit = unit_ref
        qref_x.is_input = waste  # waste enters, product leaves
        qref_x.is_quantitative_reference = True
        qref_x.is_avoided_product = False
        qref_x.internal_id = 1

        exchanges = [qref_x]
        bg_flow_name = None

        # Build the background exchange if provider is given
        if provider_id:
            bg_flow_ref = None

            if provider_flow_id:
                # Use the explicitly provided flow ID
                bg_flow = self.client.get(o.Flow, provider_flow_id)
                if bg_flow:
                    bg_flow_ref = o.Ref(
                        id=bg_flow.id, name=bg_flow.name,
                        ref_type=o.RefType.Flow,
                    )
                    bg_flow_name = bg_flow.name
            else:
                # Auto-detect: look up provider's quantitative reference flow
                provider_proc = self.client.get(o.Process, provider_id)
                if provider_proc and provider_proc.exchanges:
                    for ex in provider_proc.exchanges:
                        if getattr(ex, "is_quantitative_reference", False):
                            if ex.flow:
                                bg_flow_ref = o.Ref(
                                    id=ex.flow.id, name=ex.flow.name,
                                    ref_type=o.RefType.Flow,
                                )
                                bg_flow_name = ex.flow.name
                            break

            if bg_flow_ref:
                bg_x = o.Exchange()
                bg_x.flow = bg_flow_ref
                bg_x.amount = 1.0
                bg_x.unit = unit_ref
                # For product: background flow is INPUT to bridge
                # For waste: background flow is OUTPUT from bridge
                bg_x.is_input = not waste
                bg_x.is_quantitative_reference = False
                bg_x.is_avoided_product = False
                bg_x.default_provider = o.Ref(
                    id=provider_id, ref_type=o.RefType.Process,
                )
                bg_x.internal_id = 2
                exchanges.append(bg_x)

        # Build the bridge process
        try:
            p = o.Process()
            p.id = str(uuid.uuid4())
            p.name = name
            p.category = category
            p.process_type = o.ProcessType.UNIT_PROCESS
            p.description = (
                "Bridge process: connects foreground model to background database."
            )
            p.last_internal_id = len(exchanges)
            p.quantitative_reference = qref_x
            p.exchanges = exchanges

            proc_ref = self.client.put(p)

            # Clear caches so new flow and process are findable
            self._cache.pop("Flow", None)
            self._cache.pop("Process", None)

            result = {
                "flow_id": flow_id,
                "flow_name": name,
                "process_id": proc_ref.id,
                "process_name": proc_ref.name,
                "unit": unit_name,
                "waste": waste,
                "provider_id": provider_id,
                "category": category,
                "exchange_count": len(exchanges),
            }
            if bg_flow_name:
                result["background_flow"] = bg_flow_name
            if not provider_id:
                result["note"] = (
                    "No provider set. Add the background input exchange "
                    "manually in openLCA or use edit_process."
                )
            elif len(exchanges) == 1:
                result["warning"] = (
                    "Could not find the provider's quantitative reference "
                    "flow. Bridge has no background input. Set provider_flow_id "
                    "explicitly or add the input exchange manually."
                )
            return result
        except Exception as ex:
            return {"error": str(ex)}

    def create_process(self, name: str, category: str,
                       exchanges: List[Dict],
                       parameters: Optional[List[Dict]] = None,
                       description: str = "",
                       location: Optional[str] = None,
                       flow_schema: Optional[str] = None,
                       process_schema: Optional[str] = None) -> Dict:
        """
        Create a process, or return the existing one if a process
        with the same name and category already exists.

        If the process exists, returns its ID with already_existed=True
        so the assistant can use edit_process to modify it.
        """
        try:
            # B01: Reject empty or whitespace-only process names
            if not name or not name.strip():
                return {"error": "Process name cannot be empty or whitespace-only."}

            # V01: Reject path traversal in category
            cat_err = _validate_category(category)
            if cat_err:
                return {"error": cat_err}

            # W04: Length limits on name and category
            if len(name) > 250:
                return {
                    "error": f"Process name is {len(name)} characters "
                             f"(max 250). Use a shorter name.",
                }
            if category and category.count("/") > 6:
                return {
                    "error": f"Category has {category.count('/') + 1} "
                             f"levels (max 7). Use a shallower path.",
                }

            # B02: Require at least one exchange
            if not exchanges:
                return {
                    "error": "At least one exchange is required. "
                             "Include a quantitative reference (is_qref=True) "
                             "as the process output.",
                }

            # B04: Exactly one quantitative reference
            qref_count = sum(1 for ex in exchanges if ex.get("is_qref"))
            if qref_count == 0:
                return {
                    "error": "No quantitative reference found. Exactly one "
                             "exchange must have is_qref=True.",
                }
            if qref_count > 1:
                return {
                    "error": f"Found {qref_count} quantitative references "
                             f"but exactly one is required. Mark only the "
                             f"main output exchange with is_qref=True.",
                }

            # V02: Validate parameter names
            if parameters:
                for i, pd in enumerate(parameters):
                    param_err = _validate_param_name(pd.get("name", ""), i)
                    if param_err:
                        return {"error": param_err}
                    if pd.get("formula"):
                        formula_err = _validate_formula(pd["formula"], i)
                        if formula_err:
                            return {"error": formula_err.replace(
                                "Exchange", "Parameter", 1)}
                    elif "value" not in pd:
                        return {"error": f"Parameter {i}: give either a "
                                         f"value or a formula."}

            # V03: Reject negative amounts on quantitative references
            for i, ex_def in enumerate(exchanges):
                if ex_def.get("is_qref") and not ex_def.get("formula"):
                    try:
                        amt = float(ex_def.get("amount", 0.0))
                        if amt < 0:
                            return {
                                "error": f"Exchange {i}: quantitative reference "
                                         f"amount ({amt}) cannot be negative. "
                                         f"Use a positive value."
                            }
                    except (ValueError, TypeError):
                        pass  # caught later in B06

            # Pre-flight: check if this process already exists
            existing = self._get_descriptors(o.Process)
            for p in existing:
                p_cat = getattr(p, "category", "") or ""
                if p.name == name and (not category or category in p_cat):
                    return {
                        "process_id": p.id,
                        "process_name": p.name,
                        "category": p_cat,
                        "already_existed": True,
                        "hint": (
                            "Process already exists. Use edit_process to "
                            "add exchanges or parameters, or use a different name."
                        ),
                    }

            # Validate all flow_ids and provider_ids exist in this database
            flow_lookup: Dict[str, Any] = {}
            for i, ex_def in enumerate(exchanges):
                fid = ex_def.get("flow_id")
                if fid:
                    flow_check = self.client.get(o.Flow, fid)
                    if not flow_check:
                        return {
                            "error": f"Exchange {i}: flow_id '{fid}' not found in connected database. "
                                     f"Check that the ID is from this database, not a previous session.",
                        }
                    flow_lookup[fid] = flow_check
                pid = ex_def.get("provider_id")
                if pid:
                    prov_check = self.client.get(o.Process, pid)
                    if not prov_check:
                        return {
                            "error": f"Exchange {i}: provider_id '{pid}' not found in connected database.",
                        }

            p = o.Process()
            p.id = str(uuid.uuid4())
            p.name = name
            p.category = category
            p.process_type = o.ProcessType.UNIT_PROCESS
            if description:
                p.description = description

            # Set location if provided
            if location:
                loc_descriptors = self.client.get_descriptors(o.Location)
                loc_ref = None
                for ld in loc_descriptors:
                    if ld.name == location or getattr(ld, "code", "") == location:
                        loc_ref = ld
                        break
                if not loc_ref:
                    # Try partial match
                    for ld in loc_descriptors:
                        if location.lower() in ld.name.lower():
                            loc_ref = ld
                            break
                if loc_ref:
                    p.location = o.Ref(
                        id=loc_ref.id, name=loc_ref.name,
                        ref_type=o.RefType.Location,
                    )

            # B05/B06/B11: Pre-validate exchange definitions
            exchange_warnings = []
            for i, ex_def in enumerate(exchanges):
                # B05: the unit must belong to one of the flow's
                # properties, or openLCA would silently swap it
                fp_ref, u_ref, u_err = self._exchange_unit(
                    ex_def["flow_id"], ex_def.get("unit", "kg"))
                if u_err:
                    return {"error": f"Exchange {i}: {u_err}"}
                ex_def["_flow_property"], ex_def["_unit"] = fp_ref, u_ref

                # B06: Warn on extreme amounts
                formula_check = ex_def.get("formula")
                if not formula_check:
                    try:
                        amt = float(ex_def.get("amount", 0.0))
                        if abs(amt) > 1e15:
                            exchange_warnings.append(
                                f"Exchange {i}: amount {amt:.2e} is "
                                f"extremely large (>1e15). Verify this "
                                f"is intentional."
                            )
                    except (ValueError, TypeError):
                        return {
                            "error": f"Exchange {i}: amount "
                                     f"'{ex_def.get('amount')}' is not "
                                     f"a valid number.",
                        }

                # B11/V04: Formula validation
                if formula_check:
                    formula_err = _validate_formula(formula_check, i)
                    if formula_err:
                        return {"error": formula_err}
                    # Warn on very long formulas
                    if len(formula_check) > 500:
                        exchange_warnings.append(
                            f"Exchange {i}: formula is {len(formula_check)} "
                            f"chars long. openLCA may truncate or reject it."
                        )

            # Build exchanges. Every exchange is fully parametrised:
            # a bare amount becomes a process-scoped parameter named
            # NN_processname__flowname_unit (Below280 convention), and
            # the exchange references it via amount_formula. An
            # exchange that already carries an explicit formula is
            # left as-is, since it's already parametrised by design
            # (it may reference shared or global parameters).
            used_param_names = {pd["name"] for pd in (parameters or [])}
            auto_param_objects = []
            exchange_objects = []
            for i, ex_def in enumerate(exchanges, start=1):
                x = o.Exchange()
                x.internal_id = i
                fid = ex_def["flow_id"]
                flow_name = ex_def.get("flow_name") or getattr(
                    flow_lookup.get(fid), "name", "") or ""
                x.flow = o.Ref(
                    id=fid,
                    name=flow_name,
                    ref_type=o.RefType.Flow,
                )

                # Unit and the flow property it belongs to (checked above)
                unit_name = ex_def.get("unit", "kg")
                x.flow_property = ex_def.pop("_flow_property")
                x.unit = ex_def.pop("_unit")

                # Amount: an explicit formula is respected as-is;
                # a bare amount is auto-parametrised.
                formula = ex_def.get("formula")
                if formula:
                    x.amount = 0.0
                    x.amount_formula = formula
                else:
                    amount = float(ex_def.get("amount", 0.0))
                    param_name = self._make_param_name(
                        i - 1, name, flow_name, unit_name, used_param_names)
                    auto_param = o.Parameter()
                    auto_param.id = str(uuid.uuid4())
                    auto_param.name = param_name
                    auto_param.value = amount
                    auto_param.parameter_scope = o.ParameterScope.PROCESS_SCOPE
                    auto_param.is_input_parameter = True
                    auto_param_objects.append(auto_param)

                    x.amount = 0.0
                    x.amount_formula = param_name

                x.is_input = ex_def.get("is_input", True)
                x.is_quantitative_reference = ex_def.get("is_qref", False)
                x.is_avoided_product = False

                # Provider
                prov_id = ex_def.get("provider_id")
                if prov_id:
                    x.default_provider = o.Ref(
                        id=prov_id, ref_type=o.RefType.Process,
                    )

                # Comment/description
                comment = ex_def.get("comment") or ex_def.get("description")
                if comment:
                    x.description = comment

                exchange_objects.append(x)

            p.last_internal_id = len(exchange_objects)
            p.exchanges = exchange_objects

            # Set quantitative reference
            qref = next((x for x in exchange_objects
                         if x.is_quantitative_reference), None)
            if qref:
                p.quantitative_reference = qref

            # Build parameters: explicitly-provided ones plus the
            # auto-generated ones from bare-amount exchanges above.
            param_objects = list(auto_param_objects)
            if parameters:
                for pd in parameters:
                    param = o.Parameter()
                    param.id = str(uuid.uuid4())
                    param.name = pd["name"]
                    param.parameter_scope = o.ParameterScope.PROCESS_SCOPE
                    if pd.get("formula"):
                        # Dependent parameter: openLCA calculates it
                        param.formula = pd["formula"]
                        param.is_input_parameter = False
                    else:
                        param.value = float(pd.get("value", 0.0))
                        param.is_input_parameter = True
                    param.description = pd.get("description", "")
                    param_objects.append(param)
            if param_objects:
                p.parameters = param_objects

            # Set DQ systems (flow schema / process schema) if provided
            dq_info = {}
            flow_dq_ref = (self._resolve_dq_system(flow_schema)
                           if flow_schema else None)
            if flow_schema and not flow_dq_ref and any(
                    e.get("dq_entry") for e in exchanges):
                return {"error": f"Data quality system '{flow_schema}' not "
                                 f"found, and the exchanges carry pedigree "
                                 f"scores that need it."}
            dq_err = self._check_dq_entries(exchanges, flow_dq_ref)
            if dq_err:
                return {"error": dq_err}
            for x, ex_def in zip(exchange_objects, exchanges):
                if ex_def.get("dq_entry"):
                    x.dq_entry = ex_def["dq_entry"]
            if flow_schema:
                dq_ref = flow_dq_ref
                if dq_ref:
                    p.exchange_dq_system = dq_ref
                    dq_info["flow_schema"] = dq_ref.name
                else:
                    dq_info["flow_schema_warning"] = (
                        f"DQ system '{flow_schema}' not found, skipped."
                    )
            if process_schema:
                dq_ref = self._resolve_dq_system(process_schema)
                if dq_ref:
                    p.dq_system = dq_ref
                    dq_info["process_schema"] = dq_ref.name
                else:
                    dq_info["process_schema_warning"] = (
                        f"DQ system '{process_schema}' not found, skipped."
                    )

            ref = self.client.put(p)

            # Clear process cache so create_system can find it
            self._cache.pop("Process", None)
            result = {
                "process_id": ref.id,
                "process_name": ref.name,
                "category": category,
                "exchange_count": len(exchange_objects),
                "parameter_count": len(param_objects),
                "auto_parametrised": len(auto_param_objects),
            }
            result.update(dq_info)
            if exchange_warnings:
                result["warnings"] = exchange_warnings
            return result

        except Exception as ex:
            return {"error": str(ex)}

    def edit_process(self, process_id: str,
                     add_exchanges: Optional[List[Dict]] = None,
                     update_exchanges: Optional[List[Dict]] = None,
                     remove_exchanges: Optional[List[str]] = None,
                     add_parameters: Optional[List[Dict]] = None,
                     update_parameters: Optional[Dict[str, float]] = None,
                     description: Optional[str] = None,
                     category: Optional[str] = None,
                     location: Optional[str] = None) -> Dict:
        """
        Edit an existing process in place.

        update_exchanges now supports provider_id in addition to
        amount, formula, and unit.
        """
        # V01: Reject path traversal in category
        if category is not None:
            cat_err = _validate_category(category)
            if cat_err:
                return {"error": cat_err}

        # V02: Validate parameter names on add_parameters
        if add_parameters:
            for i, pd in enumerate(add_parameters):
                param_err = _validate_param_name(pd.get("name", ""), i)
                if param_err:
                    return {"error": param_err}

        # V04: Validate formulas on update_exchanges
        if update_exchanges:
            for i, upd in enumerate(update_exchanges):
                formula = upd.get("formula")
                if formula:
                    formula_err = _validate_formula(formula, i)
                    if formula_err:
                        return {"error": formula_err}

        # V04: Validate formulas on add_exchanges
        if add_exchanges:
            for i, ex_def in enumerate(add_exchanges):
                formula = ex_def.get("formula")
                if formula:
                    formula_err = _validate_formula(formula, i)
                    if formula_err:
                        return {"error": formula_err}

        try:
            process = self.client.get(o.Process, process_id)
            if process is not None:
                dq_err = self._check_dq_entries(
                    add_exchanges, getattr(process, "exchange_dq_system", None))
                if not dq_err and update_exchanges:
                    dq_err = self._check_dq_entries(
                        update_exchanges,
                        getattr(process, "exchange_dq_system", None))
                if dq_err:
                    return {"error": dq_err}
            if not process:
                return {"error": f"Process not found: {process_id}"}

            changes = []

            # Update description
            if description is not None:
                process.description = description
                changes.append("description updated")

            # Update category
            if category is not None:
                process.category = category
                changes.append(f"category set to '{category}'")

            # Update location
            if location is not None:
                loc_descriptors = self.client.get_descriptors(o.Location)
                loc_ref = None
                for ld in loc_descriptors:
                    if ld.name == location or getattr(ld, "code", "") == location:
                        loc_ref = ld
                        break
                if not loc_ref:
                    for ld in loc_descriptors:
                        if location.lower() in ld.name.lower():
                            loc_ref = ld
                            break
                if loc_ref:
                    process.location = o.Ref(
                        id=loc_ref.id, name=loc_ref.name,
                        ref_type=o.RefType.Location,
                    )
                    changes.append(f"location set to '{loc_ref.name}'")

            # Remove exchanges by flow_id. An entry may also be a dict
            # {"flow_id": ..., "internal_id": n}, which removes only that
            # one exchange when a flow appears more than once.
            single = [r for r in (remove_exchanges or []) if isinstance(r, dict)]
            remove_exchanges = [r for r in (remove_exchanges or [])
                                if not isinstance(r, dict)] or (
                                    None if not single else [])
            if single and process.exchanges:
                wanted = {(r.get("flow_id"), r.get("internal_id")) for r in single}
                kept, removed_one = [], 0
                for ex in process.exchanges:
                    key = (ex.flow.id if ex.flow else None,
                           getattr(ex, "internal_id", None))
                    if key in wanted:
                        wanted.discard(key)
                        removed_one += 1
                    else:
                        kept.append(ex)
                process.exchanges = kept
                if removed_one:
                    changes.append(f"{removed_one} exchange(s) removed")
                if wanted:
                    changes.append(
                        f"WARNING: {len(wanted)} exchange(s) to remove were "
                        f"not found in the process.")

            if remove_exchanges and process.exchanges:
                remove_set = set(remove_exchanges)
                # B09: Track which flow_ids were actually found
                found_ids = {
                    ex.flow.id for ex in process.exchanges
                    if ex.flow and ex.flow.id in remove_set
                }
                not_found = remove_set - found_ids
                before = len(process.exchanges)
                process.exchanges = [
                    ex for ex in process.exchanges
                    if not (ex.flow and ex.flow.id in remove_set)
                ]
                removed = before - len(process.exchanges)
                if removed:
                    changes.append(f"{removed} exchange(s) removed")
                if not_found:
                    changes.append(
                        f"WARNING: {len(not_found)} flow_id(s) not "
                        f"found in process exchanges: "
                        f"{', '.join(sorted(not_found)[:5])}"
                    )
            elif remove_exchanges and not process.exchanges:
                changes.append(
                    "WARNING: remove_exchanges specified but process "
                    "has no exchanges."
                )

            # Update existing exchanges (match by flow_id)
            if update_exchanges and process.exchanges:
                for upd in update_exchanges:
                    target_fid = upd.get("flow_id")
                    if not target_fid:
                        continue
                    matched = False
                    target_internal = upd.get("internal_id")
                    for ex in process.exchanges:
                        if (target_internal is not None and
                                getattr(ex, "internal_id", None) != target_internal):
                            continue
                        if ex.flow and ex.flow.id == target_fid:
                            matched = True
                            if "formula" in upd and upd["formula"]:
                                ex.amount = 0.0
                                ex.amount_formula = upd["formula"]
                                changes.append(
                                    f"exchange '{ex.flow.name}' formula set to '{upd['formula']}'")
                            elif "amount" in upd:
                                ex.amount = float(upd["amount"])
                                ex.amount_formula = None
                                changes.append(
                                    f"exchange '{ex.flow.name}' amount set to {upd['amount']}")
                            if "unit" in upd:
                                fp_ref, u_ref, u_err = self._exchange_unit(
                                    ex.flow.id, upd["unit"])
                                if u_err:
                                    return {"error": u_err}   # nothing written yet
                                ex.flow_property, ex.unit = fp_ref, u_ref
                                changes.append(
                                    f"exchange '{ex.flow.name}' unit set to '{upd['unit']}'")
                            if upd.get("dq_entry"):
                                ex.dq_entry = upd["dq_entry"]
                                changes.append(
                                    f"exchange '{ex.flow.name}' pedigree set to {upd['dq_entry']}")
                            if upd.get("comment"):
                                ex.description = upd["comment"]
                                changes.append(
                                    f"exchange '{ex.flow.name}' comment updated")
                            if "provider_id" in upd:
                                ex.default_provider = o.Ref(
                                    id=upd["provider_id"],
                                    ref_type=o.RefType.Process,
                                )
                                changes.append(
                                    f"exchange '{ex.flow.name}' provider updated")
                            break
                    # B09: Warn if the flow_id wasn't found
                    if not matched:
                        changes.append(
                            f"WARNING: update_exchanges flow_id "
                            f"'{target_fid}' not found in process."
                        )

            # Update existing parameter values
            if update_parameters and process.parameters:
                found_params = set()
                for param in process.parameters:
                    if param.name in update_parameters:
                        old_val = param.value
                        param.value = float(update_parameters[param.name])
                        found_params.add(param.name)
                        changes.append(
                            f"parameter '{param.name}': {old_val} -> {param.value}")
                # B09: Report parameters that weren't found
                not_found_params = set(update_parameters.keys()) - found_params
                if not_found_params:
                    changes.append(
                        f"WARNING: parameter(s) not found in process: "
                        f"{', '.join(sorted(not_found_params)[:10])}"
                    )
            elif update_parameters and not process.parameters:
                changes.append(
                    "WARNING: update_parameters specified but process "
                    "has no parameters."
                )

            # Add new parameters
            if add_parameters:
                if not process.parameters:
                    process.parameters = []
                for pd in add_parameters:
                    param = o.Parameter()
                    param.id = str(uuid.uuid4())
                    param.name = pd["name"]
                    param.value = float(pd.get("value", 0.0))
                    param.parameter_scope = o.ParameterScope.PROCESS_SCOPE
                    param.is_input_parameter = True
                    param.description = pd.get("description", "")
                    process.parameters.append(param)
                    changes.append(f"parameter '{pd['name']}' added")

            # Add new exchanges. Bare amounts are auto-parametrised in
            # the same NN_processname__flowname_unit convention used by
            # create_process; an explicit formula is left as-is.
            if add_exchanges:
                if not process.exchanges:
                    process.exchanges = []
                if not process.parameters:
                    process.parameters = []

                # Find the next internal_id
                max_id = process.last_internal_id or 0
                if process.exchanges:
                    existing_ids = [
                        getattr(x, "internal_id", 0) or 0
                        for x in process.exchanges
                    ]
                    if existing_ids:
                        max_id = max(max_id, max(existing_ids))

                used_param_names = {p.name for p in process.parameters}
                next_param_index = len(process.parameters)

                for ex_def in add_exchanges:
                    max_id += 1
                    x = o.Exchange()
                    x.internal_id = max_id
                    fid = ex_def["flow_id"]
                    flow_name = ex_def.get("flow_name", "")
                    if not flow_name:
                        flow_check = self.client.get(o.Flow, fid)
                        flow_name = getattr(flow_check, "name", "") or ""
                    x.flow = o.Ref(
                        id=fid,
                        name=flow_name,
                        ref_type=o.RefType.Flow,
                    )

                    unit_name = ex_def.get("unit", "kg")
                    fp_ref, u_ref, u_err = self._exchange_unit(fid, unit_name)
                    if u_err:
                        return {"error": f"'{flow_name}': {u_err}"}   # nothing written yet
                    x.flow_property, x.unit = fp_ref, u_ref

                    formula = ex_def.get("formula")
                    if formula:
                        x.amount = 0.0
                        x.amount_formula = formula
                    else:
                        amount = float(ex_def.get("amount", 0.0))
                        param_name = self._make_param_name(
                            next_param_index, process.name, flow_name,
                            unit_name, used_param_names)
                        next_param_index += 1
                        auto_param = o.Parameter()
                        auto_param.id = str(uuid.uuid4())
                        auto_param.name = param_name
                        auto_param.value = amount
                        auto_param.parameter_scope = o.ParameterScope.PROCESS_SCOPE
                        auto_param.is_input_parameter = True
                        process.parameters.append(auto_param)
                        changes.append(f"parameter '{param_name}' added")

                        x.amount = 0.0
                        x.amount_formula = param_name

                    x.is_input = ex_def.get("is_input", True)
                    x.is_quantitative_reference = ex_def.get("is_qref", False)
                    x.is_avoided_product = False

                    prov_id = ex_def.get("provider_id")
                    if prov_id:
                        x.default_provider = o.Ref(
                            id=prov_id, ref_type=o.RefType.Process,
                        )

                    comment = ex_def.get("comment") or ex_def.get("description")
                    if comment:
                        x.description = comment
                    if ex_def.get("dq_entry"):
                        x.dq_entry = ex_def["dq_entry"]

                    process.exchanges.append(x)
                    changes.append(f"exchange '{flow_name}' added")

                process.last_internal_id = max_id

            # Save
            self.client.put(process)
            self._cache.pop("Process", None)

            return {
                "process_id": process.id,
                "process_name": process.name,
                "changes": changes,
                "exchange_count": len(process.exchanges) if process.exchanges else 0,
                "parameter_count": len(process.parameters) if process.parameters else 0,
            }

        except Exception as ex:
            return {"error": str(ex)}

    def edit_flow(self, flow_id: str, operations: List[Dict]) -> Dict:
        """
        Add or update a flow's properties, or change its reference
        property. Properties are never removed here: openLCA's IPC has
        no usage query, and removing a property that exchanges use
        breaks them, so removal is left to openLCA's flow editor.

        operations, applied in order:
          {"op": "add" | "update", "property": "Mass",
           "amount": 2400, "unit": "kg", "per_unit": "m3"}
              meaning 1 m3 = 2400 kg. Either unit may belong to the named
              property; the other must belong to a property already on
              the flow. Written either way round, it means the same.
          {"op": "reference", "property": "Mass"}
              make Mass the reference; every factor is rescaled so all
              exchanges keep their meaning.

        Conversion factors follow openLCA: the amount of each property
        per one reference unit of the reference property (which is 1).
        """
        try:
            flow = self.client.get(o.Flow, flow_id)
            if flow is None:
                return {"error": f"Flow not found: {flow_id}"}
            factors = list(flow.flow_properties or [])
            changes = []
            groups = {}

            def prop_ref(name_or_id):
                descs = self._get_descriptors(o.FlowProperty)
                hit = [d for d in descs if d.id == name_or_id]
                if not hit:
                    hit = [d for d in descs
                           if (d.name or "").lower() == str(name_or_id).lower()]
                if not hit:
                    return None, (f"Flow property '{name_or_id}' not found. "
                                  f"Available include: " + ", ".join(
                                      sorted({d.name for d in descs})[:15]))
                if len(hit) > 1:
                    return None, f"'{name_or_id}' matches {len(hit)} flow properties"
                return hit[0], None

            def units_of(prop_id):
                if prop_id not in groups:
                    fp = self.client.get(o.FlowProperty, prop_id)
                    ug = (self.client.get(o.UnitGroup, fp.unit_group.id)
                          if fp and fp.unit_group else None)
                    groups[prop_id] = {u.name: (u.conversion_factor or 1.0)
                                       for u in (ug.units if ug else []) or []}
                return groups[prop_id]

            def factor_of(prop_id):
                for f in factors:
                    if f.flow_property and f.flow_property.id == prop_id:
                        return f
                return None

            def label(pid):
                f = factor_of(pid)
                return f.flow_property.name if f and f.flow_property else pid

            for i, op in enumerate(operations or []):
                kind = op.get("op")
                desc, err = prop_ref(op.get("property", ""))
                if err:
                    return {"error": f"Operation {i}: {err}"}
                existing = factor_of(desc.id)

                if kind == "reference":
                    if existing is None:
                        return {"error": f"Operation {i}: '{desc.name}' is not a "
                                         f"property of '{flow.name}'. Add it first."}
                    if existing.is_ref_flow_property:
                        changes.append(f"'{desc.name}' is already the reference")
                        continue
                    base = existing.conversion_factor
                    if not base:
                        return {"error": f"Operation {i}: '{desc.name}' has a zero "
                                         f"conversion factor"}
                    for f in factors:
                        f.conversion_factor = (f.conversion_factor or 0.0) / base
                        f.is_ref_flow_property = False
                    existing.conversion_factor = 1.0
                    existing.is_ref_flow_property = True
                    changes.append(f"reference property set to '{desc.name}' "
                                   f"(all factors rescaled)")
                    continue

                if kind not in ("add", "update"):
                    return {"error": f"Operation {i}: unknown op '{kind}'"}
                try:
                    amount = float(op["amount"])
                except (KeyError, TypeError, ValueError):
                    return {"error": f"Operation {i}: amount must be a number"}
                if amount <= 0:
                    return {"error": f"Operation {i}: amount must be positive"}
                u1, u2 = op.get("unit", ""), op.get("per_unit", "")

                # Relation: 1 u2 (property X) = amount u1 (property Y).
                # One of X, Y is the named property A; the other is B,
                # a property already on the flow.
                a_units = units_of(desc.id)
                others = [f for f in factors if f.flow_property
                          and f.flow_property.id != desc.id]

                def owner(unit):
                    return [f for f in others if unit in units_of(f.flow_property.id)]

                if u1 in a_units and owner(u2):
                    a_is_y, b = True, owner(u2)[0]
                elif u2 in a_units and owner(u1):
                    a_is_y, b = False, owner(u1)[0]
                else:
                    have = ", ".join(sorted(label(f.flow_property.id) for f in others)) or "none"
                    return {"error": (
                        f"Operation {i}: one of '{u1}' and '{u2}' must be a unit "
                        f"of '{desc.name}' and the other a unit of a property "
                        f"already on '{flow.name}' (others on it: {have}).")}
                b_units = units_of(b.flow_property.id)
                cf1 = (a_units if a_is_y else b_units)[u1]
                cf2 = (b_units if a_is_y else a_units)[u2]
                ratio = amount * cf1 / cf2          # f_Y / f_X
                f_b = b.conversion_factor or 0.0

                if kind == "add":
                    new_f = ratio * f_b if a_is_y else f_b / ratio
                    if existing is not None:
                        same = (existing.conversion_factor and abs(
                            existing.conversion_factor - new_f)
                            <= 1e-9 * max(abs(new_f), 1e-300))
                        if same or existing.is_ref_flow_property and abs(
                                (ratio * f_b if a_is_y else f_b / ratio) - 1.0) < 1e-9:
                            changes.append(f"'{desc.name}' already present with "
                                           f"this conversion, unchanged")
                            continue
                        return {"error": (
                            f"Operation {i}: '{desc.name}' is already a property "
                            f"of '{flow.name}' with a different conversion. Use "
                            f"UPDATE PROPERTY to change it.")}
                    factors.append(o.FlowPropertyFactor(
                        flow_property=o.Ref(id=desc.id, name=desc.name,
                                            ref_type=o.RefType.FlowProperty),
                        conversion_factor=new_f, is_ref_flow_property=False))
                    changes.append(f"'{desc.name}' added: 1 {u2} = {amount:g} {u1} "
                                   f"(factor {new_f:.6g})")
                else:
                    if existing is None:
                        return {"error": f"Operation {i}: '{desc.name}' is not a "
                                         f"property of '{flow.name}'. Use ADD."}
                    if existing.is_ref_flow_property:
                        # The reference stays at 1, so move the other one
                        if b.is_ref_flow_property:
                            return {"error": f"Operation {i}: both units belong "
                                             f"to the reference property"}
                        b.conversion_factor = 1.0 / ratio if a_is_y else ratio
                        changes.append(f"'{label(b.flow_property.id)}' factor set to "
                                       f"{b.conversion_factor:.6g} (1 {u2} = {amount:g} {u1})")
                    else:
                        existing.conversion_factor = ratio * f_b if a_is_y else f_b / ratio
                        changes.append(f"'{desc.name}' factor set to "
                                       f"{existing.conversion_factor:.6g} "
                                       f"(1 {u2} = {amount:g} {u1})")

            flow.flow_properties = factors
            self.client.put(flow)
            self._cache.pop("Flow", None)
            return {"flow_id": flow_id, "flow_name": flow.name,
                    "category": getattr(flow, "category", "") or "",
                    "changes": changes,
                    "properties": [{"name": f.flow_property.name,
                                    "factor": f.conversion_factor,
                                    "reference": bool(f.is_ref_flow_property)}
                                   for f in factors if f.flow_property]}
        except Exception as ex:
            return {"error": str(ex)}

    def set_process_tags(self, process_id: str, tags: Dict[str, Any],
                         prefix: str = "",
                         documentation: Optional[Dict[str, str]] = None) -> Dict:
        """Set 'prefix:key=value' tags on a process, replacing any tag
        with the same prefix and key. A value of None removes the tag.
        Tags the call does not name are left alone.

        documentation, if given, sets fields of openLCA's process
        documentation: valid_from, valid_until (dates, YYYY-MM-DD),
        time_description, data_collection_description,
        technology_description, geography_description."""
        allowed_docs = ("valid_from", "valid_until", "time_description",
                        "data_collection_description",
                        "technology_description", "geography_description")
        try:
            process = self.client.get(o.Process, process_id)
            if not process:
                return {"error": f"Process not found: {process_id}"}
            lead = f"{prefix}:" if prefix else ""
            kept = []
            for tag in process.tags or []:
                key = tag[len(lead):].partition("=")[0] if tag.startswith(lead) else None
                if key is not None and key in tags:
                    continue
                kept.append(tag)
            for key, value in tags.items():
                if value is None:
                    continue
                text = str(value).replace("\n", " ").strip()
                kept.append(f"{lead}{key}={text}")
            process.tags = kept
            if documentation:
                doc = process.process_documentation or o.ProcessDocumentation()
                for field_name, value in documentation.items():
                    if field_name not in allowed_docs:
                        return {"error": f"Unknown documentation field "
                                         f"'{field_name}'. Use: "
                                         f"{', '.join(allowed_docs)}"}
                    setattr(doc, field_name, value)
                process.process_documentation = doc
            self.client.put(process)
            return {"process_id": process.id, "process_name": process.name,
                    "tags": sorted(kept)}
        except Exception as ex:
            return {"error": str(ex)}

    def set_switched_provider(self, process_id: str, provider_id: str,
                              parameter: str) -> Dict:
        """Give a bridge a second provider that a global parameter
        switches to.

        The bridge's existing input keeps its provider and gets the
        amount formula "1 - parameter"; a second input, from
        provider_id, gets the formula "parameter". With the parameter
        at 0 (its value in the database) the bridge behaves as before;
        a calculation that redefines it to 1 draws on the second
        provider instead. Doing it twice changes nothing."""
        try:
            process = self.client.get(o.Process, process_id)
            if not process:
                return {"error": f"Process not found: {process_id}"}
            second = self.client.get(o.Process, provider_id)
            if not second:
                return {"error": f"Process not found: {provider_id}"}
            linked = [ex for ex in process.exchanges or []
                      if not getattr(ex, "is_quantitative_reference", False)
                      and getattr(ex, "default_provider", None) is not None]
            if any(ex.default_provider.id == provider_id
                   and ex.amount_formula == parameter for ex in linked):
                return {"process_id": process.id, "already_set": True}
            if len(linked) != 1:
                return {"error": f"'{process.name}' has {len(linked)} linked "
                                 f"inputs; a second provider can only be "
                                 f"added to a bridge with one."}
            first = linked[0]
            flow_ref = None
            for ex in second.exchanges or []:
                if getattr(ex, "is_quantitative_reference", False) and ex.flow:
                    flow_ref = o.Ref(id=ex.flow.id, name=ex.flow.name,
                                     ref_type=o.RefType.Flow)
                    break
            if flow_ref is None:
                return {"error": f"'{second.name}' has no reference flow."}
            made = self.create_global_parameter(
                parameter, value=0.0,
                description="Switch used by olcaBASIC: 0 for the main "
                            "provider of a bridge, 1 for its second one.")
            if "error" in made:
                return made
            first.amount_formula = f"1 - {parameter}"
            first.amount = 1.0
            extra = o.Exchange()
            extra.flow = flow_ref
            extra.amount = 0.0
            extra.amount_formula = parameter
            extra.unit = first.unit
            extra.is_input = first.is_input
            extra.is_quantitative_reference = False
            extra.is_avoided_product = False
            extra.default_provider = o.Ref(id=provider_id,
                                           ref_type=o.RefType.Process)
            process.last_internal_id = (process.last_internal_id or
                                        len(process.exchanges)) + 1
            extra.internal_id = process.last_internal_id
            process.exchanges.append(extra)
            self.client.put(process)
            self._cache.pop("Process", None)
            return {"process_id": process.id, "provider_id": provider_id,
                    "parameter": parameter}
        except Exception as ex:
            return {"error": str(ex)}

    def move_entity(self, entity_type: str, entity_id: str,
                    category: str) -> Dict:
        """
        Move a process, flow or product system to another folder.

        entity_type: 'process', 'flow', or 'product_system'
        category: the folder path to move it to

        Only the folder changes. Exchanges, links and parameters that
        point at the entity do so by UUID and are unaffected.
        """
        type_map = {
            "process": o.Process,
            "flow": o.Flow,
            "product_system": o.ProductSystem,
        }
        olca_type = type_map.get(entity_type)
        if not olca_type:
            return {
                "error": f"Unknown entity type: {entity_type}. "
                         f"Use: {', '.join(type_map.keys())}",
            }
        cat_err = _validate_category(category)
        if cat_err:
            return {"error": cat_err}
        if category and category.count("/") > 6:
            return {"error": f"Category has {category.count('/') + 1} "
                             f"levels (max 7). Use a shallower path."}
        try:
            entity = self.client.get(olca_type, entity_id)
            if not entity:
                return {"error": f"{entity_type} not found: {entity_id}"}
            previous = getattr(entity, "category", "") or ""
            entity.category = category
            self.client.put(entity)
            self._cache.pop(olca_type.__name__, None)
            return {
                "moved": True,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "name": getattr(entity, "name", entity_id),
                "from": previous,
                "to": category,
            }
        except Exception as ex:
            return {"error": str(ex)}

    def delete_entity(self, entity_type: str, entity_id: str,
                      usage_checked: bool = False,
                      prefer_categories=None) -> Dict:
        """
        Delete a process, flow, or product system from the database.

        entity_type: 'process', 'flow', or 'product_system'
        entity_id: UUID of the entity to delete
        """
        type_map = {
            "process": o.Process,
            "flow": o.Flow,
            "product_system": o.ProductSystem,
        }
        olca_type = type_map.get(entity_type)
        if not olca_type:
            return {
                "error": f"Unknown entity type: {entity_type}. "
                         f"Use: {', '.join(type_map.keys())}",
            }

        try:
            # Verify it exists first
            entity = self.client.get(olca_type, entity_id)
            if not entity:
                return {"error": f"{entity_type} not found: {entity_id}"}

            name = getattr(entity, "name", entity_id)

            # openLCA deletes a flow even while exchanges or
            # characterisation factors still point at it, which leaves
            # those processes and methods broken. Refuse instead.
            if entity_type == "flow" and not usage_checked:
                # One use is enough to refuse, so stop at the first
                usage = self.find_flow_usage(
                    entity_id, max_hits=1,
                    prefer_categories=prefer_categories)
                if "error" in usage:
                    return usage
                if (not usage["in_use"] and usage["processes_checked"]
                        < usage["processes_total"]):
                    return {"error": (
                        f"Only {usage['processes_checked']} of "
                        f"{usage['processes_total']} processes could be "
                        f"checked for uses of flow '{name}', so it was "
                        f"not deleted.")}
                if usage["in_use"]:
                    where = usage["used_by_processes"] + [
                        f"{c} (impact category)"
                        for c in usage["used_in_impact_categories"]
                    ] + list(usage.get("used_elsewhere", []))
                    more = "" if usage["complete"] else " (and possibly others)"
                    return {"error": (
                        f"Flow '{name}' is still used by "
                        f"{', '.join(where)}{more}. Remove it from those "
                        f"first; deleting it now would leave them broken."),
                        "in_use": True}

            self.client.delete(entity)

            # Clear relevant cache
            cache_key = olca_type.__name__
            self._cache.pop(cache_key, None)

            return {
                "deleted": True,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "name": name,
            }
        except Exception as ex:
            return {"error": str(ex)}

    # ── product system creation ─────────────────────────────

    def create_product_system(self, process_ref: str,
                              linking: str = "prefer_defaults",
                              target_amount: Optional[float] = None,
                              target_unit: Optional[str] = None,
                              target_flow_property: Optional[str] = None,
                              category: Optional[str] = None) -> Dict:
        """
        Create a product system from a process.

        linking options:
          'prefer_defaults' - use default providers where set (recommended)
          'only_defaults'   - only link where default providers exist

        Optional: set target_amount, target_unit (e.g. 'm3', 'kg'),
        target_flow_property (e.g. 'Volume', 'Mass'), and category
        after creation. Same pattern as EB_full_products.py.
        """
        # V01: Reject path traversal in category
        if category:
            cat_err = _validate_category(category)
            if cat_err:
                return {"error": cat_err}

        process = self._resolve_process(process_ref)
        if not process:
            return {"error": f"Process not found: {process_ref}"}

        # BUG-06: Pre-flight duplicate check
        existing = self._get_descriptors(o.ProductSystem)
        for ps in existing:
            ps_cat = getattr(ps, "category", "") or ""
            if ps.name == process.name:
                return {
                    "system_id": ps.id,
                    "system_name": ps.name,
                    "category": ps_cat,
                    "already_existed": True,
                    "hint": (
                        "Product system already exists for this process. "
                        "Use list_systems or validate_system to inspect it, "
                        "or delete_entity to remove it before recreating."
                    ),
                }

        # B07: Validate target_amount if provided
        if target_amount is not None:
            if target_amount <= 0:
                return {
                    "error": f"target_amount must be positive, got "
                             f"{target_amount}. Use a positive value "
                             f"representing the functional unit quantity.",
                }
            if abs(target_amount) > 1e15:
                return {
                    "error": f"target_amount {target_amount:.2e} is "
                             f"unreasonably large (>1e15).",
                }

        # B07: Validate target_unit if provided
        if target_unit:
            unit_check = self._get_unit_ref(target_unit)
            if not unit_check:
                return {
                    "error": f"target_unit '{target_unit}' not found "
                             f"in this database.",
                }

        # B03: Verify the source process has a quantitative reference
        # before attempting system creation; without one, openLCA
        # returns a NoneType error.
        try:
            source_proc = self.client.get(o.Process, process.id)
            if source_proc:
                has_qref = False
                if source_proc.exchanges:
                    for ex in source_proc.exchanges:
                        if getattr(ex, "is_quantitative_reference", False):
                            has_qref = True
                            break
                if not has_qref:
                    return {
                        "error": (
                            f"Process '{process.name}' has no quantitative "
                            f"reference exchange. A product system requires "
                            f"the source process to have exactly one output "
                            f"exchange marked as quantitative reference "
                            f"(is_qref=True). Edit the process first."
                        ),
                    }
        except Exception:
            pass  # proceed and let openLCA report the error if any

        # Set up linking config
        if linking == "only_defaults":
            provider = o.ProviderLinking.ONLY_DEFAULTS
        else:
            provider = o.ProviderLinking.PREFER_DEFAULTS

        config = o.LinkingConfig(
            prefer_unit_processes=True,
            provider_linking=provider,
        )

        system_id = None
        warnings = []

        # BUG-02: Serialise product system creation to prevent
        # concurrent IPC crashes in openLCA
        with self._system_lock:
            try:
                system_ref = self.client.create_product_system(process, config)
                system_id = system_ref.id

                # Always read back the system for post-creation fixes
                system = self.client.get(o.ProductSystem, system_ref.id)

                # BUG-01: Default target_amount to qref amount when IPC
                # returns 0 (the IPC default). Read the source process to
                # find its quantitative reference amount.
                current_amount = getattr(system, "target_amount", 0) or 0
                if target_amount is not None:
                    system.target_amount = target_amount
                elif current_amount == 0:
                    qref_amount = 1.0  # safe fallback
                    try:
                        source_proc = self.client.get(o.Process, process.id)
                        if source_proc and source_proc.exchanges:
                            for ex in source_proc.exchanges:
                                if getattr(ex, "is_quantitative_reference", False):
                                    qref_amount = ex.amount or 1.0
                                    break
                    except Exception:
                        pass
                    system.target_amount = qref_amount
                    warnings.append(
                        f"target_amount was 0 after creation; "
                        f"defaulted to quantitative reference amount "
                        f"({qref_amount})"
                    )

                if category:
                    system.category = category

                if target_flow_property:
                    self._ensure_unit_cache()
                    fp = self._fp_lookup.get(target_flow_property)
                    if fp:
                        system.target_flow_property = o.Ref(
                            id=fp.id, name=fp.name,
                            ref_type=o.RefType.FlowProperty,
                        )

                if target_unit:
                    # The unit must belong to a property of the reference
                    # flow, or openLCA would swap it for another unit
                    full = self.client.get(o.Process, process.id)
                    qref = next((ex for ex in ((full.exchanges if full else None) or [])
                                 if getattr(ex, "is_quantitative_reference", False)
                                 and ex.flow), None)
                    if qref is None:
                        return {"error": "the process has no reference flow "
                                         "to apply target_unit to"}
                    fp_ref, u_ref, u_err = self._exchange_unit(
                        qref.flow.id, target_unit)
                    if u_err:
                        return {"error": f"target_unit: {u_err}"}
                    system.target_unit = u_ref
                    if not target_flow_property:
                        system.target_flow_property = fp_ref

                self.client.put(system)

                # Read back the system to report which providers were linked
                linked_system = self.client.get(o.ProductSystem, system_ref.id)
                links = self._extract_links(linked_system)

                # B08: Warn about self-referencing links
                root_id = process.id
                self_links = [
                    lnk for lnk in links
                    if lnk.get("provider_id") == root_id
                    and lnk.get("receiving_process_id") == root_id
                ]
                if self_links:
                    warnings.append(
                        f"Detected {len(self_links)} self-referencing "
                        f"link(s) where the root process is both "
                        f"provider and receiver. This creates a "
                        f"circular dependency that may cause "
                        f"calculation errors."
                    )

                # BUG-03: Warn when only_defaults links zero providers
                if not links and linking == "only_defaults":
                    warnings.append(
                        "No providers were linked. 'only_defaults' links "
                        "only processes with a default provider set. Try "
                        "'prefer_defaults' to auto-link all exchanges."
                    )

                result = {
                    "system_id": system_ref.id,
                    "system_name": system_ref.name,
                    "source_process": process.name,
                    "linking": linking,
                    "linked_providers": links,
                    "target_amount": system.target_amount,
                }
                if target_unit:
                    result["target_unit"] = target_unit
                if target_flow_property:
                    result["target_flow_property"] = target_flow_property
                if warnings:
                    result["warnings"] = warnings
                return result

            except Exception as e:
                # BUG-04/05: If the system was created but post-processing
                # failed, still return the system_id so it isn't orphaned
                if system_id:
                    return {
                        "error": str(e),
                        "system_id": system_id,
                        "partial": True,
                        "hint": (
                            "Product system was created but post-processing "
                            "failed (possibly a timeout on a large database). "
                            "The system exists in openLCA and can be inspected "
                            "with validate_system or get_system_links."
                        ),
                    }
                return {"error": str(e)}
            finally:
                # BUG-07: Always invalidate the ProductSystem cache after
                # a creation attempt. Previously this was only inside the
                # try block's success path, so a timeout that still created
                # the system on the Java side left the cache stale — the
                # next call's duplicate check wouldn't see it and would
                # create another copy.
                self._cache.pop("ProductSystem", None)
