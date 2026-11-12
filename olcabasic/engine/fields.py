"""
The fields of processes, flows, parameters and product systems that
olcaBASIC could not write before: uncertainty, avoided products, costs,
allocation factors, documentation, social aspects, process type,
exchange locations, parameter sets, analysis groups, and the chemical
fields of a flow.

Part of olcabasic.engine.Engine (see engine.py).
"""

import math
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import olca_schema as o

# ── uncertainty ──────────────────────────────────────────────

UNCERTAINTY_KINDS = {
    "LOGNORMAL": ("geometric mean", "geometric standard deviation"),
    "NORMAL": ("mean", "standard deviation"),
    "TRIANGLE": ("minimum", "mode", "maximum"),
    "UNIFORM": ("minimum", "maximum"),
}


def make_uncertainty(kind: str, values: List[float]):
    """(olca_schema.Uncertainty, None) or (None, error message)."""
    kind = (kind or "").upper()
    names = UNCERTAINTY_KINDS.get(kind)
    if names is None:
        return None, (f"Unknown uncertainty distribution '{kind}'. Use "
                      f"LOGNORMAL, NORMAL, TRIANGLE or UNIFORM.")
    if len(values) != len(names):
        return None, (f"UNCERTAINTY {kind} takes {len(names)} numbers "
                      f"({', '.join(names)}), not {len(values)}.")
    try:
        v = [float(x) for x in values]
    except (TypeError, ValueError):
        return None, f"UNCERTAINTY {kind} takes numbers."
    if any(math.isnan(x) or math.isinf(x) for x in v):
        return None, f"UNCERTAINTY {kind} takes finite numbers."
    if kind == "LOGNORMAL":
        if v[0] <= 0:
            return None, (f"The geometric mean of a log-normal "
                          f"distribution must be above 0 (got {v[0]:g}).")
        if v[1] <= 1:
            return None, (f"The geometric standard deviation must be "
                          f"above 1 (got {v[1]:g}). A value of 1 means no "
                          f"spread at all.")
        return o.Uncertainty(
            distribution_type=o.UncertaintyType.LOG_NORMAL_DISTRIBUTION,
            geom_mean=v[0], geom_sd=v[1]), None
    if kind == "NORMAL":
        if v[1] <= 0:
            return None, (f"The standard deviation must be above 0 (got "
                          f"{v[1]:g}).")
        return o.Uncertainty(
            distribution_type=o.UncertaintyType.NORMAL_DISTRIBUTION,
            mean=v[0], sd=v[1]), None
    if kind == "TRIANGLE":
        if not (v[0] <= v[1] <= v[2]) or v[0] == v[2]:
            return None, (f"A triangular distribution needs minimum <= "
                          f"mode <= maximum, with minimum below maximum "
                          f"(got {v[0]:g}, {v[1]:g}, {v[2]:g}).")
        return o.Uncertainty(
            distribution_type=o.UncertaintyType.TRIANGLE_DISTRIBUTION,
            minimum=v[0], mode=v[1], maximum=v[2]), None
    if v[0] >= v[1]:
        return None, (f"A uniform distribution needs minimum below maximum "
                      f"(got {v[0]:g}, {v[1]:g}).")
    return o.Uncertainty(
        distribution_type=o.UncertaintyType.UNIFORM_DISTRIBUTION,
        minimum=v[0], maximum=v[1]), None


def describe_uncertainty(u) -> str:
    """'LOGNORMAL 2.5, 1.2', as it would be typed. '' for none."""
    if u is None or u.distribution_type is None:
        return ""
    t = u.distribution_type
    if t == o.UncertaintyType.LOG_NORMAL_DISTRIBUTION:
        return f"LOGNORMAL {u.geom_mean:g}, {u.geom_sd:g}"
    if t == o.UncertaintyType.NORMAL_DISTRIBUTION:
        return f"NORMAL {u.mean:g}, {u.sd:g}"
    if t == o.UncertaintyType.TRIANGLE_DISTRIBUTION:
        return f"TRIANGLE {u.minimum:g}, {u.mode:g}, {u.maximum:g}"
    if t == o.UncertaintyType.UNIFORM_DISTRIBUTION:
        return f"UNIFORM {u.minimum:g}, {u.maximum:g}"
    return ""


def uncertainty_dict(u) -> Optional[Dict]:
    text = describe_uncertainty(u)
    if not text:
        return None
    kind, _, rest = text.partition(" ")
    return {"kind": kind, "values": [float(x) for x in rest.split(", ")],
            "text": text}


# ── documentation ────────────────────────────────────────────

#: Every field of openLCA's process documentation: field -> kind.
#: text: free text; date: a day; actor / source: one entity by name;
#: sources: several sources; bool: yes or no; the last three are lists
#: of small records.
DOCUMENT_FIELDS: Dict[str, str] = {
    "completeness_description": "text",
    "compliance_declarations": "compliance",
    "creation_date": "date",
    "data_collection_description": "text",
    "data_documentor": "actor",
    "data_generator": "actor",
    "data_selection_description": "text",
    "data_set_owner": "actor",
    "data_treatment_description": "text",
    "flow_completeness": "aspects",
    "geography_description": "text",
    "intended_application": "text",
    "inventory_method_description": "text",
    "is_copyright_protected": "bool",
    "modeling_constants_description": "text",
    "project_description": "text",
    "publication": "source",
    "restrictions_description": "text",
    "reviews": "reviews",
    "sampling_description": "text",
    "sources": "sources",
    "technology_description": "text",
    "time_description": "text",
    "use_advice": "text",
    "valid_from": "date",
    "valid_until": "date",
}

_DMY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def parse_date(text: str):
    """(ISO date 'YYYY-MM-DD', None) or (None, error). Accepts
    DD/MM/YYYY and YYYY-MM-DD, and a bare year."""
    text = str(text).strip()
    m = _DMY.match(text)
    try:
        if m:
            d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            return d.isoformat(), None
        m = _ISO.match(text)
        if m:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return d.isoformat(), None
    except ValueError:
        return None, f"'{text}' is not a real date."
    return None, (f"'{text}' is not a date. Write it as DD/MM/YYYY or "
                  f"YYYY-MM-DD.")


RISK_LEVELS = [e.name for e in o.RiskLevel]

ALLOCATION_WORDS = {
    "PHYSICAL": o.AllocationType.PHYSICAL_ALLOCATION,
    "ECONOMIC": o.AllocationType.ECONOMIC_ALLOCATION,
    "CAUSAL": o.AllocationType.CAUSAL_ALLOCATION,
    "NONE": o.AllocationType.NO_ALLOCATION,
    "AS_DEFINED": o.AllocationType.USE_DEFAULT_ALLOCATION,
}
ALLOCATION_NAMES = {v: k for k, v in ALLOCATION_WORDS.items()}

