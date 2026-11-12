"""
Results that stay open, and every question openLCA can answer about one.

A calculation is expensive; reading one more thing from its result is
not. open_result() calculates and keeps the result in openLCA until
close_result(). result_query() then reads totals, contributions,
inventory, factors, intensities, scaling, requirements, upstream trees,
costs, normalised and weighted results, grouped results and Sankey
data from it.

Every query returns the same shape:

    {"query": name, "title": text, "system": ..., "method": ...,
     "columns": [key, ...], "rows": [{key: value, ...}, ...]}

so the language can print, cut (TOP n) and save (CSV) any of them the
same way. Trees add "root"; Sankey adds "nodes" and "edges".

Part of olcabasic.engine.Engine (see engine.py).
"""

import atexit
import uuid
import weakref
from typing import Any, Callable, Dict, List, Optional, Tuple

import olca_schema as o

from .ipc_methods import IPC_METHODS, needs_version

#: A Session holds no more than this many open results at once.
MAX_OPEN_RESULTS = 5

_NOT_UNDERSTOOD = "does not understand"

# Engines that have opened a result. When Python exits, whatever they
# still hold open is disposed, so nothing is left behind in openLCA
# even if a program stopped on an error.
_ENGINES: "weakref.WeakSet" = weakref.WeakSet()


def close_everything() -> int:
    """Dispose every result every live engine holds open."""
    n = 0
    for engine in list(_ENGINES):
        try:
            n += engine.close_all_results()
        except Exception:
            pass
    return n


atexit.register(close_everything)


def _dispose_all(results: Dict) -> None:
    """Dispose what an engine that is being garbage-collected left open."""
    for r in list(results.values()):
        ResultsMixin._dispose(r)
    results.clear()


class OpenResult:
    """One calculation result held open in openLCA."""

    def __init__(self, handle: str, result, system, method, setup: Dict):
        self.handle = handle
        self.result = result
        self.system = system
        self.method = method
        self.setup = setup            # what was asked for, in plain values
        self.disposed = False
        self._tech_flows = None
        self._envi_flows = None
        self._categories = None
        self._groups = None

    @property
    def with_costs(self) -> bool:
        return bool(self.setup.get("with_costs"))

    @property
    def nw_set(self) -> str:
        return self.setup.get("nw_set") or ""

    def key(self) -> Tuple:
        """What makes two calculations the same calculation."""
        s = self.setup
        return (self.system.id, self.method.id if self.method else None,
                s.get("allocation") or "as_defined", s.get("amount"),
                s.get("unit"), s.get("flow_property"),
                bool(s.get("with_regionalisation")),
                tuple(sorted((s.get("parameters") or {}).items())),
                s.get("parameter_set") or "")


