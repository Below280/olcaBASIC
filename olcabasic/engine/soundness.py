"""
Checks that a model is sound before it is calculated.

These back the rules that turned the last silent ways of building a
model wrongly into errors (olcaBASIC 0.4.0):

    systems_containing       which product systems hold a process, so
                             that they can be marked stale when it changes
    system_drift             does a product system still link what its
                             foreground processes ask for (survives a
                             RESET and a new session, and sees edits made
                             in the openLCA app)
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

#: The tag on a product system olcaBASIC built, saying how it was linked
#: (prefer_defaults, only_defaults, ignore_defaults, only_link_providers).
LINKING_TAG = "olcabasic:linking="


def _linkable(ex) -> bool:
    """Can openLCA link this exchange to a provider? Product inputs,
    waste outputs, and avoided products and wastes (which link the
    other way round)."""
    if getattr(ex, "is_quantitative_reference", False):
        return False
    flow = getattr(ex, "flow", None)
    ft = getattr(flow, "flow_type", None) if flow is not None else None
    is_input = bool(getattr(ex, "is_input", False))
    avoided = bool(getattr(ex, "is_avoided_product", False))
    if ft == o.FlowType.PRODUCT_FLOW:
        return is_input != avoided
    if ft == o.FlowType.WASTE_FLOW:
        return is_input == avoided
    return False


def _named_bridge(name: str, category: str = "") -> bool:
    """A bridge is named 'BRIDGE | ...' or sits in a Bridges folder
    (the same test as the interpreter's)."""
    segments = [seg.strip().lower() for seg in (category or "").split("/")]
    return ((name or "").upper().replace(" ", "").startswith("BRIDGE|")
            or "bridges" in segments)


class SoundnessMixin:

    # ── which processes a system holds ───────────────────────

    def _system_read(self, system_id: str):
        """(id of the reference process, ids of every process) of a
        product system. Read once per system and kept until
        clear_caches() or the system is built again (a rebuilt system
        has a new id)."""
        return self._system_info(system_id)[:2]

    def _system_info(self, system_id: str):
        """(reference process id, member ids, links, tags) of a product
        system, read once and kept like _system_read. links maps
        (process id, exchange internal id) to (provider id, flow id)."""
        cache = self.__dict__.setdefault("_members_cache", {})
        if system_id not in cache or len(cache[system_id]) < 4:
            system = self.client.get(o.ProductSystem, system_id)
            ids: Set[str] = set()
            ref = None
            links: Dict = {}
            tags: List[str] = []
            if system is not None:
                if system.ref_process is not None:
                    ref = system.ref_process.id
                    ids.add(ref)
                ids.update(r.id for r in system.processes or [])
                for link in system.process_links or []:
                    proc = getattr(link, "process", None)
                    exch = getattr(link, "exchange", None)
                    if proc is None or exch is None:
                        continue
                    prov = getattr(link, "provider", None)
                    flow = getattr(link, "flow", None)
                    links[(proc.id, exch.internal_id)] = (
                        prov.id if prov is not None else None,
                        flow.id if flow is not None else None)
                tags = list(system.tags or [])
            cache[system_id] = (ref, ids, links, tags)
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
        {"systems": [{"id", "name"}], "how"}. A server with data/get/usage
        answers directly (no released openLCA has it yet, 2.7.0
        included); otherwise every product system in the database is
        looked at (each is read once and remembered)."""
        try:
            # a server with data/get/usage can say where a process is used
            if self.ipc_supports("data/get/usage"):
                data, err = self.client.rpc_call(
                    "data/get/usage",
                    {"@type": "Process", "@id": process_id})
                if not err:
                    return {"process_id": process_id, "systems": [
                        {"id": d.get("@id"), "name": d.get("name", "")}
                        for d in data or []
                        if d.get("@type") == "ProductSystem"],
                        "how": "asked openLCA"}
            self._cache.pop("ProductSystem", None)
            found = []
            for d in self._get_descriptors(o.ProductSystem):
                if process_id in self._system_members(d.id):
                    found.append({"id": d.id, "name": d.name})
            return {"process_id": process_id, "systems": found,
                    "how": "read every product system"}
        except Exception as ex:
            return {"error": str(ex)}

    # ── does the system still match its foreground ───────────

    def system_drift(self, system_ref: str,
                     folders: Optional[List[str]] = None) -> Dict:
        """How a product system no longer matches its foreground
        processes: {"system_id", "system_name", "linking", "drift":
        [messages]}. An empty list means the system links what the
        processes ask for now.

        openLCA reads amounts, formulas and parameters from the
        processes when it calculates, so a changed amount never makes a
        system out of date. What does is structure the system froze when
        it was built: an input added, removed or given another provider.
        Only the foreground (the part the program built) is checked;
        background datasets are never edited. The system is read once a
        session; its processes are read every time."""
        try:
            desc = self.find_system(system_ref)
            if desc is None:
                return {"error": f"Product system '{system_ref}' not found"}
            _, _, links, tags = self._system_info(desc.id)
            linking = next((t[len(LINKING_TAG):] for t in tags
                            if t.startswith(LINKING_TAG)), "")
            drift: List[str] = []
            linked_by_process: Dict[str, Set[int]] = {}
            for (pid, iid) in links:
                linked_by_process.setdefault(pid, set()).add(iid)
            for d in self._foreground(desc, folders):
                proc = self.client.get(o.Process, d.id)
                if proc is None:
                    drift.append(f"'{d.name}' is in the system but no "
                                 f"longer in the database")
                    continue
                by_iid = {ex.internal_id: ex for ex in proc.exchanges or []}
                for ex in proc.exchanges or []:
                    if not _linkable(ex):
                        continue
                    flow = ex.flow.name if ex.flow is not None else "?"
                    got = links.get((proc.id, ex.internal_id))
                    default = getattr(ex, "default_provider", None)
                    if got is None:
                        if default is not None:
                            drift.append(
                                f"'{proc.name}' asks for '{flow}' from "
                                f"'{default.name}', and the system has no "
                                f"link for it")
                        elif linking in ("prefer_defaults",
                                         "ignore_defaults",
                                         "only_link_providers") \
                                and ex.flow is not None \
                                and self.client.get_providers(ex.flow):
                            drift.append(
                                f"'{proc.name}' has an input '{flow}' that "
                                f"the system does not link")
                        continue
                    provider_id, flow_id = got
                    if ex.flow is not None and flow_id \
                            and flow_id != ex.flow.id:
                        drift.append(
                            f"the system links exchange {ex.internal_id} of "
                            f"'{proc.name}' as another flow than '{flow}'")
                    elif default is not None and provider_id \
                            and provider_id != default.id \
                            and linking in ("prefer_defaults",
                                            "only_defaults"):
                        drift.append(
                            f"'{proc.name}' now takes '{flow}' from "
                            f"'{default.name}', and the system still "
                            f"links another provider")
                for iid in sorted(linked_by_process.get(proc.id, ())):
                    if iid not in by_iid:
                        drift.append(
                            f"the system links an input of '{proc.name}' "
                            f"that the process no longer has")
            return {"system_id": desc.id, "system_name": desc.name,
                    "linking": linking, "drift": drift}
        except Exception as ex:
            return {"error": str(ex)}

    def system_unbridged(self, system_ref: str,
                         folders: Optional[List[str]] = None) -> Dict:
        """Links in a product system that take a background process
        straight into a foreground process, with no bridge between:
        {"system_id", "system_name", "unbridged": [messages]}.

        olcaBASIC refuses such an input when it builds a process, but a
        system can also be made or relinked in the openLCA app or from
        Python. This reads the system as it is in the database, so the
        rule holds however the system was made. A bridge is a process
        named 'BRIDGE | ...' or in a Bridges folder; the foreground is
        the folder of the reference process and the program's build
        folders."""
        try:
            desc = self.find_system(system_ref)
            if desc is None:
                return {"error": f"Product system '{system_ref}' not found"}
            _, _, links, _ = self._system_info(desc.id)
            fg = {d.id: d for d in self._foreground(desc, folders)}
            names = {d.id: d for d in self._get_descriptors(o.Process)}
            out: List[str] = []
            for (pid, _iid), (provider_id, _flow) in links.items():
                user = fg.get(pid)
                if user is None or provider_id is None \
                        or provider_id in fg:
                    continue
                if _named_bridge(user.name, getattr(user, "category", "")):
                    continue
                prov = names.get(provider_id)
                if prov is None:
                    msg = (f"'{user.name}' links to a process that no "
                           f"longer exists ({provider_id})")
                    if msg not in out:
                        out.append(msg)
                    continue
                pname = prov.name
                if _named_bridge(
                        prov.name, getattr(prov, "category", "")):
                    continue
                msg = (f"'{user.name}' takes '{pname}' from the "
                       f"background with no bridge")
                if msg not in out:
                    out.append(msg)
            return {"system_id": desc.id, "system_name": desc.name,
                    "unbridged": sorted(out)}
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
        from ..background import is_background_folder
        tops = {t for t in tops if not is_background_folder(t)}
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

    def foreground_flow_ids(self, system_ref: str,
                            folders: Optional[List[str]] = None) -> Dict:
        """The flows the foreground processes of a system exchange:
        {"flows": [ids]}. The foreground is read afresh (a few
        processes)."""
        try:
            desc = self.find_system(system_ref)
            if desc is None:
                return {"error": f"Product system '{system_ref}' not found"}
            ids = set()
            for d in self._foreground(desc, folders):
                proc = self.client.get(o.Process, d.id)
                for ex in (proc.exchanges or []) if proc else []:
                    if ex.flow:
                        ids.add(ex.flow.id)
            return {"flows": sorted(ids)}
        except Exception as ex:
            return {"error": str(ex)}

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
