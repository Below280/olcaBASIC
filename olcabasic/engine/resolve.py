"""
Name resolution for the engine.

Turning what a user typed (a name, part of a name, a UUID, a folder
path) into exactly one openLCA entity, or into an error that says why
not. This logic lived in olcaBASIC's bridge.py up to v0.3.0; it sits in
the engine so that every route into openLCA resolves names the same way.

ResolveMixin is mixed into Engine. It uses self.client,
self.get_descriptors(), self.find_process() and self.create_flow().
"""

from typing import Dict, Optional

import olca_schema as o


def _plural(word: str) -> str:
    """process -> processes, flow -> flows, currency -> currencies."""
    if word.endswith(("s", "x", "ch", "sh")):
        return word + "es"
    if word.endswith("y") and word[-2:-1] not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


class ResolveMixin:
    """Resolution methods of the Engine."""

    def resolve_process(self, name_or_id: str) -> Optional[str]:
        """UUID of the process with this UUID, exact name or unique
        partial name. None if there is no single match."""
        proc = self.find_process(name_or_id)
        return proc.id if proc else None

    def process_candidates(self, name: str, location: str = "") -> list:
        """Every process called exactly this (optionally at one location
        code), as [{"id", "name", "location", "category"}], sorted by
        location. Used to list the choices when a name is ambiguous."""
        loc = location.strip().lower()
        out = []
        for p in self.get_descriptors(o.Process):
            if p.name != name:
                continue
            p_loc = getattr(p, "location", "") or ""
            if loc and p_loc.lower() != loc:
                continue
            out.append({"id": p.id, "name": p.name, "location": p_loc,
                        "category": getattr(p, "category", "") or ""})
        return sorted(out, key=lambda c: (c["location"], c["id"]))

    def processes_in_folder(self, path: str, deep: bool = True) -> list:
        """Every process in a folder (and, with deep, in the folders
        below it), as [{"id", "name", "location", "category"}] sorted
        by category then name. From descriptors: no full reads."""
        base = (path or "").strip("/").lower()
        out = []
        for p in self.get_descriptors(o.Process):
            cat = (getattr(p, "category", "") or "").strip("/")
            low = cat.lower()
            if low == base or (deep and low.startswith(base + "/")):
                out.append({"id": p.id, "name": p.name,
                            "location": getattr(p, "location", "") or "",
                            "category": cat})
        return sorted(out, key=lambda c: (c["category"], c["name"]))

    def describe_process(self, process_id: str) -> Optional[Dict]:
        """{"id", "name", "location", "category"} of a process, from its
        descriptor (no full read). None if there is no such process."""
        for p in self.get_descriptors(o.Process):
            if p.id == process_id:
                return {"id": p.id, "name": p.name,
                        "location": getattr(p, "location", "") or "",
                        "category": getattr(p, "category", "") or ""}
        return None

    def find_method_strict(self, ref: str) -> Dict:
        """An impact method by UUID or by its full name.

        Returns {"id", "name"}, or {"error", "candidates"} when nothing
        has exactly that name. Candidates are the methods whose names
        contain the text or are close to it, so 'EF 3.1' offers
        'EF v3.1' and 'EF v3.1 no LT'."""
        import difflib
        methods = self.get_descriptors(o.ImpactMethod)
        for m in methods:
            if m.id == ref:
                return {"id": m.id, "name": m.name}
        exact = [m for m in methods if m.name == ref]
        if len(exact) == 1:
            return {"id": exact[0].id, "name": exact[0].name}
        if len(exact) > 1:
            return {"error": f"{len(exact)} impact methods are called "
                             f"'{ref}'. Use the UUID of the one you mean.",
                    "candidates": [f"{m.name} ({m.id})" for m in exact]}
        names = sorted({m.name for m in methods})
        lower = ref.lower()
        squeezed = "".join(ch for ch in lower if ch.isalnum())
        near = [n for n in names if lower in n.lower()
                or squeezed in "".join(ch for ch in n.lower() if ch.isalnum())]
        for n in difflib.get_close_matches(ref, names, n=5, cutoff=0.6):
            if n not in near:
                near.append(n)
        return {"error": f"No impact method is called '{ref}'.",
                "candidates": near[:10]}

    def get_process_details_by_ref(self, ref: str) -> Dict:
        """get_process_details for a name or a UUID."""
        proc = self.find_process(ref)
        return self.get_process_details(proc.id if proc else ref)

    def get_data_quality_by_ref(self, ref: str) -> Dict:
        """get_data_quality for a name or a UUID."""
        proc = self.find_process(ref)
        return self.get_data_quality(proc.id if proc else ref)

    @staticmethod
    def _flow_result(f, ambiguous: int = 0) -> Dict:
        r = {"flow_id": f.id, "flow_name": f.name,
             "category": getattr(f, "category", "") or "",
             "already_existed": True}
        if ambiguous:
            r["ambiguous"] = ambiguous
        return r

    @classmethod
    def _match_flow_name(cls, name: str, flows: list,
                         roots=()) -> Optional[Dict]:
        """Exact name match, else unique substring match, else None.
        Several exact matches: prefer an 'unspecified' sub-compartment
        (ecoinvent-style default), then the compartment root itself
        (FLCAC-style, e.g. 'emission/air'), then the shortest path."""
        exact = [f for f in flows if f.name == name]
        if len(exact) == 1:
            return cls._flow_result(exact[0])
        if len(exact) > 1:
            cat = lambda f: (getattr(f, "category", "") or "").lower().rstrip("/")
            root_set = {r.lower().rstrip("/") for r in roots}
            unspec = [f for f in exact if cat(f).endswith("unspecified")]
            at_root = [f for f in exact if cat(f) in root_set]
            if unspec:
                best = unspec[0]
            elif at_root:
                best = at_root[0]
            else:
                best = min(exact, key=lambda f: len(cat(f)))
            return cls._flow_result(best, ambiguous=len(exact))
        lower = name.lower()
        partial = [f for f in flows if lower in f.name.lower()]
        if len(partial) == 1:
            return cls._flow_result(partial[0])
        return None

    @staticmethod
    def _under_folder(f, folder: str) -> bool:
        base = (folder or "").strip("/").lower()
        c = (getattr(f, "category", "") or "").strip("/").lower()
        return c == base or c.startswith(base + "/")

    def flow_candidates(self, name: str, folder: str = "") -> list:
        """Every flow called exactly this (optionally only in one folder
        and the folders below it), as [{"id", "name", "category",
        "flow_type"}] sorted by category. Used to list the choices when
        a flow name is ambiguous."""
        out = []
        for f in self.get_descriptors(o.Flow):
            if f.name != name:
                continue
            if folder and not self._under_folder(f, folder):
                continue
            ft = getattr(f, "flow_type", None)
            out.append({"id": f.id, "name": f.name,
                        "category": getattr(f, "category", "") or "",
                        "flow_type": getattr(ft, "value", ft) or ""})
        return sorted(out, key=lambda c: (c["category"], c["id"]))

    def flow_by_id(self, uid: str) -> Optional[Dict]:
        """The flow with this UUID, as a find_flow result, or None."""
        for f in self.get_descriptors(o.Flow):
            if f.id == uid:
                return self._flow_result(f)
        return None

    def find_flow_in_folder(self, name: str, folder: str) -> Dict:
        """USE FLOW "name" FOLDER "path": only flows in that folder (and
        below) count. Returns a find_flow result; {"ambiguous": n} with
        no flow_id when several flows there share the exact name; or
        {"error": ...} when nothing there matches."""
        in_folder = [f for f in self.get_descriptors(o.Flow)
                     if self._under_folder(f, folder)]
        exact = [f for f in in_folder if f.name == name]
        if len(exact) == 1:
            return self._flow_result(exact[0])
        if len(exact) > 1:
            return {"ambiguous": len(exact)}
        lower = name.lower()
        partial = [f for f in in_folder if lower in f.name.lower()]
        if len(partial) == 1:
            return self._flow_result(partial[0])
        if partial:
            return {"error": (f"'{name}' is part of {len(partial)} flow "
                              f"names in '{folder}'; give the full name")}
        return {"error": f"No flow called '{name}' in '{folder}'"}

    def find_flow(self, name: str, unit: str = "",
                  category="", strict: bool = False) -> Optional[Dict]:
        """Find an existing flow by name. Returns dict with flow_id or None.

        category is a case-insensitive prefix.
        strict=True (elementary flows): only flows under that prefix
        are considered; there is no fallback to the whole database.
        strict=False (product flows): flows under the prefix are
        preferred, then the whole database is searched.
        """
        flows = self.get_descriptors(o.Flow)

        if category:
            prefixes = [category] if isinstance(category, str) else list(category)
            prefixes = [p.lower().rstrip("/") for p in prefixes]

            def under(f):
                c = (getattr(f, "category", "") or "").lower()
                return any(c == p or c.startswith(p + "/")
                           for p in prefixes)

            in_cat = [f for f in flows if under(f)]
            if strict:
                return self._match_flow_name(name, in_cat, prefixes)
            hit = self._match_flow_name(name, in_cat, prefixes)
            if hit:
                return hit

        return self._match_flow_name(name, flows)

    def resolve_process_strict(self, ref: str) -> Dict:
        """Resolve a PROVIDER reference to exactly one process.
        Accepts a UUID or a name that matches one process only."""
        procs = self.get_descriptors(o.Process)
        by_id = [p for p in procs if p.id == ref]
        if by_id:
            return {"process_id": by_id[0].id}
        exact = [p for p in procs if p.name == ref]
        if len(exact) == 1:
            return {"process_id": exact[0].id}
        if len(exact) > 1:
            locs = sorted({getattr(p, "location", "") or "?" for p in exact})
            return {"error": (
                f"'{ref}' matches {len(exact)} processes "
                f"(locations: {', '.join(locs)}). Give the UUID of the "
                f"one you mean (FIND PROCESS shows them)."),
                "ambiguous": len(exact)}
        partial = [p for p in procs if ref.lower() in p.name.lower()]
        if len(partial) == 1:
            return {"process_id": partial[0].id}
        if partial:
            return {"error": f"'{ref}' matches {len(partial)} "
                             f"processes by partial name; be more specific"}
        return {"error": f"Process not found: '{ref}'"}

    def find_process_qref_flow(self, process_name: str,
                                location: str = "") -> Optional[Dict]:
        """Find a process by name and return its quantitative reference
        flow ID and the process ID (for use as default provider).

        Returns None if no process matches, a dict with "error" if
        LOCATION rules something out, otherwise the match (with
        "ambiguous" set if several processes were equally good).
        """
        processes = self.get_descriptors(o.Process)
        exact = [p for p in processes if p.name == process_name]

        if not exact:
            # Partial match (only returns if unique)
            proc_desc = self.find_process(process_name)
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

        proc = self.client.get(o.Process, proc_desc.id)
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

    def get_flow_details(self, flow_id: str) -> Dict:
        """A flow with its properties, factors and reference units."""
        flow = self.client.get(o.Flow, flow_id)
        if flow is None:
            return {"error": f"Flow not found: {flow_id}"}
        props = []
        for f in flow.flow_properties or []:
            unit = ""
            if f.flow_property:
                fp = self.client.get(o.FlowProperty, f.flow_property.id)
                if fp and fp.unit_group:
                    ug = self.client.get(o.UnitGroup, fp.unit_group.id)
                    for u in (ug.units if ug else []) or []:
                        if u.is_ref_unit or (u.conversion_factor == 1.0 and not unit):
                            unit = u.name
            props.append({"name": f.flow_property.name if f.flow_property else "?",
                          "factor": f.conversion_factor,
                          "reference": bool(f.is_ref_flow_property),
                          "unit": unit})
        ftype = str(getattr(flow, "flow_type", "") or "")
        return {"name": flow.name, "category": getattr(flow, "category", "") or "",
                "type": ftype.split(".")[-1].replace("_FLOW", "").lower(),
                "description": getattr(flow, "description", "") or "",
                "properties": props}

    def get_process_object(self, process_id: str):
        """The full openLCA process (exchanges with flow and provider
        references), for EDIT to match exchanges by name."""
        return self.client.get(o.Process, process_id)

    def resolve_entity_strict(self, entity_type: str, ref: str) -> Dict:
        """Resolve a process, flow or product_system name (or UUID)
        to exactly one ID."""
        otype = {"process": o.Process, "flow": o.Flow,
                 "product_system": o.ProductSystem}.get(entity_type)
        if otype is None:
            return {"error": f"Unknown entity type: {entity_type}"}
        items = self.get_descriptors(otype)
        by_id = [d for d in items if d.id == ref]
        if by_id:
            return {"id": by_id[0].id, "name": by_id[0].name}
        exact = [d for d in items if d.name == ref]
        if len(exact) == 1:
            return {"id": exact[0].id, "name": exact[0].name}
        label = entity_type.replace("_", " ")
        if len(exact) > 1:
            cats = sorted({getattr(d, "category", "") or "(root)"
                           for d in exact})
            return {"error": (
                f"{len(exact)} {_plural(label)} are called '{ref}' (in: "
                f"{'; '.join(cats[:5])}). Nothing was deleted. "
                f"Delete by UUID instead.")}
        return {"not_found": True}

    def folder_exists(self, path: str, entity_type: str = "") -> bool:
        """True if any entity of this type (any type if empty) sits in
        this folder or below it (whole path segments)."""
        info = self.list_category_contents(path, entity_type)
        return (info.get("subfolder_count", 0) > 0
                or info.get("entity_count", 0) > 0)

    def resolve_flow_id(self, name: str, unit: str = "",
                         category: str = "",
                         flow_type: str = "product") -> Optional[str]:
        """Find or create a flow by name and return its ID."""
        result = self.create_flow(name, unit, category, flow_type)
        if "error" in result:
            return None
        return result.get("flow_id")

    def list_category_contents(self, path: str = "",
                                entity_type: str = "") -> Dict:
        """List processes, flows, or systems in a category folder.
        Returns immediate children (subfolders and entities)."""
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
            for desc in self.get_descriptors(otype):
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
