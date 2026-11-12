"""
Checks that a model is sound before it is calculated.

These back the rules that turned the last silent ways of building a
model wrongly into errors (olcaBASIC 0.4.0):

    systems_containing       which product systems hold a process, so
                             that they can be marked stale when it changes
    uncharacterised_flows    elementary flows a method has no factor for
    foreground_uncertainty   is there any uncertainty in the foreground
    allocation_gaps          multi-output processes with no factors for
                             the allocation method asked for

"Foreground" is the part of a system the program built: the processes
of the system that sit in the program's build folders, or in the top
folder of the system's reference process.

Nothing here writes to the database.
"""

from typing import Dict, List, Optional, Set

import olca_schema as o

from .fields import ALLOCATION_NAMES, ALLOCATION_WORDS


#: The tag on entities olcaBASIC created that its rules look for later
#: (impact methods and categories carry it too).
OWN_TAG = "olcaBASIC"


class SoundnessMixin:

    # ── which processes a system holds ───────────────────────

    def _system_read(self, system_id: str):
        """(id of the reference process, ids of every process) of a
        product system. Read once per system and kept until
        clear_caches() or the system is built again (a rebuilt system
        has a new id)."""
        cache = self.__dict__.setdefault("_members_cache", {})
        if system_id not in cache:
            system = self.client.get(o.ProductSystem, system_id)
            ids: Set[str] = set()
            ref = None
            if system is not None:
                if system.ref_process is not None:
                    ref = system.ref_process.id
                    ids.add(ref)
                ids.update(r.id for r in system.processes or [])
            cache[system_id] = (ref, ids)
        return cache[system_id]

    def _system_members(self, system_id: str) -> Set[str]:
        return self._system_read(system_id)[1]

    def forget_system_members(self, system_id: Optional[str] = None):
        """Drop what is remembered about the processes of a system (of
        every system when no id is given)."""
        cache = self.__dict__.setdefault("_members_cache", {})
        if system_id is None:
            cache.clear()
        else:
            cache.pop(system_id, None)

    def systems_containing(self, process_id: str) -> Dict:
        """The product systems that contain a process:
        {"systems": [{"id", "name"}]}. Every product system in the
        database is looked at (each is read once and remembered)."""
        try:
            self._cache.pop("ProductSystem", None)
            found = []
            for d in self._get_descriptors(o.ProductSystem):
                if process_id in self._system_members(d.id):
                    found.append({"id": d.id, "name": d.name})
            return {"process_id": process_id, "systems": found}
        except Exception as ex:
            return {"error": str(ex)}

    # ── the foreground of a system ───────────────────────────

    def _foreground(self, system, folders: Optional[List[str]] = None):
        """Descriptors of the system's foreground processes."""
        ref, members = self._system_read(system.id)
        by_id = {d.id: d for d in self._get_descriptors(o.Process)}
        tops = {f.strip("/").split("/")[0].lower()
                for f in folders or [] if f and f.strip("/")}
        if ref in by_id:
            tops.add((getattr(by_id[ref], "category", "") or "")
                     .strip("/").split("/")[0].lower())
        out = []
        for pid in members:
            d = by_id.get(pid)
            if d is None:
                continue
            top = (getattr(d, "category", "") or "").strip("/") \
                .split("/")[0].lower()
            if top in tops:
                out.append(d)
        return sorted(out, key=lambda d: d.name or "")

    @staticmethod
    def _has_uncertainty(u) -> bool:
        return u is not None and getattr(u, "distribution_type", None) \
            is not None

    def foreground_uncertainty(self, system_ref: str,
                               folders: Optional[List[str]] = None) -> Dict:
        """
        Is there an uncertainty distribution anywhere in the foreground
        of a system: on an exchange or a parameter of a foreground
        process, or on a global parameter?

        Returns {"has_uncertainty": bool, "where": "..." (the first one
        found), "processes": n (foreground processes looked at)}.
        """
        try:
            system = self._resolve_system(system_ref)
            if not system:
                return {"error": f"Product system not found: {system_ref}"}
            foreground = self._foreground(system, folders)
            for d in foreground:
                process = self.client.get(o.Process, d.id)
                if process is None:
                    continue
                for ex in process.exchanges or []:
                    if self._has_uncertainty(ex.uncertainty):
                        flow = ex.flow.name if ex.flow else "an exchange"
                        return {"has_uncertainty": True,
                                "where": f"'{flow}' in '{process.name}'",
                                "processes": len(foreground)}
                for p in process.parameters or []:
                    if self._has_uncertainty(p.uncertainty):
                        return {"has_uncertainty": True,
                                "where": f"parameter {p.name} of "
                                         f"'{process.name}'",
                                "processes": len(foreground)}
            for d in self._get_descriptors(o.Parameter):
                param = self.client.get(o.Parameter, d.id)
                if param is None or not self._is_global(param):
                    continue
                if self._has_uncertainty(param.uncertainty):
                    return {"has_uncertainty": True,
                            "where": f"global parameter {param.name}",
                            "processes": len(foreground)}
            return {"has_uncertainty": False, "where": "",
                    "processes": len(foreground)}
        except Exception as ex:
            return {"error": str(ex)}

    def allocation_gaps(self, system_ref: str, allocation: Optional[str],
                        folders: Optional[List[str]] = None) -> Dict:
        """
        Foreground processes with more than one product and no
        allocation factors for the method the calculation will use.

        allocation is PHYSICAL or ECONOMIC, or None / AS_DEFINED for
        "as set in each process" (then each process is checked against
        its own default method, when that is physical or economic).

        Returns {"gaps": [{"process", "products": [names], "method"}]}.
        """
        try:
            system = self._resolve_system(system_ref)
            if not system:
                return {"error": f"Product system not found: {system_ref}"}
            asked = self._resolve_allocation(allocation)
            checked = (o.AllocationType.PHYSICAL_ALLOCATION,
                       o.AllocationType.ECONOMIC_ALLOCATION)
            if asked not in checked + (
                    o.AllocationType.USE_DEFAULT_ALLOCATION,):
                return {"gaps": []}
            gaps = []
            for d in self._foreground(system, folders):
                process = self.client.get(o.Process, d.id)
                if process is None:
                    continue
                method = asked
                if asked == o.AllocationType.USE_DEFAULT_ALLOCATION:
                    method = process.default_allocation_method
                if method not in checked:
                    continue
                products = [v["flow_name"]
                            for v in self._exchange_views(process)
                            if self._is_product_view(v)]
                if len(products) < 2:
                    continue
                if any(f.allocation_type == method
                       for f in process.allocation_factors or []):
                    continue
                gaps.append({"process": process.name, "products": products,
                             "method": ALLOCATION_NAMES.get(method, "?")})
            return {"gaps": gaps}
        except ValueError as ex:
            return {"error": str(ex)}
        except Exception as ex:
            return {"error": str(ex)}

    # ── characterisation factors ─────────────────────────────

    def _characterised_flows(self, method_id: str) -> Set[str]:
        """Ids of every flow that has a factor in any category of a
        method. Read once per method (one read per category) and kept
        until clear_caches()."""
        cache = self.__dict__.setdefault("_characterised_cache", {})
        if method_id not in cache:
            method = self.client.get(o.ImpactMethod, method_id)
            flows: Set[str] = set()
            for ref in (method.impact_categories or []) if method else []:
                cat = self.client.get(o.ImpactCategory, ref.id)
                for f in (cat.impact_factors or []) if cat else []:
                    if f.flow is not None:
                        flows.add(f.flow.id)
            cache[method_id] = flows
        return cache[method_id]

    def flow_is_own(self, flow_id: str) -> bool:
        """True for a flow olcaBASIC created (it carries the tag
        'olcaBASIC')."""
        try:
            flow = self.client.get(o.Flow, flow_id)
        except Exception:
            return False
        return flow is not None and OWN_TAG in (flow.tags or [])

    def forget_characterised_flows(self):
        self.__dict__.setdefault("_characterised_cache", {}).clear()

    def uncharacterised_flows(self, method_ref: str,
                              flow_ids: List[str]) -> Dict:
        """
        Which of these flows have no characterisation factor in any
        category of a method: {"method", "flows": [{"id", "name"}]}.
        Such a flow adds nothing to any result of that method.
        """
        try:
            method = self._resolve_method(method_ref)
            if not method:
                return {"error": f"Impact method not found: {method_ref}"}
            have = self._characterised_flows(method.id)
            missing = []
            for fid in flow_ids:
                if fid in have:
                    continue
                missing.append({"id": fid,
                                "name": self.flow_info(fid).get("name", fid)})
            return {"method": method.name, "flows": missing}
        except Exception as ex:
            return {"error": str(ex)}