class ResultsMixin:
    """Open results and the queries on them."""

    MAX_OPEN_RESULTS = MAX_OPEN_RESULTS

    # ── what the server can do ───────────────────────────────

    def ipc_supports(self, method: str) -> bool:
        """True if the IPC server answers this method. Servers before
        the version that added a method reply "Does not understand"."""
        known = self.__dict__.setdefault("_ipc_support", {})
        if method not in known:
            _, err = self.client.rpc_call(method, None)
            known[method] = not (err and _NOT_UNDERSTOOD in str(err).lower())
        return known[method]

    def _unsupported(self, method: str, what: str) -> Dict:
        since = needs_version(method)
        return {"error": f"{what} needs openLCA {since} or later: this "
                         f"openLCA's IPC server has no '{method}' method.",
                "hint": f"Update openLCA to {since} or later to use it."}

    # ── opening and closing ──────────────────────────────────

    def _results(self) -> Dict[str, OpenResult]:
        if "_open_results" not in self.__dict__:
            self.__dict__["_open_results"] = {}
            _ENGINES.add(self)
            # an engine that is thrown away takes its results with it
            weakref.finalize(self, _dispose_all,
                             self.__dict__["_open_results"])
        return self.__dict__["_open_results"]

    def open_results(self) -> List[Dict]:
        """The results that are open: handle, system, method, setup."""
        return [{"handle": r.handle, "system": r.system.name,
                 "method": r.method.name if r.method else "",
                 "setup": dict(r.setup)} for r in self._results().values()]

    def result_setup_key(self, handle: str) -> Optional[Tuple]:
        r = self._results().get(handle)
        return r.key() if r else None

    def close_result(self, handle: str) -> bool:
        """Dispose one open result. True if it was open."""
        r = self._results().pop(handle, None)
        if r is None:
            return False
        self._dispose(r)
        return True

    def close_all_results(self) -> int:
        """Dispose every open result. Returns how many there were."""
        results = list(self._results().values())
        self._results().clear()
        for r in results:
            self._dispose(r)
        return len(results)

    @staticmethod
    def _dispose(r: OpenResult):
        if r.disposed:
            return
        r.disposed = True
        try:
            r.result.dispose()
        except Exception:
            pass

    def _nw_set_ref(self, method, name: str):
        """(Ref, error) for a normalisation and weighting set of a method."""
        full = self.client.get(o.ImpactMethod, method.id)
        sets = list(getattr(full, "nw_sets", None) or [])
        for s in sets:
            if s.id == name or s.name == name:
                return o.Ref(id=s.id, name=s.name), None
        close = [s for s in sets if name.lower() in (s.name or "").lower()]
        if len(close) == 1:
            return o.Ref(id=close[0].id, name=close[0].name), None
        if not sets:
            return None, (f"'{method.name}' has no normalisation and "
                          f"weighting sets.")
        names = ", ".join(f'"{s.name}"' for s in sets)
        return None, (f"'{method.name}' has no NW set called '{name}'. "
                      f"Its sets: {names}.")

    def _property_ref(self, name: str):
        for d in self._get_descriptors(o.FlowProperty):
            if d.id == name or d.name == name:
                return d
        return None

    def build_setup(self, system_ref: str, method_ref: Optional[str] = None,
                    allocation: Optional[str] = None,
                    amount: Optional[float] = None,
                    unit: Optional[str] = None,
                    flow_property: Optional[str] = None,
                    with_costs: bool = False,
                    with_regionalisation: bool = False,
                    nw_set: Optional[str] = None,
                    parameters: Optional[Dict[str, float]] = None,
                    parameter_set: Optional[str] = None) -> Dict:
        """Resolve the names of a calculation into an
        olca_schema.CalculationSetup. Returns {"setup", "system",
        "method", "plain"} or {"error"}."""
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}
        method = None
        if method_ref:
            method = self._resolve_method(method_ref)
            if not method:
                return {"error": f"Impact method not found: {method_ref}"}
        try:
            alloc = self._resolve_allocation(allocation)
        except ValueError as e:
            return {"error": str(e)}

        plain: Dict[str, Any] = {
            "allocation": (allocation or "as_defined").lower(),
            "with_costs": bool(with_costs),
            "with_regionalisation": bool(with_regionalisation),
        }
        setup = o.CalculationSetup(target=system, impact_method=method,
                                   allocation=alloc)
        if with_costs:
            setup.with_costs = True
        if with_regionalisation:
            setup.with_regionalization = True

        if amount is not None:
            if unit is None:
                return {"error": "AMOUNT needs a unit, for example "
                                 "AMOUNT 2.5 kg."}
            setup.amount = float(amount)
            plain["amount"] = float(amount)
        if unit is not None:
            unit_ref = self._get_unit_ref(unit)
            if unit_ref is None:
                return {"error": f"Unit '{unit}' is not in this database. "
                                 f"FIND UNIT \"{unit}\" shows the units "
                                 f"there are."}
            setup.unit = unit_ref
            plain["unit"] = unit
        if flow_property is not None:
            prop = self._property_ref(flow_property)
            if prop is None:
                return {"error": f"Flow property not found: {flow_property}"}
            setup.flow_property = o.Ref(id=prop.id, name=prop.name)
            plain["flow_property"] = prop.name

        if nw_set:
            if method is None:
                return {"error": "NW SET needs an impact method."}
            ref, err = self._nw_set_ref(method, nw_set)
            if err:
                return {"error": err}
            setup.nw_set = ref
            plain["nw_set"] = ref.name

        redefs: List[o.ParameterRedef] = []
        if parameter_set:
            full = self.client.get(o.ProductSystem, system.id)
            sets = list(getattr(full, "parameter_sets", None) or [])
            chosen = next((s for s in sets if s.name == parameter_set), None)
            if chosen is None:
                names = ", ".join(f'"{s.name}"' for s in sets) or "none"
                return {"error": f"'{system.name}' has no parameter set "
                                 f"called '{parameter_set}'. Its sets: "
                                 f"{names}."}
            redefs.extend(chosen.parameters or [])
            plain["parameter_set"] = chosen.name
        if parameters:
            targets = self._parameter_targets(system, set(parameters))
            split = self._split_targets(targets, list(parameters))
            if split["missing"]:
                return {"error": "Parameter(s) not found in the system: "
                                 + ", ".join(split["missing"])}
            if split["dependent"]:
                return {"error": "Parameter(s) calculated by a formula, "
                                 "which cannot be given a value: "
                                 + ", ".join(split["dependent"])}
            for name, value in parameters.items():
                for copy in targets[name]:
                    if copy["is_input"]:
                        redefs.append(o.ParameterRedef(
                            name=name, value=float(value),
                            context=copy["context"]))
            plain["parameters"] = {k: float(v) for k, v in parameters.items()}
        if redefs:
            setup.parameters = redefs
        return {"setup": setup, "system": system, "method": method,
                "plain": plain}

    def open_result(self, system_ref: str, method_ref: Optional[str] = None,
                    allocation: Optional[str] = None,
                    amount: Optional[float] = None,
                    unit: Optional[str] = None,
                    flow_property: Optional[str] = None,
                    with_costs: bool = False,
                    with_regionalisation: bool = False,
                    nw_set: Optional[str] = None,
                    parameters: Optional[Dict[str, float]] = None,
                    parameter_set: Optional[str] = None,
                    simulate: bool = False,
                    temporary: bool = False) -> Dict:
        """
        Calculate a product system and keep the result open.

        Returns {"handle", "system", "system_id", "method", "method_id",
        "setup", "impacts", "demand"}; close it with close_result(handle).
        No more than MAX_OPEN_RESULTS can be open at once. If anything
        fails after openLCA has made the result, it is disposed before
        the error is returned. temporary=True is for a result the caller
        closes again at once; it does not count towards the limit.
        """
        if not temporary and len(self._results()) >= self.MAX_OPEN_RESULTS:
            return {"error": f"{self.MAX_OPEN_RESULTS} results are open "
                             f"already, which is the limit.",
                    "open": self.open_results()}
        built = self.build_setup(
            system_ref, method_ref, allocation, amount, unit, flow_property,
            with_costs, with_regionalisation, nw_set, parameters,
            parameter_set)
        if "error" in built:
            return built
        system, method = built["system"], built["method"]
        result = (self.client.simulate(built["setup"]) if simulate
                  else self.client.calculate(built["setup"]))
        opened = OpenResult(uuid.uuid4().hex[:12], result, system, method,
                            built["plain"])
        try:
            state = result.wait_until_ready()
            err = getattr(state, "error", None)
            if err:
                raise RuntimeError(f"openLCA could not calculate "
                                   f"'{system.name}': {err}")
            impacts = result.get_total_impacts() if method else []
            demand = result.get_demand()
        except Exception as e:
            self._dispose(opened)
            return {"error": str(e)}
        self._results()[opened.handle] = opened
        out = {
            "handle": opened.handle,
            "system": system.name, "system_id": system.id,
            "method": method.name if method else "",
            "method_id": method.id if method else "",
            "setup": dict(opened.setup),
            "impacts": self._impacts_to_list(impacts),
        }
        if demand is not None and demand.tech_flow is not None:
            out["demand"] = dict(self._tf(demand.tech_flow),
                                 amount=demand.amount)
        return out

    def borrow_result(self, handle: Optional[str], system_ref: str,
                      method_ref: str, allocation: Optional[str] = None):
        """An open result for (system, method, allocation): the one with
        this handle if it is that calculation, otherwise a new one.

        Returns (OpenResult, borrowed, error). A result that was not
        borrowed must be closed by the caller with close_result().
        """
        if handle:
            r = self._results().get(handle)
            if r is not None:
                system = self._resolve_system(system_ref)
                method = self._resolve_method(method_ref)
                plain = OpenResult("", None, system, method, {
                    "allocation": (allocation or "as_defined").lower()}) \
                    if system and method else None
                if plain is not None and plain.key() == r.key():
                    return r, True, None
        made = self.open_result(system_ref, method_ref, allocation,
                                temporary=True)
        if "error" in made:
            return None, False, made
        return self._results()[made["handle"]], False, None

    # ── turning openLCA's objects into plain rows ────────────

    @staticmethod
    def _tf(tf) -> Dict:
        prov, flow = tf.provider, tf.flow
        return {"process": prov.name if prov else "",
                "process_id": prov.id if prov else "",
                "location": (getattr(prov, "location", "") or "") if prov else "",
                "product": flow.name if flow else "",
                "product_id": flow.id if flow else ""}

    @staticmethod
    def _ef(ef) -> Dict:
        flow = ef.flow
        loc = getattr(ef, "location", None)
        return {"flow": flow.name if flow else "",
                "flow_id": flow.id if flow else "",
                "compartment": (getattr(flow, "category", "") or "") if flow else "",
                "unit": (getattr(flow, "ref_unit", "") or "") if flow else "",
                "direction": "input" if ef.is_input else "output",
                "location": (loc.name or "") if loc is not None else ""}

    @staticmethod
    def _cat(ref) -> Dict:
        return {"category": ref.name, "category_id": ref.id,
                "unit": getattr(ref, "ref_unit", "") or ""}

    def _tech_flows_of(self, r: OpenResult) -> list:
        if r._tech_flows is None:
            r._tech_flows = list(r.result.get_tech_flows())
        return r._tech_flows

    def _envi_flows_of(self, r: OpenResult) -> list:
        if r._envi_flows is None:
            r._envi_flows = list(r.result.get_envi_flows())
        return r._envi_flows

    def _categories_of(self, r: OpenResult) -> list:
        if r._categories is None:
            r._categories = list(r.result.get_impact_categories())
        return r._categories

    # ── finding the thing a query names ──────────────────────

    def _find_category(self, r: OpenResult, name: str):
        cats = self._categories_of(r)
        if not cats:
            return None, {"error": "This result has no impact categories: "
                                   "it was calculated without a method.",
                          "hint": "CALCULATE \"system\" USING \"method\"."}
        exact = [c for c in cats if c.id == name or c.name == name]
        if not exact:
            low = name.lower()
            exact = [c for c in cats if c.name.lower() == low] or \
                    [c for c in cats if low in c.name.lower()]
        if len(exact) == 1:
            return exact[0], None
        listing = "\n".join(f"    {c.name}" for c in (exact or cats)[:40])
        if exact:
            return None, {"error": f"'{name}' matches {len(exact)} "
                                   f"categories of the result:\n{listing}",
                          "hint": "Give the full category name."}
        return None, {"error": f"The result has no category called "
                               f"'{name}'. It has:\n{listing}",
                      "hint": "RESULT CATEGORIES lists them."}

    def _find_tech_flow(self, r: OpenResult, name: str,
                        location: Optional[str] = None,
                        product: Optional[str] = None):
        flows = [tf for tf in self._tech_flows_of(r) if tf.provider]
        found = [tf for tf in flows if tf.provider.id == name]
        if not found:
            found = [tf for tf in flows if tf.provider.name == name]
        if not found:
            low = name.lower()
            found = [tf for tf in flows if low in tf.provider.name.lower()]
        if location:
            found = [tf for tf in found
                     if (getattr(tf.provider, "location", "") or "") == location]
        if product:
            found = [tf for tf in found if tf.flow
                     and (tf.flow.id == product or tf.flow.name == product)]
        if len(found) == 1:
            return found[0], None
        if not found:
            where = f" at LOCATION \"{location}\"" if location else ""
            return None, {"error": f"No process called '{name}'{where} is "
                                   f"in this result.",
                          "hint": "RESULT PROCESSES lists the processes of "
                                  "the calculated system."}
        rows = [f"    {tf.provider.name}  "
                f"[{getattr(tf.provider, 'location', '') or 'no location'}]  "
                f"{tf.provider.id}" for tf in found[:12]]
        more = len(found) - 12
        if more > 0:
            rows.append(f"    ... and {more} more")
        same_process = len({tf.provider.id for tf in found}) == 1
        hint = ("The process has several products: add PRODUCT \"flow "
                "name\"." if same_process else
                "Give the full name, add LOCATION \"code\", or use the "
                "UUID in place of the name.")
        return None, {"error": f"'{name}' matches {len(found)} processes "
                               f"of the result:\n" + "\n".join(rows),
                      "hint": hint}

    def _find_envi_flow(self, r: OpenResult, name: str,
                        compartment: Optional[str] = None):
        flows = [ef for ef in self._envi_flows_of(r) if ef.flow]
        found = [ef for ef in flows if ef.flow.id == name]
        if not found:
            found = [ef for ef in flows if ef.flow.name == name]
        if not found:
            low = name.lower()
            found = [ef for ef in flows if ef.flow.name.lower() == low]
        if compartment:
            low = compartment.lower()
            found = [ef for ef in found
                     if low in (getattr(ef.flow, "category", "") or "").lower()]
        if len(found) == 1:
            return found[0], None
        if not found:
            where = f" in \"{compartment}\"" if compartment else ""
            return None, {"error": f"No elementary flow called '{name}'"
                                   f"{where} is in this result's inventory.",
                          "hint": "RESULT FLOWS LIST shows the flows of "
                                  "the inventory."}
        rows = [f"    {ef.flow.name}  "
                f"[{getattr(ef.flow, 'category', '') or 'no compartment'}]  "
                f"{ef.flow.id}" for ef in found[:12]]
        return None, {"error": f"'{name}' matches {len(found)} elementary "
                               f"flows of the result:\n" + "\n".join(rows),
                      "hint": "Add IN \"compartment\" after the flow name "
                              "(part of the compartment path is enough), "
                              "or use the UUID."}

    # ── the queries ──────────────────────────────────────────

    def result_query(self, handle: str, query: str, **args) -> Dict:
        """
        Read one thing from an open result.

        query is one of QUERIES. The arguments each takes are listed
        there. Returns the tabular shape described in the module
        docstring, or {"error", "hint"}.
        """
        r = self._results().get(handle)
        if r is None:
            return {"error": "That result is not open any more.",
                    "hint": "CALCULATE again to make a new one."}
        fn = getattr(self, "_q_" + query, None)
        if fn is None:
            return {"error": f"Unknown result query: {query}"}
        try:
            out = fn(r, **{k: v for k, v in args.items() if v is not None})
        except _QueryError as e:
            return e.payload
        if "error" in out:
            return out
        out.setdefault("query", query)
        out["system"] = r.system.name
        out["method"] = r.method.name if r.method else ""
        return out

    # helpers that raise instead of returning errors

    def _category(self, r, name):
        cat, err = self._find_category(r, name)
        if err:
            raise _QueryError(err)
        return cat

    def _process(self, r, name, location=None, product=None):
        tf, err = self._find_tech_flow(r, name, location, product)
        if err:
            raise _QueryError(err)
        return tf

    def _flow(self, r, name, compartment=None):
        ef, err = self._find_envi_flow(r, name, compartment)
        if err:
            raise _QueryError(err)
        return ef

    def _need_method(self, r, what):
        if r.method is None:
            raise _QueryError({
                "error": f"{what} needs impact results, and this result "
                         f"was calculated without a method.",
                "hint": "CALCULATE \"system\" USING \"method\"."})

    def _need_costs(self, r):
        if not r.with_costs:
            raise _QueryError({
                "error": "This result was calculated without costs.",
                "hint": f"Calculate again with costs: CALCULATE "
                        f"\"{r.system.name}\" USING \"method\" WITH COSTS."})

    def _need_groups(self, r) -> List[str]:
        if r._groups is None:
            full = self.client.get(o.ProductSystem, r.system.id)
            r._groups = [g.name for g in
                         (getattr(full, "analysis_groups", None) or [])]
        if not r._groups:
            raise _QueryError({
                "error": f"'{r.system.name}' has no analysis groups, so "
                         f"there is nothing to group the result by.",
                "hint": "Add ANALYSIS GROUP \"name\" ... END ANALYSIS "
                        "GROUP blocks with EDIT SYSTEM, then calculate "
                        "again."})
        return r._groups

    def _tf_rows(self, values, key="amount") -> List[Dict]:
        return [dict(self._tf(v.tech_flow), **{key: v.amount})
                for v in values if v.tech_flow is not None]

    def _ef_rows(self, values, key="amount") -> List[Dict]:
        return [dict(self._ef(v.envi_flow), **{key: v.amount})
                for v in values if v.envi_flow is not None]

    @staticmethod
    def _share(rows: List[Dict], total: float, key="amount"):
        for row in rows:
            row["share_pct"] = (row[key] / total * 100.0) if total else 0.0
        return rows

    # impacts

    def _q_impacts(self, r, category=None):
        self._need_method(r, "RESULT IMPACTS")
        if category:
            cat = self._category(r, category)
            v = r.result.get_total_impact_value_of(cat)
            rows = [dict(self._cat(cat), amount=v.amount)]
        else:
            rows = [dict(self._cat(v.impact_category), amount=v.amount)
                    for v in r.result.get_total_impacts()]
        return {"title": "Impact totals", "keep_order": True,
                "columns": ["category", "amount", "unit"], "rows": rows}

    def _q_categories(self, r):
        self._need_method(r, "RESULT CATEGORIES")
        return {"title": "Impact categories of the result", "keep_order": True,
                "columns": ["category", "unit"],
                "rows": [self._cat(c) for c in self._categories_of(r)]}

    def _q_processes(self, r):
        return {"title": "Processes of the calculated system", "keep_order": True,
                "columns": ["process", "location", "product"],
                "rows": [self._tf(tf) for tf in self._tech_flows_of(r)]}

    def _q_demand(self, r):
        d = r.result.get_demand()
        rows = [] if d is None else [dict(self._tf(d.tech_flow),
                                          amount=d.amount)]
        return {"title": "Demand of the calculation", "keep_order": True,
                "columns": ["process", "product", "amount"], "rows": rows}

    def _nw(self, r, weighted: bool):
        self._need_method(r, "RESULT WEIGHTED" if weighted
                          else "RESULT NORMALISED")
        if not r.nw_set:
            word = "WEIGHTED" if weighted else "NORMALISED"
            raise _QueryError({
                "error": f"RESULT {word} needs a normalisation and "
                         f"weighting set, and this result was calculated "
                         f"without one.",
                "hint": f"Calculate again: CALCULATE \"{r.system.name}\" "
                        f"USING \"{r.method.name}\" NW SET \"name\". SHOW "
                        f"METHOD \"{r.method.name}\" lists the sets."})
        values = (r.result.get_weighted_impacts() if weighted
                  else r.result.get_normalized_impacts())
        rows = [{"category": v.impact_category.name,
                 "category_id": v.impact_category.id, "amount": v.amount}
                for v in values]
        return {"title": ("Weighted" if weighted else "Normalised")
                + f" results (NW set: {r.nw_set})",
                "nw_set": r.nw_set, "keep_order": True,
                "columns": ["category", "amount"], "rows": rows}

    def _q_normalised(self, r):
        return self._nw(r, False)

    def _q_weighted(self, r):
        return self._nw(r, True)

    # inventory

    def _q_flows(self, r, process=None, direct=False, flow=None,
                 compartment=None, location=None, product=None):
        cols = ["flow", "compartment", "direction", "amount", "unit"]
        if process is None:
            if direct:
                raise _QueryError({
                    "error": "DIRECT needs a process.",
                    "hint": "RESULT FLOWS OF PROCESS \"name\" DIRECT."})
            if flow:
                ef = self._flow(r, flow, compartment)
                v = r.result.get_total_flow_value_of(ef)
                rows = [dict(self._ef(ef), amount=v.amount)]
            else:
                rows = self._ef_rows(r.result.get_total_flows())
            return {"title": "Inventory (total elementary flows)",
                    "columns": cols, "rows": rows}
        tf = self._process(r, process, location, product)
        who = tf.provider.name
        if flow:
            ef = self._flow(r, flow, compartment)
            v = (r.result.get_direct_intervention_of(ef, tf) if direct
                 else r.result.get_total_intervention_of(ef, tf))
            rows = [dict(self._ef(ef), amount=v.amount)]
        else:
            rows = self._ef_rows(
                r.result.get_direct_interventions_of(tf) if direct
                else r.result.get_total_interventions_of(tf))
        kind = "its own exchanges" if direct else "itself and its supply chain"
        return {"title": f"Elementary flows of {who} ({kind})",
                "process": who, "columns": cols, "rows": rows}

    def _q_flows_list(self, r):
        return {"title": "Elementary flows of the inventory", "keep_order": True,
                "columns": ["flow", "compartment", "direction", "unit"],
                "rows": [self._ef(ef) for ef in self._envi_flows_of(r)]}

    def _q_flow_by_process(self, r, flow, compartment=None):
        ef = self._flow(r, flow, compartment)
        total = r.result.get_total_flow_value_of(ef).amount
        rows = self._share(
            self._tf_rows(r.result.get_flow_contributions_of(ef)), total)
        return {"title": f"Where {ef.flow.name} comes from (direct, by "
                         f"process)",
                "flow": ef.flow.name, "total": total,
                "unit": getattr(ef.flow, "ref_unit", "") or "",
                "columns": ["process", "location", "amount", "share_pct"],
                "rows": rows}

    # contributions

    def _q_contribution_process(self, r, direct=False, category=None,
                                process=None, location=None, product=None):
        self._need_method(r, "RESULT CONTRIBUTION")
        res = r.result
        kind = "direct" if direct else "with supply chain"
        if process is not None:
            tf = self._process(r, process, location, product)
            if category:
                cat = self._category(r, category)
                v = (res.get_direct_impact_of(cat, tf) if direct
                     else res.get_total_impact_of(cat, tf))
                values = [(cat, v.amount)]
            else:
                got = (res.get_direct_impacts_of(tf) if direct
                       else res.get_total_impacts_of(tf))
                values = [(v.impact_category, v.amount) for v in got]
            totals = {v.impact_category.id: v.amount
                      for v in res.get_total_impacts()}
            rows = []
            for cat, amount in values:
                total = totals.get(cat.id, 0.0)
                rows.append(dict(self._cat(cat), amount=amount,
                                 share_pct=(amount / total * 100.0)
                                 if total else 0.0))
            return {"title": f"Contribution of {tf.provider.name} ({kind})",
                    "process": tf.provider.name,
                    "columns": ["category", "amount", "unit", "share_pct"],
                    "rows": rows}
        cols = ["process", "location", "amount", "share_pct"]
        if category:
            cat = self._category(r, category)
            total = res.get_total_impact_value_of(cat).amount
            if direct:
                rows = self._tf_rows(res.get_impact_contributions_of(cat))
            else:
                rows = [dict(self._tf(tf),
                             amount=res.get_total_impact_of(cat, tf).amount)
                        for tf in self._tech_flows_of(r)]
            return {"title": f"Contribution by process to {cat.name} "
                             f"({kind})",
                    "category": cat.name, "total": total,
                    "unit": getattr(cat, "ref_unit", "") or "",
                    "columns": cols, "rows": self._share(rows, total)}
        totals = {v.impact_category.id: v.amount
                  for v in res.get_total_impacts()}
        rows = []
        for tf in self._tech_flows_of(r):
            got = (res.get_direct_impacts_of(tf) if direct
                   else res.get_total_impacts_of(tf))
            for v in got:
                total = totals.get(v.impact_category.id, 0.0)
                rows.append(dict(
                    self._tf(tf), category=v.impact_category.name,
                    amount=v.amount,
                    unit=getattr(v.impact_category, "ref_unit", "") or "",
                    share_pct=(v.amount / total * 100.0) if total else 0.0))
        return {"title": f"Contribution by process, every category ({kind})",
                "columns": ["category", "process", "location", "amount",
                            "unit", "share_pct"],
                "rank_within": "category", "rows": rows}

    def _q_contribution_flow(self, r, category=None, flow=None,
                             compartment=None):
        self._need_method(r, "RESULT CONTRIBUTION BY FLOW")
        res = r.result
        cols = ["flow", "compartment", "amount", "share_pct"]
        if flow and not category:
            raise _QueryError({
                "error": "One flow's contribution needs the category.",
                "hint": "RESULT CONTRIBUTION BY FLOW CATEGORY \"name\" "
                        "FLOW \"name\"."})
        if category:
            cat = self._category(r, category)
            total = res.get_total_impact_value_of(cat).amount
            if flow:
                ef = self._flow(r, flow, compartment)
                v = res.get_flow_impact_of(cat, ef)
                rows = [dict(self._ef(ef), amount=v.amount)]
            else:
                rows = self._ef_rows(res.get_flow_impacts_of(cat))
            return {"title": f"Contribution by elementary flow to {cat.name}",
                    "category": cat.name, "total": total,
                    "unit": getattr(cat, "ref_unit", "") or "",
                    "columns": cols, "rows": self._share(rows, total)}
        rows = []
        for v in res.get_total_impacts():
            cat = v.impact_category
            for row in self._ef_rows(res.get_flow_impacts_of(cat)):
                if not row["amount"]:
                    continue
                row["category"] = cat.name
                row["unit"] = getattr(cat, "ref_unit", "") or ""
                row["share_pct"] = ((row["amount"] / v.amount * 100.0)
                                    if v.amount else 0.0)
                rows.append(row)
        return {"title": "Contribution by elementary flow, every category",
                "columns": ["category", "flow", "compartment", "amount",
                            "unit", "share_pct"],
                "rank_within": "category", "rows": rows}

    def _q_factors(self, r, category, flow=None, compartment=None):
        self._need_method(r, "RESULT FACTORS")
        cat = self._category(r, category)
        if flow:
            ef = self._flow(r, flow, compartment)
            v = r.result.get_impact_factor_of(cat, ef)
            rows = [dict(self._ef(ef), factor=v.amount)]
        else:
            rows = self._ef_rows(r.result.get_impact_factors_of(cat),
                                 key="factor")
        unit = getattr(cat, "ref_unit", "") or ""
        for row in rows:
            row["factor_unit"] = (f"{unit} per {row['unit']}"
                                  if unit and row["unit"] else unit)
        return {"title": f"Characterisation factors of {cat.name} for the "
                         f"flows of the inventory",
                "category": cat.name, "sort_by": "factor",
                "columns": ["flow", "compartment", "factor", "factor_unit"],
                "rows": rows}

    # intensities, scaling, requirements

    def _impact_intensities(self, r, tf) -> list:
        """The client's get_impact_intensities_of sends a method name
        the server does not have, so this goes through rpc_call."""
        data, err = self.client.rpc_call(
            "result/impact-intensities-of",
            {"@id": r.result.uid, "techFlow": tf.to_dict()})
        if err:
            raise _QueryError({"error": f"openLCA could not give the "
                                        f"intensities: {err}"})
        return [o.ImpactValue.from_dict(d) for d in (data or [])]

    def _q_intensity(self, r, process, category=None, flows=False, flow=None,
                     compartment=None, location=None, product=None):
        tf = self._process(r, process, location, product)
        who = tf.provider.name
        per = f"per unit of {tf.flow.name if tf.flow else 'product'}"
        if flow or flows:
            cols = ["flow", "compartment", "direction", "amount", "unit"]
            if flow:
                ef = self._flow(r, flow, compartment)
                v = r.result.get_flow_intensity_of(ef, tf)
                rows = [dict(self._ef(ef), amount=v.amount)]
            else:
                rows = self._ef_rows(r.result.get_flow_intensities_of(tf))
            return {"title": f"Elementary flows of {who} {per}, with its "
                             f"supply chain",
                    "process": who, "columns": cols, "rows": rows}
        self._need_method(r, "RESULT INTENSITY")
        if category:
            cat = self._category(r, category)
            v = r.result.get_impact_intensity_of(cat, tf)
            rows = [dict(self._cat(cat), amount=v.amount)]
        else:
            rows = [dict(self._cat(v.impact_category), amount=v.amount)
                    for v in self._impact_intensities(r, tf)]
        return {"title": f"Impacts of {who} {per}, with its supply chain",
                "process": who,
                "columns": ["category", "amount", "unit"], "rows": rows}

    def _q_scaling(self, r, process=None, unscaled=False, location=None,
                   product=None):
        if process is None:
            if unscaled:
                raise _QueryError({
                    "error": "UNSCALED needs a process.",
                    "hint": "RESULT SCALING OF PROCESS \"name\" UNSCALED."})
            return {"title": "Scaling factors (how many times each process "
                             "runs)",
                    "columns": ["process", "location", "product", "amount"],
                    "rows": self._tf_rows(r.result.get_scaling_factors())}
        tf = self._process(r, process, location, product)
        values = (r.result.get_unscaled_tech_flows_of(tf) if unscaled
                  else r.result.get_scaled_tech_flows_of(tf))
        # openLCA answers with the whole column of the technology
        # matrix: an entry per process of the system, nearly all zero
        values = [v for v in values if v.amount]
        what = ("as written in the process" if unscaled
                else "scaled to this calculation")
        return {"title": f"Product and waste flows of {tf.provider.name} "
                         f"({what}; inputs are negative)",
                "process": tf.provider.name,
                "columns": ["process", "location", "product", "amount"],
                "rows": self._tf_rows(values)}

    def _q_totality(self, r, process=None, location=None, product=None):
        if process is None:
            data, err = self.client.rpc_call("result/totality-factors",
                                             {"@id": r.result.uid})
            if err:
                return {"error": f"openLCA could not give the totality "
                                 f"factors: {err}"}
            values = [o.TechFlowValue.from_dict(d) for d in (data or [])]
        else:
            tf = self._process(r, process, location, product)
            data, err = self.client.rpc_call(
                "result/totality-factor-of",
                {"@id": r.result.uid, "techFlow": tf.to_dict()})
            if err:
                return {"error": f"openLCA could not give the totality "
                                 f"factor: {err}"}
            values = [o.TechFlowValue.from_dict(data)]
        return {"title": "Totality factors (total requirement, corrected "
                         "for loops in the supply chain)",
                "columns": ["process", "location", "product", "amount"],
                "rows": self._tf_rows(values)}

    def _q_requirements(self, r, process=None, location=None, product=None):
        if process is None:
            values = r.result.get_total_requirements()
        else:
            tf = self._process(r, process, location, product)
            values = [r.result.get_total_requirements_of(tf)]
        return {"title": "Total requirements (amount of each product the "
                         "system needs)",
                "columns": ["process", "location", "product", "amount"],
                "rows": self._tf_rows(values)}

    # upstream trees

    def _q_tree(self, r, category=None, flow=None, costs=False,
                compartment=None, levels=3, top=5):
        res = r.result
        if costs:
            self._need_costs(r)
            getter = lambda path: res.get_upstream_costs_of(path)
            total = res.get_total_costs().amount
            subject, unit = "costs", self._currency_name(res)
        elif flow:
            ef = self._flow(r, flow, compartment)
            getter = lambda path: res.get_upstream_interventions_of(ef, path)
            total = res.get_total_flow_value_of(ef).amount
            subject = ef.flow.name
            unit = getattr(ef.flow, "ref_unit", "") or ""
        elif category:
            self._need_method(r, "RESULT TREE CATEGORY")
            cat = self._category(r, category)
            getter = lambda path: res.get_upstream_impacts_of(cat, path)
            total = res.get_total_impact_value_of(cat).amount
            subject, unit = cat.name, getattr(cat, "ref_unit", "") or ""
        else:
            raise _QueryError({
                "error": "RESULT TREE needs to know what to follow.",
                "hint": "RESULT TREE CATEGORY \"name\", RESULT TREE FLOW "
                        "\"name\" or RESULT TREE COSTS."})

        def share(v):
            return (v / total * 100.0) if total else 0.0

        def node_of(n, depth, path):
            tf = n.tech_flow
            node = dict(self._tf(tf), amount=n.result or 0.0,
                        direct=n.direct_contribution or 0.0,
                        required=n.required_amount,
                        share_pct=share(n.result or 0.0), children=[])
            if depth < levels and tf.provider is not None:
                kids = sorted(getter(path + [tf]),
                              key=lambda k: abs(k.result or 0), reverse=True)
                node["children"] = [node_of(k, depth + 1, path + [tf])
                                    for k in kids[:top]]
                rest = kids[top:]
                if rest:
                    other = sum(k.result or 0 for k in rest)
                    node["other"] = {"count": len(rest), "amount": other,
                                     "share_pct": share(other)}
            return node

        roots = getter([])
        if not roots:
            return {"error": "openLCA returned no upstream tree for this."}
        demand = res.get_demand().tech_flow

        def same(a, b):
            return (a and b and a.flow and b.flow and a.flow.id == b.flow.id
                    and (a.provider.id if a.provider else None)
                    == (b.provider.id if b.provider else None))

        if len(roots) == 1 and same(roots[0].tech_flow, demand):
            root = node_of(roots[0], 0, [])
        else:
            kids = sorted(roots, key=lambda k: abs(k.result or 0),
                          reverse=True)
            root = dict(self._tf(demand), amount=total, direct=None,
                        required=None, share_pct=100.0,
                        children=[node_of(k, 1, []) for k in kids[:top]]
                        if levels >= 1 else [])
            if kids[top:] and levels >= 1:
                other = sum(k.result or 0 for k in kids[top:])
                root["other"] = {"count": len(kids[top:]), "amount": other,
                                 "share_pct": share(other)}

        rows: List[Dict] = []

        def flatten(node, level):
            rows.append({"level": level, "process": node["process"],
                         "location": node["location"],
                         "amount": node["amount"], "direct": node["direct"],
                         "share_pct": node["share_pct"]})
            for child in node["children"]:
                flatten(child, level + 1)
            if node.get("other"):
                rows.append({"level": level + 1,
                             "process": f"({node['other']['count']} others)",
                             "location": "",
                             "amount": node["other"]["amount"],
                             "direct": None,
                             "share_pct": node["other"]["share_pct"]})

        flatten(root, 0)
        return {"title": f"Upstream tree of {subject}", "subject": subject,
                "unit": unit, "total": total, "levels": levels, "top": top,
                "root": root, "keep_order": True,
                "columns": ["level", "process", "location", "amount",
                            "direct", "share_pct"],
                "rows": rows}

    # costs

    @staticmethod
    def _currency_name(res) -> str:
        cur = getattr(res.get_total_costs(), "currency", None)
        return (cur.name or "") if cur is not None else ""

    def _q_costs(self, r, by=None, process=None, direct=False,
                 intensity=False, location=None, product=None):
        self._need_costs(r)
        res = r.result
        total = res.get_total_costs()
        currency = (total.currency.name or "") if total.currency else ""
        note = ("Costs are net: what a process pays for its inputs less "
                "what it earns from its products.")
        if by == "process":
            rows = self._share(self._tf_rows(res.get_cost_contributions()),
                               total.amount)
            return {"title": "Direct net costs by process",
                    "total": total.amount, "currency": currency,
                    "note": note,
                    "columns": ["process", "location", "amount", "share_pct"],
                    "rows": rows}
        if by == "group":
            self._need_groups(r)
            rows = [{"group": g.group, "amount": g.amount}
                    for g in res.get_grouped_cost_results()]
            return {"title": "Net costs by analysis group",
                    "total": total.amount, "currency": currency,
                    "note": note, "columns": ["group", "amount"],
                    "rows": rows}
        if by == "tag":
            return self._by_tag(r, "result/tag-results-of-costs", {},
                                "Net costs by process tag", currency)
        if process is not None:
            tf = self._process(r, process, location, product)
            if intensity:
                amount = self._cost_number(r, "result/cost-intensities-of", tf)
                what = (f"per unit of {tf.flow.name if tf.flow else 'product'}"
                        f", with its supply chain")
            elif direct:
                amount = self._cost_number(r, "result/direct-costs-of", tf)
                what = "its own exchanges"
            else:
                amount = self._cost_number(r, "result/total-costs-of", tf)
                what = "itself and its supply chain"
            return {"title": f"Net costs of {tf.provider.name} ({what})",
                    "currency": currency, "note": note,
                    "columns": ["process", "location", "amount"],
                    "rows": [dict(self._tf(tf), amount=amount)]}
        return {"title": "Total net costs", "currency": currency,
                "note": note, "columns": ["system", "amount", "currency"],
                "rows": [{"system": r.system.name, "amount": total.amount,
                          "currency": currency}]}

    def _cost_number(self, r, method: str, tf) -> float:
        """The server answers the per-process cost methods with a bare
        number, which the client's wrappers cannot read (they expect an
        object), so these go through rpc_call."""
        data, err = self.client.rpc_call(
            method, {"@id": r.result.uid, "techFlow": tf.to_dict()})
        if err:
            raise _QueryError({"error": f"openLCA could not give the "
                                        f"costs: {err}"})
        if isinstance(data, dict):
            return float(data.get("amount") or 0.0)
        return float(data or 0.0)

    # analysis groups and tags

    def _q_impacts_by_group(self, r, category=None):
        self._need_method(r, "RESULT IMPACTS BY GROUP")
        self._need_groups(r)
        cats = ([self._category(r, category)] if category
                else self._categories_of(r))
        rows = []
        for cat in cats:
            for g in r.result.get_grouped_impact_results_of(cat):
                rows.append(dict(self._cat(cat), group=g.group,
                                 amount=g.amount))
        return {"title": "Impacts by analysis group",
                "columns": ["category", "group", "amount", "unit"],
                "rank_within": "category", "rows": rows}

    def _q_flows_by_group(self, r, flow, compartment=None):
        self._need_groups(r)
        ef = self._flow(r, flow, compartment)
        rows = [{"group": g.group, "amount": g.amount,
                 "unit": getattr(ef.flow, "ref_unit", "") or ""}
                for g in r.result.get_grouped_flow_results_of(ef)]
        return {"title": f"{ef.flow.name} by analysis group",
                "flow": ef.flow.name,
                "columns": ["group", "amount", "unit"], "rows": rows}

    def _by_tag(self, r, method: str, params: Dict, title: str, unit: str):
        if not self.ipc_supports(method):
            return self._unsupported(method, "Results by process tag")
        data, err = self.client.rpc_call(
            method, dict({"@id": r.result.uid}, **params))
        if err:
            return {"error": f"openLCA could not give the results by tag: "
                             f"{err}"}
        rows = [{"tag": d.get("tag", ""), "amount": d.get("amount", 0.0),
                 "unit": unit} for d in (data or [])]
        return {"title": title, "columns": ["tag", "amount", "unit"],
                "rows": rows}

    def _q_impacts_by_tag(self, r, category):
        self._need_method(r, "RESULT IMPACTS BY TAG")
        cat = self._category(r, category)
        return self._by_tag(
            r, "result/tag-results-of-impact",
            {"impactCategory": {"@type": "ImpactCategory", "@id": cat.id}},
            f"{cat.name} by process tag (direct results)",
            getattr(cat, "ref_unit", "") or "")

    def _q_flows_by_tag(self, r, flow, compartment=None):
        ef = self._flow(r, flow, compartment)
        return self._by_tag(
            r, "result/tag-results-of-flow", {"enviFlow": ef.to_dict()},
            f"{ef.flow.name} by process tag (direct results)",
            getattr(ef.flow, "ref_unit", "") or "")

    # Sankey

    def _q_sankey(self, r, category=None, flow=None, compartment=None,
                  min_share=None, max_nodes=None):
        req = o.SankeyRequest()
        if category:
            self._need_method(r, "RESULT SANKEY CATEGORY")
            cat = self._category(r, category)
            req.impact_category = o.Ref(id=cat.id, name=cat.name,
                                        ref_type=o.RefType.ImpactCategory)
            subject, unit = cat.name, getattr(cat, "ref_unit", "") or ""
        elif flow:
            ef = self._flow(r, flow, compartment)
            req.envi_flow = ef
            subject = ef.flow.name
            unit = getattr(ef.flow, "ref_unit", "") or ""
        else:
            raise _QueryError({
                "error": "RESULT SANKEY needs a category or a flow.",
                "hint": "RESULT SANKEY CATEGORY \"name\" or RESULT SANKEY "
                        "FLOW \"name\". openLCA cannot draw one for costs."})
        if min_share is not None:
            req.min_share = float(min_share)
        if max_nodes is not None:
            req.max_nodes = int(max_nodes)
        graph = r.result.get_sankey_graph(req)
        nodes = [dict(self._tf(n.tech_flow), index=n.index,
                      direct=n.direct_result, amount=n.total_result)
                 for n in (graph.nodes or [])]
        edges = [{"from": e.provider_index, "to": e.node_index,
                  "share": e.upstream_share} for e in (graph.edges or [])]
        return {"title": f"Sankey data for {subject}", "subject": subject,
                "unit": unit, "root_index": graph.root_index,
                "nodes": nodes, "edges": edges,
                "columns": ["index", "process", "location", "amount",
                            "direct"],
                "rows": nodes}