#: Shares of one allocation method must add up to 1 within this.
ALLOCATION_SUM_TOLERANCE = 1e-6


class _Refused(Exception):
    """A field that cannot be written: message and the key of the line
    that asked for it."""

    def __init__(self, message: str, where: Any = None, hint: str = ""):
        self.message, self.where, self.hint = message, where, hint
        super().__init__(message)


class FieldsMixin:
    """Writing and reading the wider set of fields."""

    # ── look-ups by name ─────────────────────────────────────

    def _one_by_name(self, entity_type, name: str, what: str, make: str):
        """Descriptor of the one entity of a type with this name or
        UUID. Raises _Refused when there is none or several."""
        items = self._get_descriptors(entity_type)
        found = [d for d in items if d.id == name]
        if not found:
            found = [d for d in items if d.name == name]
        if len(found) == 1:
            return found[0]
        if not found:
            raise _Refused(f"No {what} is called '{name}'.",
                           hint=(f"{make} FIND {what.upper()} \"{name}\" "
                                 f"searches by part of a name.").strip())
        listing = "\n".join(
            f"    {getattr(d, 'category', '') or '(no folder)':<40} {d.id}"
            for d in found[:12])
        raise _Refused(f"'{name}' matches {len(found)} {what}s:\n{listing}",
                       hint="Use the UUID in place of the name.")

    def _actor(self, name: str):
        d = self._one_by_name(o.Actor, name, "actor",
                              "Make one with MAKE ACTOR.")
        return o.Ref(id=d.id, name=d.name, ref_type=o.RefType.Actor)

    def _source(self, name: str):
        d = self._one_by_name(o.Source, name, "source",
                              "Make one with MAKE SOURCE.")
        return o.Ref(id=d.id, name=d.name, ref_type=o.RefType.Source)

    def _currency(self, name: str):
        items = self._get_descriptors(o.Currency)
        full = None
        found = [d for d in items if d.id == name or d.name == name]
        if not found:
            # by code: the descriptor has no code, the entity does
            for d in items:
                cur = self.client.get(o.Currency, d.id)
                if cur is not None and (cur.code or "").upper() == name.upper():
                    found.append(d)
        if len(found) == 1:
            return o.Ref(id=found[0].id, name=found[0].name,
                         ref_type=o.RefType.Currency)
        if not found:
            raise _Refused(
                f"No currency is called '{name}' (by name or by code).",
                hint="FIND CURRENCY \"\" lists the currencies; MAKE "
                     "CURRENCY creates one.")
        raise _Refused(f"'{name}' matches {len(found)} currencies.",
                       hint="Use the UUID in place of the name.")

    def _location(self, code: str):
        items = self._get_descriptors(o.Location)
        found = [d for d in items if d.id == code
                 or (getattr(d, "code", None) or "") == code]
        if not found:
            found = [d for d in items if d.name == code]
        if not found:
            # descriptors of some servers carry no code
            for d in items:
                if d.name and d.name.lower() == code.lower():
                    found.append(d)
        if not found:
            for loc in self.client.get_all(o.Location):
                if (loc.code or "") == code:
                    found.append(loc)
        if len(found) >= 1 and len({d.id for d in found}) == 1:
            return o.Ref(id=found[0].id, name=found[0].name,
                         ref_type=o.RefType.Location)
        if not found:
            raise _Refused(f"No location has the code or name '{code}'.",
                           hint="FIND LOCATION \"text\" searches the "
                                "locations; MAKE LOCATION creates one.")
        raise _Refused(f"'{code}' matches {len(found)} locations.",
                       hint="Use the UUID in place of the code.")

    # ── processes ────────────────────────────────────────────

    def _exchange_views(self, process) -> List[Dict]:
        views = []
        for ex in process.exchanges or []:
            views.append({
                "internal_id": ex.internal_id,
                "flow_id": ex.flow.id if ex.flow else None,
                "flow_name": (ex.flow.name or "") if ex.flow else "",
                "is_input": bool(ex.is_input),
                "is_qref": bool(ex.is_quantitative_reference),
                "flow_type": self._flow_type_name(ex),
                "avoided": bool(ex.is_avoided_product),
                "aliases": ([ex.default_provider.name]
                            if ex.default_provider is not None
                            and ex.default_provider.name else []),
            })
        return views

    def _flow_type_name(self, ex) -> str:
        ft = getattr(ex.flow, "flow_type", None) if ex.flow else None
        if ft is None and ex.flow is not None:
            flow = self.client.get(o.Flow, ex.flow.id)
            ft = flow.flow_type if flow else None
        return {o.FlowType.PRODUCT_FLOW: "product",
                o.FlowType.WASTE_FLOW: "waste",
                o.FlowType.ELEMENTARY_FLOW: "elementary"}.get(ft, "product")

    @staticmethod
    def _is_product_view(v: Dict, avoided: Optional[bool] = None) -> bool:
        """A product the process makes: a product output or a waste
        input (a treatment service), not flagged as avoided."""
        avoided = v["avoided"] if avoided is None else avoided
        if avoided:
            return False
        return ((v["flow_type"] == "product" and not v["is_input"])
                or (v["flow_type"] == "waste" and v["is_input"]))

    def flow_type_of(self, flow_id: str) -> str:
        """'product', 'waste' or 'elementary' for a flow, '' if it is
        not in the database."""
        return self.flow_info(flow_id).get("type", "")

    def flow_info(self, flow_id: str) -> Dict:
        """{"name", "type"} of a flow, {} if it is not in the database.
        type is 'product', 'waste' or 'elementary'."""
        for d in self._get_descriptors(o.Flow):
            if d.id == flow_id:
                return {"name": d.name, "type": {
                    o.FlowType.PRODUCT_FLOW: "product",
                    o.FlowType.WASTE_FLOW: "waste",
                    o.FlowType.ELEMENTARY_FLOW: "elementary"}.get(
                        getattr(d, "flow_type", None), "product")}
        return {}

    def exchange_views(self, process_id: str) -> List[Dict]:
        """One small dict per exchange of a process, in the shape
        check_process_fields takes."""
        process = self.client.get(o.Process, process_id)
        return self._exchange_views(process) if process is not None else []

    def check_process_fields(self, fields: Dict, views: List[Dict]) -> Dict:
        """
        Check the wider fields of a process against its exchanges
        without writing anything.

        views: one dict per exchange ({"internal_id", "flow_name",
        "is_input", "is_qref", "flow_type", "avoided", "aliases"}), for
        a process that does not exist yet as much as for one that does.
        aliases are other names the exchange goes by (its provider).

        Returns {"ok": True} or {"error", "where", "hint"}; "where" is
        the key the caller gave with the offending entry (its "where"),
        so the language can report the right line.
        """
        try:
            self._resolve_process_fields(fields, views)
            return {"ok": True}
        except _Refused as e:
            return {"error": e.message, "where": e.where, "hint": e.hint}

    def set_process_fields(self, process_id: str, fields: Dict) -> Dict:
        """
        Write the wider fields of a process. fields may hold:

        exchanges: [{"internal_id", "uncertainty": {"kind", "values"} or
            None to remove, "base_uncertainty": n, "avoided": bool,
            "cost": {"value", "formula", "currency"} or None to remove,
            "site": location code or None, "property": flow property}]
        parameters: {name: {"uncertainty": {...} or None}}
        allocation: {"PHYSICAL"|"ECONOMIC"|"CAUSAL": [{"product",
            "value" or "formula", "exchange": {"name", "direction",
            "index"} (causal only)}]}; each method given replaces the
            factors of that method. An empty list removes them.
        default_allocation: PHYSICAL, ECONOMIC, CAUSAL or NONE
        document: {field of DOCUMENT_FIELDS: value}
        social: [{"indicator", "raw", "risk", "activity", "comment",
            "source", "quality"}]; remove_social: [indicator names];
            social_schema: data quality system name
        type: UNIT or LCI_RESULT; infrastructure: bool
        process_pedigree: "(1;2;3;4)" (needs a process schema)

        Everything is checked before anything is written. Returns
        {"process_id", "changes": [...]} or {"error", "where", "hint"}.
        """
        try:
            process = self.client.get(o.Process, process_id)
            if process is None:
                return {"error": f"Process not found: {process_id}"}
            views = self._exchange_views(process)
            plan = self._resolve_process_fields(fields, views, process)
            changes = self._apply_process_fields(process, plan)
            if changes:
                self.client.put(process)
                self._cache.pop("Process", None)
            return {"process_id": process.id, "process_name": process.name,
                    "changes": changes}
        except _Refused as e:
            return {"error": e.message, "where": e.where, "hint": e.hint}
        except Exception as ex:
            return {"error": str(ex)}

    def _resolve_process_fields(self, fields: Dict, views: List[Dict],
                                process=None) -> Dict:
        """Turn names into references and check every rule. Returns the
        plan _apply_process_fields carries out."""
        plan: Dict[str, Any] = {}
        by_id = {v["internal_id"]: v for v in views}

        # exchanges
        ex_plans = []
        avoided_after = {v["internal_id"]: v["avoided"] for v in views}
        for spec in fields.get("exchanges") or []:
            where = spec.get("where")
            view = by_id.get(spec.get("internal_id"))
            if view is None:
                raise _Refused("That exchange is not in the process.", where)
            p: Dict[str, Any] = {"internal_id": view["internal_id"],
                                 "name": view["flow_name"]}
            if "uncertainty" in spec:
                u = spec["uncertainty"]
                if u is None:
                    p["uncertainty"] = None
                else:
                    made, err = make_uncertainty(u["kind"], u["values"])
                    if err:
                        raise _Refused(err, where)
                    p["uncertainty"] = made
            if "base_uncertainty" in spec:
                b = spec["base_uncertainty"]
                if b is not None and float(b) < 0:
                    raise _Refused(
                        f"BASE UNCERTAINTY cannot be negative (got {b:g}).",
                        where)
                p["base_uncertainty"] = None if b is None else float(b)
            if "avoided" in spec:
                want = bool(spec["avoided"])
                if want:
                    if view["is_qref"]:
                        raise _Refused(
                            f"'{view['flow_name']}' is the reference "
                            f"product, and the reference product cannot be "
                            f"an avoided product.", where,
                            hint="Mark a co-product AVOIDED, not the line "
                                 "with PRODUCT.")
                    ok = ((view["flow_type"] == "product"
                           and not view["is_input"])
                          or (view["flow_type"] == "waste"
                              and view["is_input"]))
                    if not ok:
                        raise _Refused(
                            f"AVOIDED is for a product the process makes "
                            f"besides its reference product (an OUTPUT of "
                            f"a product flow). '{view['flow_name']}' is "
                            f"{'an input' if view['is_input'] else 'an output'}"
                            f" of {view['flow_type']} type.", where)
                p["avoided"] = want
                avoided_after[view["internal_id"]] = want
            if "cost" in spec:
                c = spec["cost"]
                if c is None:
                    p["cost"] = None
                else:
                    if view["flow_type"] == "elementary":
                        raise _Refused(
                            f"'{view['flow_name']}' is an elementary flow: "
                            f"openLCA puts costs on product and waste "
                            f"flows only.", where)
                    if not c.get("currency"):
                        raise _Refused("COST needs a currency.", where,
                                       hint="For example: COST 12.5 "
                                            "CURRENCY \"EUR\".")
                    try:
                        cur = self._currency(str(c["currency"]))
                    except _Refused as e:
                        raise _Refused(e.message, where, e.hint)
                    p["cost"] = {"value": float(c.get("value") or 0.0),
                                 "formula": c.get("formula") or None,
                                 "currency": cur}
            if "site" in spec:
                if spec["site"] is None:
                    p["site"] = None
                else:
                    try:
                        p["site"] = self._location(str(spec["site"]))
                    except _Refused as e:
                        raise _Refused(e.message, where, e.hint)
            if "property" in spec and process is not None:
                p["property"] = str(spec["property"])
            elif "property" in spec:
                p["property"] = str(spec["property"])
            ex_plans.append(p)
        if ex_plans:
            plan["exchanges"] = ex_plans

        # parameters
        params = {}
        for name, spec in (fields.get("parameters") or {}).items():
            where = spec.get("where")
            if process is not None and not any(
                    p.name == name for p in process.parameters or []):
                raise _Refused(f"The process has no parameter '{name}'.",
                               where)
            u = spec.get("uncertainty")
            if u is None:
                params[name] = None
            else:
                made, err = make_uncertainty(u["kind"], u["values"])
                if err:
                    raise _Refused(err, where)
                params[name] = made
        if params:
            plan["parameters"] = params

        # allocation
        products = [v for v in views
                    if self._is_product_view(v, avoided_after[v["internal_id"]])]
        alloc_plan = {}
        for word, entries in (fields.get("allocation") or {}).items():
            kind = ALLOCATION_WORDS.get(word.upper())
            if kind not in (o.AllocationType.PHYSICAL_ALLOCATION,
                            o.AllocationType.ECONOMIC_ALLOCATION,
                            o.AllocationType.CAUSAL_ALLOCATION):
                raise _Refused(f"ALLOCATION {word} is not a set of factors. "
                               f"Use PHYSICAL, ECONOMIC or CAUSAL.")
            causal = kind == o.AllocationType.CAUSAL_ALLOCATION
            factors = []
            sums: Dict[Any, float] = {}
            formulas = set()
            for entry in entries:
                where = entry.get("where")
                pname = str(entry["product"])
                match = [v for v in products
                         if v["flow_name"] == pname or v["flow_id"] == pname]
                if not match:
                    listed = ", ".join(f'"{v["flow_name"]}"' for v in products)
                    raise _Refused(
                        f"'{pname}' is not a product of this process. Its "
                        f"products are: {listed or 'none'}.", where,
                        hint="An allocation factor is given per product: "
                             "the reference product and each co-product "
                             "(an OUTPUT of a product flow that is not "
                             "AVOIDED).")
                product = match[0]
                target = None
                if causal:
                    ex = entry.get("exchange")
                    if not ex:
                        raise _Refused(
                            "A causal factor is given per exchange.", where,
                            hint="Write \"product\", share FOR INPUT "
                                 "\"flow\" (or FOR OUTPUT \"flow\").")
                    cands = [v for v in views
                             if (v["flow_name"] == ex["name"]
                                 or ex["name"] in v.get("aliases", ()))
                             and (ex.get("direction") is None
                                  or v["is_input"] == (ex["direction"] == "INPUT"))
                             and not self._is_product_view(
                                 v, avoided_after[v["internal_id"]])]
                    if ex.get("index"):
                        cands = cands[ex["index"] - 1:ex["index"]]
                    if len(cands) != 1:
                        raise _Refused(
                            f"'{ex['name']}' matches {len(cands)} exchanges "
                            f"that a causal factor can apply to.", where,
                            hint="Name an input or an emission of the "
                                 "process; add INDEX n if the flow appears "
                                 "more than once.")
                    target = cands[0]
                elif entry.get("exchange"):
                    raise _Refused(
                        f"{word.upper()} factors are per product, not per "
                        f"exchange.", where,
                        hint="Leave out FOR ..., or use ALLOCATION CAUSAL.")
                key = target["internal_id"] if target else None
                if entry.get("formula"):
                    formulas.add(key)
                    value = 0.0
                else:
                    value = float(entry["value"])
                    if not 0.0 <= value <= 1.0:
                        raise _Refused(
                            f"An allocation share lies between 0 and 1 "
                            f"(got {value:g}).", where)
                    sums[key] = sums.get(key, 0.0) + value
                dupe = [f for f in factors
                        if f["product"] is product and f["target"] is target]
                if dupe:
                    raise _Refused(
                        f"'{pname}' has two {word.upper()} factors"
                        + (f" for '{target['flow_name']}'" if target else "")
                        + ".", where)
                factors.append({"product": product, "target": target,
                                "value": value,
                                "formula": entry.get("formula") or None})
            for key, total in sums.items():
                if key in formulas:
                    continue
                if abs(total - 1.0) > ALLOCATION_SUM_TOLERANCE:
                    scope = (f" for '{by_id[key]['flow_name']}'"
                             if key is not None else "")
                    raise _Refused(
                        f"The {word.upper()} allocation shares{scope} add "
                        f"up to {total:.6g}, not 1.",
                        (entries[0].get("where") if entries else None),
                        hint="The shares of the products must add up to 1.")
            if factors and not causal:
                named = {f["product"]["internal_id"] for f in factors}
                missing = [v["flow_name"] for v in products
                           if v["internal_id"] not in named]
                if missing and not formulas:
                    raise _Refused(
                        f"No {word.upper()} share is given for: "
                        + ", ".join(f"'{m}'" for m in missing) + ".",
                        entries[0].get("where"),
                        hint="Give every product a share (0 is allowed).")
            alloc_plan[kind] = factors
        if alloc_plan:
            plan["allocation"] = alloc_plan

        if "default_allocation" in fields:
            word = str(fields["default_allocation"]).upper()
            kind = ALLOCATION_WORDS.get(word)
            if kind is None or kind == o.AllocationType.USE_DEFAULT_ALLOCATION:
                raise _Refused(
                    f"DEFAULT ALLOCATION {word} is not a method.",
                    fields.get("default_allocation_where"),
                    hint="Use PHYSICAL, ECONOMIC, CAUSAL or NONE.")
            plan["default_allocation"] = kind

        # documentation
        doc = {}
        for field_name, value in (fields.get("document") or {}).items():
            where = (fields.get("document_where") or {}).get(field_name)
            kind = DOCUMENT_FIELDS.get(field_name)
            if kind is None:
                raise _Refused(f"Unknown documentation field "
                               f"'{field_name}'.", where)
            try:
                doc[field_name] = self._doc_value(kind, value)
            except _Refused as e:
                raise _Refused(e.message, where, e.hint)
        if doc:
            plan["document"] = doc

        # social aspects
        social = []
        for entry in fields.get("social") or []:
            where = entry.get("where")
            try:
                d = self._one_by_name(
                    o.SocialIndicator, str(entry["indicator"]),
                    "social indicator", "Make one with MAKE SOCIAL INDICATOR.")
            except _Refused as e:
                raise _Refused(e.message, where, e.hint)
            risk = str(entry.get("risk") or "").upper().replace(" ", "_")
            if risk not in RISK_LEVELS:
                raise _Refused(
                    f"'{entry.get('risk')}' is not a risk level.", where,
                    hint="Use one of: " + ", ".join(
                        r.replace("_", " ") for r in RISK_LEVELS) + ".")
            aspect = o.SocialAspect(
                social_indicator=o.Ref(id=d.id, name=d.name,
                                       ref_type=o.RefType.SocialIndicator),
                raw_amount=(None if entry.get("raw") is None
                            else str(entry["raw"])),
                risk_level=o.RiskLevel[risk])
            if entry.get("activity") is not None:
                aspect.activity_value = float(entry["activity"])
            if entry.get("comment") is not None:
                aspect.comment = str(entry["comment"])
            if entry.get("quality") is not None:
                aspect.quality = str(entry["quality"])
            if entry.get("source") is not None:
                try:
                    aspect.source = self._source(str(entry["source"]))
                except _Refused as e:
                    raise _Refused(e.message, where, e.hint)
            social.append(aspect)
        if social:
            plan["social"] = social
        if fields.get("remove_social"):
            plan["remove_social"] = [str(n) for n in fields["remove_social"]]
        for key in ("social_schema",):
            if fields.get(key) is not None:
                ref = self._resolve_dq_system(str(fields[key]))
                if ref is None:
                    raise _Refused(
                        f"Data quality system '{fields[key]}' not found.",
                        fields.get(key + "_where"),
                        hint="PRINT DQ SYSTEMS lists the names.")
                plan[key] = ref

        if "type" in fields:
            word = str(fields["type"]).upper().replace(" ", "_")
            kinds = {"UNIT": o.ProcessType.UNIT_PROCESS,
                     "UNIT_PROCESS": o.ProcessType.UNIT_PROCESS,
                     "LCI_RESULT": o.ProcessType.LCI_RESULT}
            if word not in kinds:
                raise _Refused(f"TYPE {fields['type']} is not a process type.",
                               fields.get("type_where"),
                               hint="Use TYPE UNIT or TYPE LCI RESULT.")
            plan["type"] = kinds[word]
        if "infrastructure" in fields:
            plan["infrastructure"] = bool(fields["infrastructure"])
        if fields.get("process_pedigree") is not None:
            entry, err = self._parse_dq_entry(fields["process_pedigree"])
            if err:
                raise _Refused(err, fields.get("process_pedigree_where"))
            schema = getattr(process, "dq_system", None) if process else None
            if process is not None and schema is None \
                    and not fields.get("has_process_schema"):
                raise _Refused(
                    "PROCESS PEDIGREE needs a data quality system for the "
                    "process.", fields.get("process_pedigree_where"),
                    hint="Add PROCESS SCHEMA \"name\" to the block (PRINT "
                         "DQ SYSTEMS lists the names).")
            if schema is not None:
                names = self._dq_indicator_names(schema)
                scores = [s for s in entry.strip("()").split(";") if s]
                if names and len(scores) != len(names):
                    raise _Refused(
                        f"PROCESS PEDIGREE has {len(scores)} scores, and "
                        f"the process's data quality system has "
                        f"{len(names)} indicators.",
                        fields.get("process_pedigree_where"))
            plan["process_pedigree"] = entry
        return plan

    def _doc_value(self, kind: str, value):
        if kind == "text":
            return str(value)
        if kind == "bool":
            return bool(value)
        if kind == "date":
            iso, err = parse_date(value)
            if err:
                raise _Refused(err)
            return iso
        if kind == "actor":
            return self._actor(str(value))
        if kind == "source":
            return self._source(str(value))
        if kind == "sources":
            return [self._source(str(v)) for v in value]
        if kind == "aspects":
            return [o.AspectValue(aspect=str(a), value=str(v))
                    for a, v in value]
        if kind == "reviews":
            out = []
            for r in value:
                review = o.Review(review_type=str(r.get("type") or ""))
                if r.get("details") is not None:
                    review.details = str(r["details"])
                if r.get("report") is not None:
                    review.report = self._source(str(r["report"]))
                if r.get("reviewers"):
                    review.reviewers = [self._actor(str(a))
                                        for a in r["reviewers"]]
                if r.get("scopes"):
                    review.scopes = [
                        o.ReviewScope(name=str(s["name"]),
                                      methods=[str(m) for m in
                                               s.get("methods") or []])
                        for s in r["scopes"]]
                if r.get("assessment"):
                    review.assessment = [
                        o.AspectValue(aspect=str(a), value=str(v))
                        for a, v in r["assessment"]]
                out.append(review)
            return out
        if kind == "compliance":
            out = []
            for c in value:
                decl = o.ComplianceDeclaration(
                    system=self._source(str(c["system"])))
                if c.get("comment") is not None:
                    decl.comment = str(c["comment"])
                if c.get("aspects"):
                    decl.aspects = [o.AspectValue(aspect=str(a), value=str(v))
                                    for a, v in c["aspects"]]
                out.append(decl)
            return out
        raise _Refused(f"Unknown kind of documentation field: {kind}")

    def _apply_process_fields(self, process, plan: Dict) -> List[str]:
        changes: List[str] = []
        by_id = {ex.internal_id: ex for ex in process.exchanges or []}
        for p in plan.get("exchanges") or []:
            ex = by_id[p["internal_id"]]
            name = p["name"]
            if "uncertainty" in p:
                ex.uncertainty = p["uncertainty"]
                changes.append(
                    f"exchange '{name}' uncertainty "
                    + (f"set to {describe_uncertainty(p['uncertainty'])}"
                       if p["uncertainty"] is not None else "removed"))
            if "base_uncertainty" in p:
                ex.base_uncertainty = p["base_uncertainty"]
                changes.append(f"exchange '{name}' base uncertainty set to "
                               f"{p['base_uncertainty']}")
            if "avoided" in p:
                ex.is_avoided_product = p["avoided"]
                changes.append(f"exchange '{name}' "
                               + ("marked as an avoided product"
                                  if p["avoided"] else
                                  "no longer an avoided product"))
            if "cost" in p:
                c = p["cost"]
                if c is None:
                    ex.cost_value = ex.cost_formula = ex.currency = None
                    changes.append(f"exchange '{name}' cost removed")
                else:
                    ex.cost_value = c["value"]
                    ex.cost_formula = c["formula"]
                    ex.currency = c["currency"]
                    shown = c["formula"] or f"{c['value']:g}"
                    changes.append(f"exchange '{name}' cost set to {shown} "
                                   f"{c['currency'].name}")
            if "site" in p:
                ex.location = p["site"]
                changes.append(
                    f"exchange '{name}' site "
                    + (f"set to {p['site'].name}" if p["site"] is not None
                       else "removed"))
            if "property" in p:
                fp_ref, u_ref, err = self._exchange_unit_in_property(
                    ex.flow.id, ex.unit.name if ex.unit else "",
                    p["property"])
                if err:
                    raise _Refused(err)
                ex.flow_property, ex.unit = fp_ref, u_ref
                changes.append(f"exchange '{name}' flow property set to "
                               f"{fp_ref.name}")
        for name, unc in (plan.get("parameters") or {}).items():
            for param in process.parameters or []:
                if param.name == name:
                    param.uncertainty = unc
                    changes.append(
                        f"parameter '{name}' uncertainty "
                        + (f"set to {describe_uncertainty(unc)}"
                           if unc is not None else "removed"))
        if "allocation" in plan:
            factors = list(process.allocation_factors or [])
            for kind, entries in plan["allocation"].items():
                factors = [f for f in factors if f.allocation_type != kind]
                for e in entries:
                    f = o.AllocationFactor(
                        allocation_type=kind,
                        product=o.Ref(id=e["product"]["flow_id"],
                                      name=e["product"]["flow_name"],
                                      ref_type=o.RefType.Flow),
                        value=e["value"])
                    if e["formula"]:
                        f.formula = e["formula"]
                    if e["target"] is not None:
                        f.exchange = o.ExchangeRef(
                            internal_id=e["target"]["internal_id"])
                    factors.append(f)
                word = ALLOCATION_NAMES[kind].lower()
                changes.append(
                    f"{word} allocation: {len(entries)} factor"
                    f"{'s' if len(entries) != 1 else ''} set" if entries
                    else f"{word} allocation factors removed")
            process.allocation_factors = factors
        if "default_allocation" in plan:
            process.default_allocation_method = plan["default_allocation"]
            changes.append(
                "default allocation set to "
                + ALLOCATION_NAMES[plan["default_allocation"]])
        if "document" in plan:
            doc = process.process_documentation or o.ProcessDocumentation()
            for field_name, value in plan["document"].items():
                setattr(doc, field_name, value)
            process.process_documentation = doc
            changes.append(f"documentation: {len(plan['document'])} field"
                           f"{'s' if len(plan['document']) != 1 else ''} set")
        if plan.get("remove_social"):
            before = list(process.social_aspects or [])
            gone = set(plan["remove_social"])
            kept = [a for a in before if not (
                a.social_indicator and (a.social_indicator.name in gone
                                        or a.social_indicator.id in gone))]
            if len(kept) == len(before):
                raise _Refused(
                    "The process has no social aspect for: "
                    + ", ".join(sorted(gone)) + ".")
            process.social_aspects = kept
            changes.append(f"{len(before) - len(kept)} social aspect(s) "
                           f"removed")
        if plan.get("social"):
            aspects = list(process.social_aspects or [])
            for a in plan["social"]:
                aspects = [x for x in aspects if not (
                    x.social_indicator
                    and x.social_indicator.id == a.social_indicator.id)]
                aspects.append(a)
                changes.append(f"social aspect '{a.social_indicator.name}' "
                               f"set")
            process.social_aspects = aspects
        if "social_schema" in plan:
            process.social_dq_system = plan["social_schema"]
            changes.append(f"social schema set to "
                           f"{plan['social_schema'].name}")
        if "type" in plan:
            process.process_type = plan["type"]
            changes.append("type set to " + (
                "LCI RESULT" if plan["type"] == o.ProcessType.LCI_RESULT
                else "UNIT"))
        if "infrastructure" in plan:
            process.is_infrastructure_process = plan["infrastructure"]
            changes.append("marked as an infrastructure process"
                           if plan["infrastructure"]
                           else "no longer an infrastructure process")
        if "process_pedigree" in plan:
            process.dq_entry = plan["process_pedigree"]
            changes.append(f"process pedigree set to "
                           f"{plan['process_pedigree']}")
        return changes

    def _exchange_unit_in_property(self, flow_id: str, unit_name: str,
                                   property_name: str):
        """Like _exchange_unit, for one named property of the flow."""
        flow = self.client.get(o.Flow, flow_id)
        if flow is None:
            return None, None, f"flow {flow_id} not found"
        names = []
        for f in flow.flow_properties or []:
            if not f.flow_property:
                continue
            fp = self.client.get(o.FlowProperty, f.flow_property.id)
            fp_name = fp.name if fp else f.flow_property.name
            names.append(fp_name)
            if fp_name != property_name and f.flow_property.id != property_name:
                continue
            ug = (self.client.get(o.UnitGroup, fp.unit_group.id)
                  if fp and fp.unit_group else None)
            for u in (ug.units or []) if ug else []:
                if u.name == unit_name or unit_name in (u.synonyms or []):
                    return (o.Ref(id=f.flow_property.id, name=fp_name,
                                  ref_type=o.RefType.FlowProperty),
                            o.Ref(id=u.id, name=u.name,
                                  ref_type=o.RefType.Unit), None)
            return None, None, (
                f"unit '{unit_name}' is not a unit of the flow property "
                f"'{fp_name}'.")
        return None, None, (
            f"flow '{flow.name}' has no property '{property_name}'. Its "
            f"properties: {', '.join(names)}. EDIT FLOW adds one.")

    def get_process_fields(self, process_id: str) -> Dict:
        """Everything set_process_fields can write, read back: per
        exchange (uncertainty, base uncertainty, avoided, cost, site,
        flow property), parameter uncertainties, allocation factors,
        default allocation, documentation, social aspects, type,
        infrastructure flag and process pedigree."""
        process = self.client.get(o.Process, process_id)
        if process is None:
            return {"error": f"Process not found: {process_id}"}
        names = {ex.internal_id: (ex.flow.name if ex.flow else "")
                 for ex in process.exchanges or []}
        exchanges = []
        for ex in process.exchanges or []:
            exchanges.append({
                "internal_id": ex.internal_id,
                "flow": ex.flow.name if ex.flow else "",
                "is_input": bool(ex.is_input),
                "is_qref": bool(ex.is_quantitative_reference),
                "avoided": bool(ex.is_avoided_product),
                "uncertainty": uncertainty_dict(ex.uncertainty),
                "base_uncertainty": ex.base_uncertainty,
                "cost": ({"value": ex.cost_value, "formula": ex.cost_formula,
                          "currency": ex.currency.name if ex.currency else ""}
                         if (ex.cost_value is not None or ex.cost_formula)
                         else None),
                "site": ex.location.name if ex.location else "",
                "property": ex.flow_property.name if ex.flow_property else "",
                "comment": ex.description or "",
            })
        allocation: Dict[str, List[Dict]] = {}
        for f in process.allocation_factors or []:
            word = ALLOCATION_NAMES.get(f.allocation_type, "?")
            allocation.setdefault(word, []).append({
                "product": f.product.name if f.product else "",
                "value": f.value, "formula": f.formula or "",
                "exchange": (names.get(f.exchange.internal_id, "")
                             if f.exchange is not None else ""),
            })
        doc = process.process_documentation
        document: Dict[str, Any] = {}
        if doc is not None:
            for field_name, kind in DOCUMENT_FIELDS.items():
                value = getattr(doc, field_name, None)
                if value in (None, [], ""):
                    continue
                document[field_name] = self._doc_plain(kind, value)
        social = []
        for a in process.social_aspects or []:
            social.append({
                "indicator": a.social_indicator.name if a.social_indicator else "",
                "raw": a.raw_amount, "risk": a.risk_level.name if a.risk_level else "",
                "activity": a.activity_value, "comment": a.comment or "",
                "source": a.source.name if a.source else "",
                "quality": a.quality or ""})
        default = process.default_allocation_method
        return {
            "process_id": process.id, "process_name": process.name,
            "type": ("LCI RESULT" if process.process_type
                     == o.ProcessType.LCI_RESULT else "UNIT"),
            "infrastructure": bool(process.is_infrastructure_process),
            "default_allocation": ALLOCATION_NAMES.get(default, "")
            if default is not None else "",
            "exchanges": exchanges,
            "parameters": {
                p.name: uncertainty_dict(p.uncertainty)
                for p in process.parameters or []
                if p.uncertainty is not None},
            "allocation": allocation,
            "document": document,
            "social": social,
            "social_schema": (process.social_dq_system.name
                              if process.social_dq_system else ""),
            "process_pedigree": process.dq_entry or "",
        }

    @staticmethod
    def _doc_plain(kind: str, value):
        if kind in ("text", "bool"):
            return value
        if kind == "date":
            return str(value)[:10]
        if kind in ("actor", "source"):
            return value.name
        if kind == "sources":
            return [v.name for v in value]
        if kind == "aspects":
            return [{"aspect": a.aspect, "value": a.value} for a in value]
        if kind == "reviews":
            return [{"type": r.review_type or "",
                     "details": r.details or "",
                     "report": r.report.name if r.report else "",
                     "reviewers": [a.name for a in r.reviewers or []],
                     "scopes": [{"name": s.name, "methods": s.methods or []}
                                for s in r.scopes or []],
                     "assessment": [{"aspect": a.aspect, "value": a.value}
                                    for a in r.assessment or []]}
                    for r in value]
        if kind == "compliance":
            return [{"system": c.system.name if c.system else "",
                     "comment": c.comment or "",
                     "aspects": [{"aspect": a.aspect, "value": a.value}
                                 for a in c.aspects or []]}
                    for c in value]
        return value

    # ── global parameters ────────────────────────────────────

    def set_parameter_uncertainty(self, name: str,
                                  uncertainty: Optional[Dict]) -> Dict:
        """Set (or with None remove) the uncertainty distribution of a
        global input parameter."""
        made = None
        if uncertainty is not None:
            made, err = make_uncertainty(uncertainty["kind"],
                                         uncertainty["values"])
            if err:
                return {"error": err}
        for d in self._get_descriptors(o.Parameter):
            if d.name != name:
                continue
            param = self.client.get(o.Parameter, d.id)
            if param is None:
                continue
            if made is not None and not param.is_input_parameter:
                return {"error": f"'{name}' is calculated from a formula, "
                                 f"so it has no uncertainty of its own. Put "
                                 f"the uncertainty on the parameters it is "
                                 f"calculated from."}
            param.uncertainty = made
            self.client.put(param)
            return {"name": name,
                    "uncertainty": describe_uncertainty(made)}
        return {"error": f"Global parameter not found: {name}"}

    # ── flows ────────────────────────────────────────────────

    def set_flow_fields(self, flow_id: str, fields: Dict) -> Dict:
        """Write a flow's cas, formula, synonyms, location,
        infrastructure flag and description. Only the keys given are
        changed; None clears a text field or the location."""
        try:
            flow = self.client.get(o.Flow, flow_id)
            if flow is None:
                return {"error": f"Flow not found: {flow_id}"}
            changes = []
            for key in ("cas", "formula", "synonyms", "description"):
                if key in fields:
                    value = fields[key]
                    setattr(flow, key, None if value is None else str(value))
                    changes.append(f"{key} " + ("removed" if value is None
                                                else f"set to '{value}'"))
            if "location" in fields:
                if fields["location"] is None:
                    flow.location = None
                    changes.append("location removed")
                else:
                    flow.location = self._location(str(fields["location"]))
                    changes.append(f"location set to {flow.location.name}")
            if "infrastructure" in fields:
                flow.is_infrastructure_flow = bool(fields["infrastructure"])
                changes.append("marked as an infrastructure flow"
                               if fields["infrastructure"]
                               else "no longer an infrastructure flow")
            if changes:
                self.client.put(flow)
                self._cache.pop("Flow", None)
            return {"flow_id": flow.id, "flow_name": flow.name,
                    "changes": changes}
        except _Refused as e:
            return {"error": e.message, "hint": e.hint}
        except Exception as ex:
            return {"error": str(ex)}

    def get_flow_fields(self, flow_id: str) -> Dict:
        flow = self.client.get(o.Flow, flow_id)
        if flow is None:
            return {"error": f"Flow not found: {flow_id}"}
        return {"flow_id": flow.id, "flow_name": flow.name,
                "cas": flow.cas or "", "formula": flow.formula or "",
                "synonyms": flow.synonyms or "",
                "description": flow.description or "",
                "location": flow.location.name if flow.location else "",
                "infrastructure": bool(flow.is_infrastructure_flow)}

    # ── product systems ──────────────────────────────────────

    def set_system_fields(self, system_ref: str,
                          parameter_sets: Optional[List[Dict]] = None,
                          analysis_groups: Optional[List[Dict]] = None,
                          remove_parameter_sets: Optional[List[str]] = None,
                          remove_analysis_groups: Optional[List[str]] = None,
                          description: Optional[str] = None) -> Dict:
        """
        Write parameter sets and analysis groups on a product system.

        parameter_sets: [{"name", "baseline": bool, "description",
            "values": [{"name", "value", "process": name or None,
            "where"}]}]. A value without a process redefines every
            input parameter of that name in the system (the global one
            and each process's own), as scenarios do. A set replaces the
            stored set of the same name.
        analysis_groups: [{"name", "color", "processes": [{"name",
            "location", "where"}]}]. A group replaces the stored group
            of the same name. A process can be in one group only.

        Returns {"system", "system_id", "changes"} or {"error", "where",
        "hint"}.
        """
        try:
            desc = self._resolve_system(system_ref)
            if desc is None:
                return {"error": f"Product system not found: {system_ref}"}
            system = self.client.get(o.ProductSystem, desc.id)
            changes: List[str] = []
            if description is not None:
                system.description = description
                changes.append("description updated")

            sets = list(system.parameter_sets or [])
            for name in remove_parameter_sets or []:
                kept = [s for s in sets if s.name != name]
                if len(kept) == len(sets):
                    raise _Refused(
                        f"'{system.name}' has no parameter set '{name}'.")
                sets = kept
                changes.append(f"parameter set '{name}' removed")
            targets = None
            for spec in parameter_sets or []:
                if targets is None:
                    targets = self._parameter_targets(system)
                redefs = []
                for v in spec.get("values") or []:
                    where = v.get("where")
                    copies = targets.get(v["name"])
                    if not copies:
                        raise _Refused(
                            f"'{system.name}' has no parameter "
                            f"'{v['name']}'.", where,
                            hint=f"SHOW SYSTEM \"{system.name}\" PARAMS "
                                 f"lists the parameters that can be set.")
                    usable = [c for c in copies if c["is_input"]]
                    if not usable:
                        raise _Refused(
                            f"'{v['name']}' is calculated from a formula, "
                            f"so it cannot be given a value.", where,
                            hint="Set the parameters it is calculated "
                                 "from.")
                    if v.get("process"):
                        usable = [c for c in usable if c["context"] is not None
                                  and (c["context"].name == v["process"]
                                       or c["context"].id == v["process"])]
                        if not usable:
                            raise _Refused(
                                f"No process called '{v['process']}' in "
                                f"'{system.name}' has a parameter "
                                f"'{v['name']}'.", where)
                    for c in usable:
                        redefs.append(o.ParameterRedef(
                            name=v["name"], value=float(v["value"]),
                            context=c["context"]))
                made = o.ParameterRedefSet(
                    name=spec["name"], parameters=redefs,
                    is_baseline=bool(spec.get("baseline")),
                    description=spec.get("description") or None)
                existed = any(s.name == spec["name"] for s in sets)
                sets = [s for s in sets if s.name != spec["name"]]
                if made.is_baseline:
                    for s in sets:
                        if s.is_baseline:
                            s.is_baseline = False
                            changes.append(f"parameter set '{s.name}' is no "
                                           f"longer the baseline")
                sets.append(made)
                changes.append(
                    f"parameter set '{spec['name']}' "
                    f"{'replaced' if existed else 'added'} "
                    f"({len(spec.get('values') or [])} parameter"
                    f"{'s' if len(spec.get('values') or []) != 1 else ''}"
                    f"{', baseline' if made.is_baseline else ''})")
            if parameter_sets or remove_parameter_sets:
                system.parameter_sets = sets

            groups = list(system.analysis_groups or [])
            for name in remove_analysis_groups or []:
                kept = [g for g in groups if g.name != name]
                if len(kept) == len(groups):
                    raise _Refused(
                        f"'{system.name}' has no analysis group '{name}'.")
                groups = kept
                changes.append(f"analysis group '{name}' removed")
            if analysis_groups:
                in_system = self._system_processes(system)
                for spec in analysis_groups:
                    refs = []
                    for p in spec.get("processes") or []:
                        where = p.get("where")
                        found = [d for d in in_system
                                 if d.id == p["name"] or d.name == p["name"]]
                        if p.get("location"):
                            found = [d for d in found if (
                                getattr(d, "location", "") or "")
                                == p["location"]]
                        if not found:
                            raise _Refused(
                                f"No process called '{p['name']}'"
                                + (f" at '{p['location']}'"
                                   if p.get("location") else "")
                                + f" is in '{system.name}'.", where,
                                hint=f"SHOW SYSTEM \"{system.name}\" LINKS "
                                     f"shows the processes of the system.")
                        if len(found) > 1:
                            listing = "\n".join(
                                f"    {getattr(d, 'location', '') or '(no location)':<16} {d.id}"
                                for d in found[:12])
                            raise _Refused(
                                f"'{p['name']}' matches {len(found)} "
                                f"processes of '{system.name}':\n{listing}",
                                where,
                                hint="Add LOCATION \"code\", or use the "
                                     "UUID in place of the name.")
                        refs.append(o.Ref(id=found[0].id, name=found[0].name,
                                          ref_type=o.RefType.Process))
                    existed = any(g.name == spec["name"] for g in groups)
                    groups = [g for g in groups if g.name != spec["name"]]
                    for g in groups:
                        clash = {r.id for r in g.processes or []} & {
                            r.id for r in refs}
                        if clash:
                            name = next(r.name for r in refs if r.id in clash)
                            raise _Refused(
                                f"'{name}' is already in the analysis group "
                                f"'{g.name}': a process can be in one group "
                                f"only.",
                                (spec.get("processes") or [{}])[0].get("where"))
                    if len({r.id for r in refs}) != len(refs):
                        raise _Refused(
                            f"A process is named twice in the analysis "
                            f"group '{spec['name']}'.")
                    groups.append(o.AnalysisGroup(
                        name=spec["name"], color=spec.get("color") or None,
                        processes=refs))
                    changes.append(
                        f"analysis group '{spec['name']}' "
                        f"{'replaced' if existed else 'added'} "
                        f"({len(refs)} process"
                        f"{'es' if len(refs) != 1 else ''})")
            if analysis_groups or remove_analysis_groups:
                system.analysis_groups = groups

            if changes:
                self.client.put(system)
                self._cache.pop("ProductSystem", None)
            return {"system": system.name, "system_id": system.id,
                    "changes": changes}
        except _Refused as e:
            return {"error": e.message, "where": e.where, "hint": e.hint}
        except Exception as ex:
            return {"error": str(ex)}

    def _system_processes(self, system) -> list:
        """Descriptors of the processes in a product system."""
        ids = []
        if system.ref_process is not None:
            ids.append(system.ref_process.id)
        for ref in system.processes or []:
            if ref.id not in ids:
                ids.append(ref.id)
        wanted = set(ids)
        return [d for d in self._get_descriptors(o.Process) if d.id in wanted]

    def get_system_fields(self, system_ref: str) -> Dict:
        """The parameter sets and analysis groups stored on a system."""
        desc = self._resolve_system(system_ref)
        if desc is None:
            return {"error": f"Product system not found: {system_ref}"}
        system = self.client.get(o.ProductSystem, desc.id)
        sets = []
        for s in system.parameter_sets or []:
            sets.append({
                "name": s.name, "baseline": bool(s.is_baseline),
                "description": s.description or "",
                "values": [{"name": r.name, "value": r.value,
                            "process": r.context.name if r.context else ""}
                           for r in s.parameters or []]})
        groups = [{"name": g.name, "color": g.color or "",
                   "processes": [r.name or r.id for r in g.processes or []]}
                  for g in system.analysis_groups or []]
        return {"system": system.name, "system_id": system.id,
                "description": system.description or "",
                "parameter_sets": sets, "analysis_groups": groups}