class _QueryError(Exception):
    def __init__(self, payload: Dict):
        self.payload = payload
        super().__init__(payload.get("error", ""))


#: Every query result_query() answers, and its arguments.
QUERIES: Dict[str, Tuple[str, ...]] = {
    "impacts": ("category",),
    "categories": (),
    "processes": (),
    "demand": (),
    "normalised": (),
    "weighted": (),
    "flows": ("process", "direct", "flow", "compartment", "location",
              "product"),
    "flows_list": (),
    "flow_by_process": ("flow", "compartment"),
    "contribution_process": ("direct", "category", "process", "location",
                             "product"),
    "contribution_flow": ("category", "flow", "compartment"),
    "factors": ("category", "flow", "compartment"),
    "intensity": ("process", "category", "flows", "flow", "compartment",
                  "location", "product"),
    "scaling": ("process", "unscaled", "location", "product"),
    "totality": ("process", "location", "product"),
    "requirements": ("process", "location", "product"),
    "tree": ("category", "flow", "costs", "compartment", "levels", "top"),
    "costs": ("by", "process", "direct", "intensity", "location", "product"),
    "impacts_by_group": ("category",),
    "flows_by_group": ("flow", "compartment"),
    "impacts_by_tag": ("category",),
    "flows_by_tag": ("flow", "compartment"),
    "sankey": ("category", "flow", "compartment", "min_share", "max_nodes"),
}
