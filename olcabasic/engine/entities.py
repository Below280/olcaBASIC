"""
Every root entity type of openLCA: finding, showing (also as JSON-LD),
moving, deleting and making actors, sources, currencies, locations,
unit groups, flow properties, social indicators, data quality systems,
impact methods, projects and stored results.

openLCA's database has 17 entity types that its IPC server can read and
write. Flow maps are the eighteenth type in the data format, but they
are not stored as database entities and the server has no way to reach
them; the engine says so instead of pretending.

Part of olcabasic.engine.Engine (see engine.py).
"""

import json
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

import olca_schema as o
from olca_ipc import Client

from .fields import (_Refused, make_uncertainty, parse_date,
                     uncertainty_dict)
from .validators import validate_category as _validate_category

#: The tag olcaBASIC puts on impact methods and categories it makes, so
#: that it can tell its own from a licensed method pack's.
OWN_TAG = "olcaBASIC"

#: Type word of the language -> (olca_schema class, name in messages).
ENTITY_TYPES: Dict[str, Tuple[Any, str]] = {
    "PROCESS": (o.Process, "process"),
    "SYSTEM": (o.ProductSystem, "product system"),
    "FLOW": (o.Flow, "flow"),
    "PROPERTY": (o.FlowProperty, "flow property"),
    "UNITS": (o.UnitGroup, "unit group"),
    "PARAMETER": (o.Parameter, "global parameter"),
    "METHOD": (o.ImpactMethod, "impact method"),
    "CATEGORY": (o.ImpactCategory, "impact category"),
    "LOCATION": (o.Location, "location"),
    "DQ SYSTEM": (o.DQSystem, "data quality system"),
    "ACTOR": (o.Actor, "actor"),
    "SOURCE": (o.Source, "source"),
    "CURRENCY": (o.Currency, "currency"),
    "SOCIAL INDICATOR": (o.SocialIndicator, "social indicator"),
    "PROJECT": (o.Project, "project"),
    "RESULT": (o.Result, "stored result"),
    "EPD": (o.Epd, "EPD"),
    "FLOW MAP": (None, "flow map"),
}

FLOW_MAP_REFUSAL = (
    "openLCA's IPC server cannot reach flow maps: they are not stored as "
    "entities of the database, and the server has no method for them. "
    "Flow maps are made and used in openLCA's import dialogues.")

# Which types can point at an entity of each type. Checked before a
# delete, so that nothing is left pointing at something that is gone.
_USERS: Dict[str, Tuple[Any, ...]] = {
    "ACTOR": (o.Process, o.Epd),
    "SOURCE": (o.Process, o.ImpactMethod, o.ImpactCategory, o.DQSystem,
               o.Epd),
    "CURRENCY": (o.Process, o.Currency),
    "LOCATION": (o.Process, o.Flow, o.ImpactCategory, o.Epd),
    "DQ SYSTEM": (o.Process,),
    "SOCIAL INDICATOR": (o.Process,),
    "UNITS": (o.FlowProperty,),
    "PROPERTY": (o.Flow, o.UnitGroup, o.SocialIndicator, o.ProductSystem),
    "PARAMETER": (o.Process, o.ImpactCategory, o.Parameter,
                  o.ProductSystem, o.Project),
    "METHOD": (o.Project, o.Result),
    "CATEGORY": (o.ImpactMethod, o.Result),
    "RESULT": (o.Epd,),
    "PROJECT": (),
    "EPD": (),
}

_FORMULA_KEYS = ("formula", "amountFormula", "costFormula")


class EntitiesMixin:
    """The generic verbs and the MAKE blocks for every entity type."""

    # ── types and names ──────────────────────────────────────

    @staticmethod
    def entity_label(word: str) -> str:
        return ENTITY_TYPES[word][1]

    def _entity_class(self, word: str):
        if word not in ENTITY_TYPES:
            raise _Refused(f"'{word}' is not a type of entity.")
        cls = ENTITY_TYPES[word][0]
        if cls is None:
            raise _Refused(FLOW_MAP_REFUSAL)
        return cls

    @staticmethod
    def _folder(d) -> str:
        return getattr(d, "category", "") or ""

    def _descriptor_row(self, word: str, d) -> Dict:
        row = {"id": d.id, "name": d.name, "folder": self._folder(d)}
        if word == "PROCESS":
            row["location"] = getattr(d, "location", "") or ""
        elif word == "FLOW":
            row["unit"] = getattr(d, "ref_unit", "") or ""
        elif word == "CATEGORY":
            row["unit"] = getattr(d, "ref_unit", "") or ""
        return row

    def find_entities(self, word: str, term: str = "",
                      folder: Optional[str] = None,
                      limit: int = 200) -> Dict:
        """Entities of one type whose name contains term (every one
        when term is empty), optionally in a folder or below it."""
        try:
            cls = self._entity_class(word)
        except _Refused as e:
            return {"error": e.message}
        low = (term or "").lower()
        rows = []
        for d in self._get_descriptors(cls):
            if low and low not in (d.name or "").lower() and low != d.id:
                continue
            if folder:
                f = self._folder(d).lower()
                want = folder.lower().rstrip("/")
                if not (f == want or f.startswith(want + "/")):
                    continue
            rows.append(self._descriptor_row(word, d))
        rows.sort(key=lambda r: (r["name"] or "").lower())
        return {"type": word, "label": ENTITY_TYPES[word][1], "term": term,
                "total": len(rows), "count": min(len(rows), limit),
                "entities": rows[:limit]}

    def resolve_one(self, word: str, ref: str) -> Dict:
        """Exactly one entity by UUID or exact name: {"id", "name",
        "folder"}, {"not_found": True}, or {"error"} when several share
        the name."""
        try:
            cls = self._entity_class(word)
        except _Refused as e:
            return {"error": e.message}
        items = self._get_descriptors(cls)
        found = [d for d in items if d.id == ref]
        if not found:
            found = [d for d in items if d.name == ref]
        label = ENTITY_TYPES[word][1]
        if len(found) == 1:
            d = found[0]
            return {"id": d.id, "name": d.name, "folder": self._folder(d)}
        if not found:
            return {"not_found": True,
                    "error": f"No {label} is called '{ref}'.",
                    "hint": f"FIND {word} \"{ref}\" searches by part of a "
                            f"name."}
        listing = "\n".join(
            f"    {self._folder(d) or '(no folder)':<40} "
            f"{getattr(d, 'location', '') or '':<10} {d.id}"
            for d in found[:12])
        return {"error": f"'{ref}' matches {len(found)} {label}s:\n{listing}",
                "hint": "Use the UUID in place of the name."}

    def _get_one(self, word: str, ref: str):
        """(entity, None) or (None, error dict)."""
        found = self.resolve_one(word, ref)
        if "id" not in found:
            return None, found
        entity = self.client.get(self._entity_class(word), found["id"])
        if entity is None:
            return None, {"error": f"Could not read the "
                                   f"{ENTITY_TYPES[word][1]} '{ref}'."}
        return entity, None

    # ── showing ──────────────────────────────────────────────

    def entity_json(self, word: str, ref: str) -> Dict:
        """An entity as openLCA's JSON-LD (read only)."""
        entity, err = self._get_one(word, ref)
        if err:
            return err
        return {"type": word, "id": entity.id, "name": entity.name,
                "json": entity.to_dict()}

    def show_entity(self, word: str, ref: str) -> Dict:
        """An entity's fields in plain values: {"type", "id", "name",
        "folder", "fields": [[label, value], ...], "lists": {title:
        [row, ...]}}."""
        entity, err = self._get_one(word, ref)
        if err:
            return err
        fields: List[List] = []
        lists: Dict[str, List] = {}

        def add(label, value):
            if value not in (None, "", []):
                fields.append([label, value])

        def ref_name(r):
            return (r.name or r.id) if r is not None else None

        e = entity
        add("Description", getattr(e, "description", None))
        if word == "ACTOR":
            for label, key in (("Address", "address"), ("City", "city"),
                               ("Postcode", "zip_code"),
                               ("Country", "country"), ("Email", "email"),
                               ("Phone", "telephone"), ("Fax", "telefax"),
                               ("Website", "website")):
                add(label, getattr(e, key))
        elif word == "SOURCE":
            add("Reference", e.text_reference)
            add("URL", e.url)
            add("Year", e.year)
            add("Attached file", e.external_file)
        elif word == "CURRENCY":
            add("Code", e.code)
            add("Conversion factor", e.conversion_factor)
            add("Reference currency", ref_name(e.ref_currency))
        elif word == "LOCATION":
            add("Code", e.code)
            add("Latitude", e.latitude)
            add("Longitude", e.longitude)
            if e.geometry:
                add("Geometry", f"GeoJSON, type "
                                f"{e.geometry.get('type', '?')}")
        elif word == "UNITS":
            add("Default flow property", ref_name(e.default_flow_property))
            lists["Units"] = [
                {"unit": u.name, "factor": u.conversion_factor,
                 "reference": bool(u.is_ref_unit),
                 "synonyms": ", ".join(u.synonyms or [])}
                for u in e.units or []]
        elif word == "PROPERTY":
            add("Unit group", ref_name(e.unit_group))
            add("Type", "ECONOMIC" if e.flow_property_type
                == o.FlowPropertyType.ECONOMIC_QUANTITY else "PHYSICAL")
        elif word == "SOCIAL INDICATOR":
            add("Activity variable", e.activity_variable)
            add("Activity quantity", ref_name(e.activity_quantity))
            add("Activity unit", ref_name(e.activity_unit))
            add("Unit of measurement", e.unit_of_measurement)
            add("Evaluation scheme", e.evaluation_scheme)
        elif word == "DQ SYSTEM":
            add("Source", ref_name(e.source))
            add("Has uncertainties", "YES" if e.has_uncertainties else "NO")
            rows = []
            for ind in sorted(e.indicators or [],
                              key=lambda i: i.position or 0):
                for sc in sorted(ind.scores or [],
                                 key=lambda s: s.position or 0):
                    rows.append({"indicator": ind.name, "score": sc.position,
                                 "label": sc.label or "",
                                 "description": sc.description or "",
                                 "uncertainty": sc.uncertainty})
            lists["Indicators and scores"] = rows
        elif word == "PARAMETER":
            add("Value", e.value)
            add("Formula", e.formula)
            add("Uncertainty", (uncertainty_dict(e.uncertainty) or {})
                .get("text"))
        elif word == "METHOD":
            add("Code", e.code)
            add("Source", ref_name(e.source))
            add("Made by olcaBASIC",
                "YES" if OWN_TAG in (e.tags or []) else "NO")
            lists["Impact categories"] = [
                {"category": c.name, "unit": getattr(c, "ref_unit", "") or ""}
                for c in e.impact_categories or []]
            lists["NW sets"] = [
                {"nw_set": s.name, "factors": len(s.factors or []),
                 "weighted_unit": s.weighted_score_unit or ""}
                for s in e.nw_sets or []]
        elif word == "CATEGORY":
            add("Reference unit", e.ref_unit)
            add("Code", e.code)
            add("Direction", e.direction.name if e.direction else None)
            add("Factors", len(e.impact_factors or []))
            lists["Parameters"] = [
                {"name": p.name, "value": p.value, "formula": p.formula or ""}
                for p in e.parameters or []]
            lists["Factors (first 50)"] = [
                {"flow": f.flow.name if f.flow else "",
                 "compartment": (getattr(f.flow, "category", "") or "")
                 if f.flow else "",
                 "value": f.value, "formula": f.formula or "",
                 "unit": f.unit.name if f.unit else "",
                 "location": f.location.name if f.location else ""}
                for f in (e.impact_factors or [])[:50]]
        elif word == "PROJECT":
            add("Method", ref_name(e.impact_method))
            add("NW set", ref_name(e.nw_set))
            add("With costs", "YES" if e.is_with_costs else None)
            add("With regionalisation",
                "YES" if e.is_with_regionalization else None)
            lists["Variants"] = [
                {"variant": v.name, "system": ref_name(v.product_system),
                 "amount": v.amount, "unit": ref_name(v.unit) or "",
                 "allocation": (v.allocation_method.name
                                if v.allocation_method else ""),
                 "disabled": bool(v.is_disabled),
                 "parameters": ", ".join(
                     f"{r.name} = {r.value:g}"
                     for r in v.parameter_redefs or [])}
                for v in e.variants or []]
        elif word == "RESULT":
            add("Product system", ref_name(e.product_system))
            add("Method", ref_name(e.impact_method))
            lists["Impact results"] = [
                {"category": r.indicator.name if r.indicator else "",
                 "amount": r.amount,
                 "unit": (getattr(r.indicator, "ref_unit", "") or "")
                 if r.indicator else ""}
                for r in e.impact_results or []]
            add("Flow results", len(e.flow_results or []))
        elif word == "EPD":
            add("URN", e.urn)
            add("Registration", e.registration_id)
            add("Type", e.epd_type.name if e.epd_type else None)
            if e.product is not None:
                add("Product", ref_name(e.product.flow))
                add("Declared amount",
                    f"{e.product.amount:g} "
                    f"{ref_name(e.product.unit) or ''}".strip()
                    if e.product.amount is not None else None)
            add("Manufacturer", ref_name(e.manufacturer))
            add("Verifier", ref_name(e.verifier))
            add("Programme operator", ref_name(e.program_operator))
            add("PCR", ref_name(e.pcr))
            add("Data generator", ref_name(e.data_generator))
            add("Location", ref_name(e.location))
            add("Valid from", str(e.valid_from)[:10] if e.valid_from else None)
            add("Valid until",
                str(e.valid_until)[:10] if e.valid_until else None)
            add("Manufacturing", e.manufacturing)
            add("Product usage", e.product_usage)
            add("Use advice", e.use_advice)
            lists["Modules"] = [
                {"module": m.name, "result": ref_name(m.result),
                 "multiplier": m.multiplier} for m in e.modules or []]
        tags = getattr(e, "tags", None) or []
        add("Tags", ", ".join(tags))
        return {"type": word, "label": ENTITY_TYPES[word][1], "id": e.id,
                "name": e.name, "folder": getattr(e, "category", "") or "",
                "fields": fields, "lists": lists}

    # ── where is it used ─────────────────────────────────────

    def _usage_from_server(self, cls, entity_id: str):
        """Users of an entity from data/get/usage (openLCA 2.7), or None
        when the server has no such method."""
        if not self.ipc_supports("data/get/usage"):
            return None
        data, err = self.client.rpc_call(
            "data/get/usage", {"@type": cls.__name__, "@id": entity_id})
        if err:
            raise RuntimeError(f"openLCA could not say where it is used: "
                               f"{err}")
        out = []
        for d in data or []:
            kind = d.get("@type", "")
            out.append(f"{d.get('name', d.get('@id', '?'))} ({kind})")
        return out

    def entity_usage(self, word: str, entity_id: str, name: str = "",
                     max_hits: int = 10, progress=None,
                     workers: int = 8) -> Dict:
        """
        Where an entity is used: {"in_use", "users": [...], "complete",
        "how"}. With openLCA 2.7 the server answers directly. Before
        that, every entity that could point at it is read; for types
        that processes point at (actors, sources, currencies, locations,
        data quality systems, social indicators, global parameters) that
        means every process, which is slow on a large database, but
        nothing is reported unused that was not checked.
        """
        try:
            cls = self._entity_class(word)
            if word in ("PROCESS", "SYSTEM", "FLOW"):
                users = self._usage_from_server(cls, entity_id)
                if users is None:
                    return {"error": "This openLCA cannot say where a "
                                     f"{ENTITY_TYPES[word][1]} is used."}
                return {"in_use": bool(users), "users": users[:max_hits],
                        "complete": True, "how": "asked openLCA"}
            users = self._usage_from_server(cls, entity_id)
            if users is not None:
                return {"in_use": bool(users), "users": users[:max_hits],
                        "complete": True, "how": "asked openLCA"}

            by_name = word == "PARAMETER"
            pattern = (re.compile(
                rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")
                if by_name else None)

            def points_at(entity) -> bool:
                if getattr(entity, "id", None) == entity_id:
                    return False
                data = entity.to_dict()
                if not by_name:
                    return entity_id in json.dumps(data)
                return _formula_mentions(data, pattern, name)

            found: List[str] = []
            checked = 0
            for user_cls in _USERS.get(word, ()):
                label = user_cls.__name__
                if user_cls is o.Process:
                    descs = list(self.client.get_descriptors(o.Process))
                    url = getattr(self.client, "url", None)
                    import threading
                    local = threading.local()

                    def worker_client():
                        if url is None:
                            return self.client
                        if not hasattr(local, "c"):
                            local.c = Client(url)
                        return local.c

                    def uses(d):
                        proc = worker_client().get(o.Process, d.id)
                        if proc is None:
                            raise RuntimeError(
                                f"could not read process '{d.name}' "
                                f"({d.id}), so the search is incomplete")
                        return points_at(proc)

                    batch = max(workers * 25, 50)
                    n = workers if url is not None else 1
                    with ThreadPoolExecutor(max_workers=n) as pool:
                        for i in range(0, len(descs), batch):
                            chunk = descs[i:i + batch]
                            for d, hit in zip(chunk, pool.map(uses, chunk)):
                                if hit:
                                    found.append(f"{d.name} ({label})")
                            checked += len(chunk)
                            if progress:
                                progress(checked, len(descs))
                            if len(found) >= max_hits:
                                break
                else:
                    for entity in self.client.get_all(user_cls):
                        checked += 1
                        if points_at(entity):
                            found.append(f"{entity.name} ({label})")
                if len(found) >= max_hits:
                    break
            return {"in_use": bool(found), "users": found[:max_hits],
                    "complete": len(found) < max_hits,
                    "how": f"read {checked} entities"}
        except _Refused as e:
            return {"error": e.message}
        except Exception as ex:
            return {"error": str(ex)}

    # ── deleting and moving ──────────────────────────────────

    def delete_any(self, word: str, ref: str,
                   confirm_foreign: bool = False) -> Dict:
        """
        Delete an entity of any type but process, flow and product
        system (delete_entity handles those). Refused while anything
        still points at it. An impact method or category olcaBASIC did
        not make is refused unless confirm_foreign is True.
        """
        try:
            entity, err = self._get_one(word, ref)
            if err:
                return err
            label = ENTITY_TYPES[word][1]
            if word in ("METHOD", "CATEGORY") and not confirm_foreign \
                    and OWN_TAG not in (entity.tags or []):
                return {"error": f"'{entity.name}' was not made by "
                                 f"olcaBASIC.", "foreign": True,
                        "factors": self._factor_count(word, entity)}
            usage = self.entity_usage(word, entity.id, entity.name,
                                      max_hits=5)
            if "error" in usage:
                return usage
            if usage["in_use"]:
                more = "" if usage["complete"] else " (and possibly others)"
                return {"error": f"The {label} '{entity.name}' is still "
                                 f"used by {', '.join(usage['users'])}"
                                 f"{more}.",
                        "hint": "Take it out of those first; deleting it "
                                "now would leave them pointing at nothing.",
                        "in_use": True}
            deleted_categories = 0
            if word == "METHOD":
                # the categories go with the method when nothing else
                # uses them
                others = set()
                for m in self.client.get_all(o.ImpactMethod):
                    if m.id != entity.id:
                        others.update(c.id for c in m.impact_categories or [])
                self.client.delete(entity)
                for c in entity.impact_categories or []:
                    if c.id in others:
                        continue
                    cat = self.client.get(o.ImpactCategory, c.id)
                    if cat is not None:
                        self.client.delete(cat)
                        deleted_categories += 1
                self._cache.pop("ImpactCategory", None)
            else:
                self.client.delete(entity)
            self._cache.pop(type(entity).__name__, None)
            out = {"deleted": True, "type": word, "id": entity.id,
                   "name": entity.name}
            if deleted_categories:
                out["categories_deleted"] = deleted_categories
            return out
        except _Refused as e:
            return {"error": e.message}
        except Exception as ex:
            return {"error": str(ex)}

    def delete_probe(self, word: str, ref: str) -> Dict:
        """{"own", "factors"} for a method or category: whether
        olcaBASIC made it, and how many factors go with it."""
        try:
            entity, err = self._get_one(word, ref)
            if err:
                return err
            return {"own": OWN_TAG in (entity.tags or []),
                    "name": entity.name,
                    "factors": self._factor_count(word, entity)}
        except Exception as ex:
            return {"error": str(ex)}

    def _factor_count(self, word: str, entity) -> int:
        if word == "CATEGORY":
            return len(entity.impact_factors or [])
        n = 0
        for c in entity.impact_categories or []:
            cat = self.client.get(o.ImpactCategory, c.id)
            n += len(cat.impact_factors or []) if cat else 0
        return n

    def move_any(self, word: str, ref: str, folder: str) -> Dict:
        """Move an entity of any type to a folder."""
        err = _validate_category(folder)
        if err:
            return {"error": err}
        try:
            entity, failed = self._get_one(word, ref)
            if failed:
                return failed
            before = getattr(entity, "category", "") or ""
            entity.category = folder
            self.client.put(entity)
            self._cache.pop(type(entity).__name__, None)
            return {"moved": True, "type": word, "id": entity.id,
                    "name": entity.name, "from": before, "to": folder}
        except _Refused as e:
            return {"error": e.message}
        except Exception as ex:
            return {"error": str(ex)}

    # ── making the simple types ──────────────────────────────

    def _existing(self, cls, name: str, folder: Optional[str]):
        for d in self._get_descriptors(cls):
            if d.name == name and (not folder
                                   or folder == (self._folder(d))):
                return d
        return None

    def make_entity(self, word: str, name: str, folder: Optional[str],
                    fields: Dict[str, Any],
                    items: Optional[List[Dict]] = None,
                    editing: bool = False) -> Dict:
        """
        Make (or with editing=True change) an actor, source, currency,
        location, unit group, flow property, social indicator or data
        quality system.

        fields: the scalar fields by their olca_schema names, plus a few
        names that are looked up: "reference" (currency), "units" (unit
        group of a property), "source", "activity_quantity",
        "activity_unit", "geometry_file", "attach". items: the units of
        a unit group, or the indicators of a data quality system.
        A field may carry "where" keys as {"__where__": {field: line}}.

        Making something that exists (same name, and the same folder if
        one is given) changes nothing and returns already_existed.
        """
        where = fields.pop("__where__", {}) if fields else {}
        try:
            if not name or not name.strip():
                return {"error": "The name cannot be empty."}
            if folder:
                err = _validate_category(folder)
                if err:
                    return {"error": err}
            cls = self._entity_class(word)
            label = ENTITY_TYPES[word][1]
            if editing:
                entity, failed = self._get_one(word, name)
                if failed:
                    return failed
            else:
                d = self._existing(cls, name, folder)
                if d is not None:
                    return {"id": d.id, "name": d.name,
                            "folder": self._folder(d),
                            "already_existed": True, "type": word}
                entity = cls(id=str(uuid.uuid4()), name=name)
                if folder:
                    entity.category = folder
            try:
                attach = self._fill_entity(word, entity, dict(fields),
                                           items, editing)
            except _Refused as e:
                return {"error": e.message, "hint": e.hint,
                        "where": where.get(e.where, e.where)}
            self.client.put(entity)
            self._cache.pop(cls.__name__, None)
            if word in ("UNITS", "PROPERTY"):
                self._unit_cache_built = False
            out = {"id": entity.id, "name": entity.name,
                   "folder": getattr(entity, "category", "") or "",
                   "type": word, "label": label,
                   "edited" if editing else "created": True}
            if attach:
                done = self.attach_source_file(entity.id, attach)
                if "error" in done:
                    out["attach_error"] = done["error"]
                    out["attach_hint"] = done.get("hint", "")
                else:
                    out["attached"] = done["file"]
            return out
        except _Refused as e:
            return {"error": e.message, "hint": e.hint}
        except Exception as ex:
            return {"error": str(ex)}

    def _fill_entity(self, word: str, e, f: Dict, items, editing: bool):
        """Set the fields of one of the simple types. Returns the path
        of a file to attach (sources), or None."""
        def take(key, attr=None, kind=str):
            if key in f:
                value = f.pop(key)
                setattr(e, attr or key,
                        None if value is None else kind(value))

        take("description")
        attach = None
        if word == "ACTOR":
            for key in ("address", "city", "country", "email", "telephone",
                        "telefax", "website", "zip_code"):
                take(key)
        elif word == "SOURCE":
            take("text_reference")
            take("url")
            if "year" in f:
                year = f.pop("year")
                if year is not None and not 0 < float(year) < 10000:
                    raise _Refused(f"'{year}' is not a year.", "year")
                e.year = None if year is None else int(year)
            attach = f.pop("attach", None)
            if attach is not None and not os.path.isfile(attach):
                raise _Refused(f"File not found: {attach}.", "attach",
                               hint="The path is relative to the folder "
                                    "the program runs in.")
        elif word == "CURRENCY":
            take("code")
            if not editing and not e.code:
                raise _Refused("A currency needs a code.", "code",
                               hint="Add CODE \"EUR\" (or the code of the "
                                    "currency) to the block.")
            if "conversion_factor" in f:
                factor = float(f.pop("conversion_factor"))
                if factor <= 0:
                    raise _Refused(
                        f"The conversion factor must be above 0 (got "
                        f"{factor:g}).", "conversion_factor")
                e.conversion_factor = factor
            ref_name = f.pop("reference", None)
            existing_refs = self._reference_currencies(exclude=e.id)
            if ref_name is not None:
                d = self._field("reference", self._one_by_name, o.Currency,
                                str(ref_name), "currency", "")
                e.ref_currency = o.Ref(id=d.id, name=d.name,
                                       ref_type=o.RefType.Currency)
            elif not editing:
                if existing_refs:
                    if len(existing_refs) > 1:
                        raise _Refused(
                            "The database has several reference "
                            "currencies.", "reference",
                            hint="Say which this one converts to: "
                                 "REFERENCE \"name\".")
                    ref = existing_refs[0]
                    e.ref_currency = o.Ref(id=ref.id, name=ref.name,
                                           ref_type=o.RefType.Currency)
                else:
                    # the first currency is its own reference
                    e.ref_currency = o.Ref(id=e.id, name=e.name,
                                           ref_type=o.RefType.Currency)
                    if e.conversion_factor not in (None, 1.0):
                        raise _Refused(
                            "This is the first currency in the database, "
                            "so it is the reference currency and its "
                            "factor is 1.", "conversion_factor")
                    e.conversion_factor = 1.0
            if e.conversion_factor is None:
                raise _Refused(
                    "A currency needs a conversion factor to the "
                    "reference currency.", "conversion_factor",
                    hint="Add FACTOR n: one unit of this currency is n "
                         "units of the reference currency.")
        elif word == "LOCATION":
            take("code")
            if not editing and not e.code:
                raise _Refused("A location needs a code.", "code",
                               hint="Add CODE \"XX\" to the block.")
            for key, lo, hi in (("latitude", -90, 90),
                                ("longitude", -180, 180)):
                if key in f:
                    value = f.pop(key)
                    if value is not None and not lo <= float(value) <= hi:
                        raise _Refused(
                            f"{key.capitalize()} lies between {lo} and "
                            f"{hi} (got {float(value):g}).", key)
                    setattr(e, key, None if value is None else float(value))
            path = f.pop("geometry_file", None)
            if path is not None:
                if not os.path.isfile(path):
                    raise _Refused(f"File not found: {path}.",
                                   "geometry_file")
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        geo = json.load(fh)
                except ValueError as ex:
                    raise _Refused(f"'{path}' is not a JSON file: {ex}.",
                                   "geometry_file")
                if geo.get("type") == "FeatureCollection":
                    feats = geo.get("features") or []
                    if len(feats) != 1:
                        raise _Refused(
                            f"'{path}' holds {len(feats)} features; a "
                            f"location takes one geometry.",
                            "geometry_file")
                    geo = feats[0]
                if geo.get("type") == "Feature":
                    geo = geo.get("geometry") or {}
                if geo.get("type") not in (
                        "Point", "MultiPoint", "LineString",
                        "MultiLineString", "Polygon", "MultiPolygon",
                        "GeometryCollection"):
                    raise _Refused(
                        f"'{path}' does not hold a GeoJSON geometry.",
                        "geometry_file")
                e.geometry = geo
        elif word == "UNITS":
            if items is not None:
                # an exchange names its unit alone, so a unit name can
                # belong to one unit group only
                taken = {}
                for g in self.client.get_all(o.UnitGroup):
                    if g.id != e.id:
                        for u in g.units or []:
                            taken[u.name] = g.name
                for i in items:
                    if str(i["name"]) in taken:
                        raise _Refused(
                            f"The unit '{i['name']}' exists already, in "
                            f"the unit group '{taken[str(i['name'])]}'.",
                            i.get("where"),
                            hint="A unit name belongs to one unit group "
                                 "only: an exchange names its unit alone. "
                                 "Choose another name for the new unit.")
                e.units = self._units(items, e)
            elif not editing:
                raise _Refused("A unit group needs units.", None,
                               hint="Add UNIT \"name\", factor lines; mark "
                                    "one REFERENCE.")
        elif word == "PROPERTY":
            group = f.pop("units", None)
            if group is not None:
                d = self._field("units", self._one_by_name, o.UnitGroup,
                                str(group), "unit group",
                                "Make one with MAKE UNITS.")
                e.unit_group = o.Ref(id=d.id, name=d.name,
                                     ref_type=o.RefType.UnitGroup)
            elif not editing:
                raise _Refused("A flow property needs a unit group.",
                               "units",
                               hint="Add UNITS \"unit group name\" to the "
                                    "block.")
            if "type" in f:
                kind = str(f.pop("type")).upper()
                if kind not in ("PHYSICAL", "ECONOMIC"):
                    raise _Refused(f"TYPE {kind} is not a kind of flow "
                                   f"property.", "type",
                                   hint="Use TYPE PHYSICAL or TYPE "
                                        "ECONOMIC.")
                e.flow_property_type = (
                    o.FlowPropertyType.ECONOMIC_QUANTITY
                    if kind == "ECONOMIC"
                    else o.FlowPropertyType.PHYSICAL_QUANTITY)
            elif not editing:
                e.flow_property_type = o.FlowPropertyType.PHYSICAL_QUANTITY
        elif word == "SOCIAL INDICATOR":
            take("activity_variable")
            take("unit_of_measurement")
            take("evaluation_scheme")
            quantity = f.pop("activity_quantity", None)
            if quantity is not None:
                d = self._field("activity_quantity", self._one_by_name,
                                o.FlowProperty, str(quantity),
                                "flow property", "")
                e.activity_quantity = o.Ref(
                    id=d.id, name=d.name, ref_type=o.RefType.FlowProperty)
            unit = f.pop("activity_unit", None)
            if unit is not None:
                ref = self._get_unit_ref(str(unit))
                if ref is None:
                    raise _Refused(
                        f"Unit '{unit}' is not in this database.",
                        "activity_unit",
                        hint=f"FIND UNIT \"{unit}\" shows the units there "
                             f"are.")
                e.activity_unit = ref
                # openLCA keeps the unit only with its quantity, so a
                # unit given alone brings the flow property it belongs to.
                if e.activity_quantity is None:
                    fp = self._get_fp_ref(str(unit))
                    if fp is None:
                        raise _Refused(
                            f"The flow property of unit '{unit}' is not "
                            f"known, and openLCA keeps an activity unit "
                            f"only with its quantity.", "activity_unit",
                            hint="Add ACTIVITY QUANTITY \"flow property\".")
                    e.activity_quantity = o.Ref(
                        id=fp.id, name=fp.name,
                        ref_type=o.RefType.FlowProperty)
        elif word == "DQ SYSTEM":
            source = f.pop("source", None)
            if source is not None:
                e.source = self._field("source", self._source, str(source))
            if "has_uncertainties" in f:
                e.has_uncertainties = bool(f.pop("has_uncertainties"))
            if items is not None:
                e.indicators = self._dq_indicators(items)
            elif not editing:
                raise _Refused(
                    "A data quality system needs indicators.", None,
                    hint="Add INDICATOR \"name\" lines, each followed by "
                         "its SCORE lines.")
        else:
            raise _Refused(f"MAKE {word} is not a block of this kind.")
        if f:
            raise _Refused(f"A {ENTITY_TYPES[word][1]} has no field "
                           f"'{sorted(f)[0]}'.", sorted(f)[0])
        return attach

    @staticmethod
    def _field(key: str, fn, *args):
        """Call a look-up; a refusal is pinned to the field it was for."""
        try:
            return fn(*args)
        except _Refused as e:
            raise _Refused(e.message, e.where or key, e.hint)

    def _reference_currencies(self, exclude: str = "") -> list:
        out = []
        for cur in self.client.get_all(o.Currency):
            if cur.id == exclude:
                continue
            if cur.ref_currency is None or cur.ref_currency.id == cur.id:
                out.append(cur)
        return out

    @staticmethod
    def _units(items: List[Dict], group) -> list:
        old = {u.name: u for u in (group.units or [])}
        names = [str(i["name"]) for i in items]
        if len(set(names)) != len(names):
            dupe = next(n for n in names if names.count(n) > 1)
            raise _Refused(f"The unit '{dupe}' is given twice.",
                           next(i.get("where") for i in items
                                if i["name"] == dupe))
        refs = [i for i in items if i.get("reference")]
        if len(refs) != 1:
            raise _Refused(
                f"A unit group has exactly one reference unit; this one "
                f"has {len(refs)}.",
                (refs[1] if len(refs) > 1 else items[0]).get("where"),
                hint="Put REFERENCE after the factor of one unit; its "
                     "factor is 1.")
        units = []
        for i in items:
            factor = float(i["factor"])
            if factor <= 0:
                raise _Refused(
                    f"The factor of '{i['name']}' must be above 0 (got "
                    f"{factor:g}).", i.get("where"))
            if i.get("reference") and abs(factor - 1.0) > 1e-12:
                raise _Refused(
                    f"'{i['name']}' is the reference unit, so its factor "
                    f"is 1, not {factor:g}.", i.get("where"))
            prev = old.get(str(i["name"]))
            unit = o.Unit(id=prev.id if prev else str(uuid.uuid4()),
                          name=str(i["name"]), conversion_factor=factor,
                          is_ref_unit=bool(i.get("reference")))
            if i.get("synonyms"):
                unit.synonyms = [s.strip() for s in
                                 str(i["synonyms"]).split(";") if s.strip()]
            if i.get("description"):
                unit.description = str(i["description"])
            units.append(unit)
        return units

    @staticmethod
    def _dq_indicators(items: List[Dict]) -> list:
        if not items:
            raise _Refused("A data quality system needs at least one "
                           "indicator.")
        counts = {len(i.get("scores") or []) for i in items}
        if 0 in counts:
            bare = next(i for i in items if not i.get("scores"))
            raise _Refused(
                f"The indicator '{bare['name']}' has no scores.",
                bare.get("where"),
                hint="Follow each INDICATOR line with SCORE n \"label\" "
                     "lines.")
        if len(counts) > 1:
            raise _Refused(
                "Every indicator of a data quality system has the same "
                "number of scores.", items[0].get("where"))
        out = []
        for pos, i in enumerate(items, start=1):
            scores = []
            numbers = [int(s["position"]) for s in i["scores"]]
            if sorted(numbers) != list(range(1, len(numbers) + 1)):
                raise _Refused(
                    f"The scores of '{i['name']}' must be numbered 1 to "
                    f"{len(numbers)}, each once.", i.get("where"))
            for s in sorted(i["scores"], key=lambda s: int(s["position"])):
                score = o.DQScore(position=int(s["position"]),
                                  label=str(s.get("label") or ""))
                if s.get("description"):
                    score.description = str(s["description"])
                if s.get("uncertainty") is not None:
                    score.uncertainty = float(s["uncertainty"])
                scores.append(score)
            out.append(o.DQIndicator(name=str(i["name"]), position=pos,
                                     scores=scores))
        return out

    def attach_source_file(self, source_id: str, path: str) -> Dict:
        """Upload a file to a source (data/put/source-file, openLCA
        2.6.2 or later). The file is sent base64-encoded."""
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}."}
        if not self.ipc_supports("data/put/source-file"):
            return self._unsupported("data/put/source-file",
                                     "Attaching a file to a source")
        from olca_ipc.protocol import FileData
        ok = self.client.put_source_file(
            o.Ref(id=source_id, ref_type=o.RefType.Source),
            FileData.from_file(path))
        if not ok:
            return {"error": f"openLCA did not accept the file '{path}'."}
        self._cache.pop("Source", None)
        return {"source_id": source_id, "file": os.path.basename(path)}

    # ── impact methods ───────────────────────────────────────

    def _elementary_flow(self, name: str, compartment: Optional[str]):
        flows = [d for d in self._get_descriptors(o.Flow)
                 if getattr(d, "flow_type", None)
                 == o.FlowType.ELEMENTARY_FLOW]
        found = [d for d in flows if d.id == name]
        if not found:
            found = [d for d in flows if d.name == name]
        if compartment:
            low = compartment.lower()
            found = [d for d in found if low in self._folder(d).lower()]
        if len(found) == 1:
            return found[0]
        if not found:
            where = f" in \"{compartment}\"" if compartment else ""
            raise _Refused(
                f"No elementary flow is called '{name}'{where}.",
                hint=f"FIND FLOW \"{name}\" shows the names and "
                     f"compartments. A factor is for a flow that exists: "
                     f"make it first with MAKE FLOW ... TO AIR.")
        listing = "\n".join(f"    {self._folder(d):<50} {d.id}"
                            for d in found[:12])
        raise _Refused(
            f"'{name}' matches {len(found)} elementary flows:\n{listing}",
            hint="Add IN \"compartment\" after the flow name (part of the "
                 "path is enough), or use the UUID.")

    def _factor(self, spec: Dict) -> o.ImpactFactor:
        where = spec.get("where")
        try:
            d = self._elementary_flow(str(spec["flow"]),
                                      spec.get("compartment"))
            factor = o.ImpactFactor(
                flow=o.Ref(id=d.id, name=d.name, category=self._folder(d),
                           ref_type=o.RefType.Flow))
            if spec.get("formula"):
                factor.formula = str(spec["formula"])
                factor.value = float(spec.get("value") or 0.0)
            else:
                factor.value = float(spec["value"])
            if spec.get("unit"):
                fp_ref, u_ref, err = self._exchange_unit(d.id,
                                                         str(spec["unit"]))
                if err:
                    raise _Refused(err)
                factor.flow_property, factor.unit = fp_ref, u_ref
            if spec.get("location"):
                factor.location = self._location(str(spec["location"]))
            if spec.get("uncertainty"):
                u = spec["uncertainty"]
                made, err = make_uncertainty(u["kind"], u["values"])
                if err:
                    raise _Refused(err)
                factor.uncertainty = made
            return factor
        except _Refused as e:
            raise _Refused(e.message, where, e.hint)

    @staticmethod
    def _factor_key(f) -> Tuple:
        return (f.flow.id if f.flow else None,
                f.location.id if f.location else None)

    def _category_params(self, specs: List[Dict]) -> list:
        params = []
        for p in specs or []:
            param = o.Parameter(
                id=str(uuid.uuid4()), name=str(p["name"]),
                parameter_scope=o.ParameterScope.IMPACT_SCOPE)
            if p.get("formula"):
                param.formula = str(p["formula"])
                param.is_input_parameter = False
            else:
                param.value = float(p["value"])
                param.is_input_parameter = True
            params.append(param)
        return params

    def _nw_set(self, spec: Dict, categories: Dict[str, o.Ref],
                old_id: Optional[str] = None) -> o.NwSet:
        factors = []
        seen = set()
        for row in spec.get("factors") or []:
            where = row.get("where")
            name = str(row["category"])
            ref = categories.get(name)
            if ref is None:
                raise _Refused(
                    f"The method has no category called '{name}'.", where,
                    hint="Its categories: " + ", ".join(
                        f'"{c}"' for c in categories) + ".")
            if name in seen:
                raise _Refused(f"'{name}' is given twice in the NW set.",
                               where)
            seen.add(name)
            norm = row.get("normalisation")
            weight = row.get("weighting")
            if norm is not None and float(norm) == 0:
                raise _Refused(
                    f"The normalisation factor of '{name}' is 0: a result "
                    f"is divided by it.", where)
            factors.append(o.NwFactor(
                impact_category=ref,
                normalisation_factor=None if norm is None else float(norm),
                weighting_factor=None if weight is None else float(weight)))
        if not factors:
            raise _Refused(f"The NW set '{spec['name']}' has no factors.",
                           spec.get("where"),
                           hint="Give one line per category: \"category\", "
                                "normalisation [, weighting].")
        return o.NwSet(id=old_id or str(uuid.uuid4()),
                       name=str(spec["name"]), factors=factors,
                       weighted_score_unit=spec.get("unit") or None,
                       description=spec.get("description") or None)

    def _new_category(self, spec: Dict, method_name: str,
                      folder: Optional[str]) -> o.ImpactCategory:
        where = spec.get("where")
        if not spec.get("unit"):
            raise _Refused(
                f"The category '{spec['name']}' needs a reference unit.",
                where, hint="CATEGORY \"name\" UNIT \"kg CO2 eq\"")
        cat = o.ImpactCategory(
            id=str(uuid.uuid4()), name=str(spec["name"]),
            ref_unit=str(spec["unit"]), category=folder or method_name,
            tags=[OWN_TAG])
        if spec.get("description"):
            cat.description = str(spec["description"])
        if spec.get("code"):
            cat.code = str(spec["code"])
        if spec.get("direction"):
            cat.direction = (o.Direction.INPUT
                             if str(spec["direction"]).upper() == "INPUT"
                             else o.Direction.OUTPUT)
        cat.parameters = self._category_params(spec.get("parameters"))
        factors: Dict[Tuple, o.ImpactFactor] = {}
        for f in spec.get("factors") or []:
            made = self._factor(f)
            key = self._factor_key(made)
            if key in factors:
                raise _Refused(
                    f"'{made.flow.name}' has two factors in "
                    f"'{spec['name']}'.", f.get("where"))
            factors[key] = made
        cat.impact_factors = list(factors.values())
        return cat

    def make_method(self, name: str, folder: Optional[str],
                    categories: List[Dict],
                    nw_sets: Optional[List[Dict]] = None,
                    description: Optional[str] = None,
                    source: Optional[str] = None,
                    code: Optional[str] = None) -> Dict:
        """
        Make an impact method with its categories, characterisation
        factors and normalisation and weighting sets.

        categories: [{"name", "unit", "direction", "code",
        "description", "parameters": [{"name", "value" | "formula"}],
        "factors": [{"flow", "compartment", "value", "formula", "unit",
        "location", "uncertainty", "where"}], "where"}]
        nw_sets: [{"name", "unit", "description", "factors":
        [{"category", "normalisation", "weighting", "where"}], "where"}]

        Everything is checked before anything is written. A method of
        that name that exists already is left as it is.
        """
        try:
            if not name or not name.strip():
                return {"error": "The method needs a name."}
            if folder:
                err = _validate_category(folder)
                if err:
                    return {"error": err}
            existing = self._existing(o.ImpactMethod, name, None)
            if existing is not None:
                return {"id": existing.id, "name": existing.name,
                        "already_existed": True, "type": "METHOD"}
            if not categories:
                raise _Refused("A method needs at least one category.",
                               hint="Add CATEGORY \"name\" UNIT \"unit\" "
                                    "... END CATEGORY blocks.")
            names = [str(c["name"]) for c in categories]
            if len(set(names)) != len(names):
                dupe = next(n for n in names if names.count(n) > 1)
                raise _Refused(
                    f"The category '{dupe}' is given twice.",
                    next(c.get("where") for c in categories[::-1]
                         if c["name"] == dupe))
            made = [self._new_category(c, name, folder) for c in categories]
            refs = {c.name: o.Ref(id=c.id, name=c.name, ref_unit=c.ref_unit,
                                  ref_type=o.RefType.ImpactCategory)
                    for c in made}
            method = o.ImpactMethod(
                id=str(uuid.uuid4()), name=name, category=folder or None,
                impact_categories=list(refs.values()), tags=[OWN_TAG])
            if description:
                method.description = description
            if code:
                method.code = code
            if source:
                method.source = self._source(source)
            set_names = [str(s["name"]) for s in nw_sets or []]
            if len(set(set_names)) != len(set_names):
                raise _Refused("Two NW sets have the same name.")
            method.nw_sets = [self._nw_set(s, refs) for s in nw_sets or []]
            for cat in made:
                self.client.put(cat)
            self.client.put(method)
            self._cache.pop("ImpactMethod", None)
            self._cache.pop("ImpactCategory", None)
            result = {"id": method.id, "name": name, "created": True,
                      "type": "METHOD", "categories": len(made),
                      "factors": sum(len(c.impact_factors or [])
                                     for c in made),
                      "nw_sets": len(method.nw_sets)}
            if source:
                # openLCA's server (2.6, and its current source) reads a
                # method's source as text and so drops the reference.
                stored = self.client.get(o.ImpactMethod, method.id)
                if stored is None or stored.source is None:
                    result["source_dropped"] = True
            return result
        except _Refused as e:
            return {"error": e.message, "where": e.where, "hint": e.hint}
        except Exception as ex:
            return {"error": str(ex)}

    def method_is_own(self, ref: str) -> Dict:
        """{"own": bool, "name", "factors"} for a method: whether
        olcaBASIC made it, and how many factors it holds."""
        entity, err = self._get_one("METHOD", ref)
        if err:
            return err
        return {"own": OWN_TAG in (entity.tags or []), "name": entity.name,
                "id": entity.id,
                "factors": self._factor_count("METHOD", entity),
                "categories": len(entity.impact_categories or [])}

    def edit_method(self, ref: str, categories: Optional[List[Dict]] = None,
                    remove_categories: Optional[List[str]] = None,
                    nw_sets: Optional[List[Dict]] = None,
                    remove_nw_sets: Optional[List[str]] = None,
                    description: Optional[str] = None,
                    confirm_foreign: bool = False,
                    dry_run: bool = False) -> Dict:
        """
        Change an impact method.

        categories: as in make_method. A category that exists has the
        factors given added, or replaced where the flow (and location)
        already has one; "remove_factors": [{"flow", "compartment"}]
        takes factors out; "unit", "description", "direction" and
        "parameters" are set when given. A category that does not exist
        is added.

        A method olcaBASIC did not make is refused unless
        confirm_foreign is True. dry_run=True checks everything and
        counts what would change, and writes nothing.
        """
        try:
            method, err = self._get_one("METHOD", ref)
            if err:
                return err
            own = OWN_TAG in (method.tags or [])
            current = {c.name: c for c in method.impact_categories or []}
            changes: List[str] = []
            to_put: List[Any] = []
            to_delete: List[Any] = []
            changed_factors = 0

            for spec in categories or []:
                cname = str(spec["name"])
                if cname in current:
                    cat = self.client.get(o.ImpactCategory, current[cname].id)
                    factors = {self._factor_key(f): f
                               for f in cat.impact_factors or []}
                    added = replaced = removed = 0
                    for f in spec.get("factors") or []:
                        made = self._factor(f)
                        key = self._factor_key(made)
                        if key in factors:
                            replaced += 1
                        else:
                            added += 1
                        factors[key] = made
                    for f in spec.get("remove_factors") or []:
                        try:
                            d = self._elementary_flow(
                                str(f["flow"]), f.get("compartment"))
                        except _Refused as e:
                            raise _Refused(e.message, f.get("where"), e.hint)
                        keys = [k for k in factors if k[0] == d.id]
                        if not keys:
                            raise _Refused(
                                f"'{cname}' has no factor for "
                                f"'{d.name}'.", f.get("where"))
                        for k in keys:
                            del factors[k]
                            removed += 1
                    cat.impact_factors = list(factors.values())
                    if spec.get("unit"):
                        cat.ref_unit = str(spec["unit"])
                    if spec.get("description") is not None:
                        cat.description = str(spec["description"])
                    if spec.get("parameters"):
                        names = {p["name"] for p in spec["parameters"]}
                        cat.parameters = [
                            p for p in cat.parameters or []
                            if p.name not in names
                        ] + self._category_params(spec["parameters"])
                    to_put.append(cat)
                    changed_factors += added + replaced + removed
                    changes.append(
                        f"category '{cname}': {added} factor(s) added, "
                        f"{replaced} replaced, {removed} removed")
                else:
                    cat = self._new_category(
                        spec, method.name, getattr(method, "category", None))
                    if not own:
                        cat.tags = []
                    to_put.append(cat)
                    method.impact_categories = list(
                        method.impact_categories or []) + [o.Ref(
                            id=cat.id, name=cat.name, ref_unit=cat.ref_unit,
                            ref_type=o.RefType.ImpactCategory)]
                    current[cname] = method.impact_categories[-1]
                    changed_factors += len(cat.impact_factors or [])
                    changes.append(
                        f"category '{cname}' added "
                        f"({len(cat.impact_factors or [])} factors)")
            for cname in remove_categories or []:
                if cname not in current:
                    raise _Refused(
                        f"The method has no category called '{cname}'.")
                cat = self.client.get(o.ImpactCategory, current[cname].id)
                changed_factors += len(cat.impact_factors or []) if cat else 0
                method.impact_categories = [
                    c for c in method.impact_categories
                    if c.id != current[cname].id]
                method.nw_sets = [
                    self._without_category(s, current[cname].id)
                    for s in method.nw_sets or []]
                if cat is not None:
                    to_delete.append(cat)
                del current[cname]
                changes.append(f"category '{cname}' removed")
            refs = {c.name: c for c in method.impact_categories or []}
            sets = list(method.nw_sets or [])
            for sname in remove_nw_sets or []:
                kept = [s for s in sets if s.name != sname]
                if len(kept) == len(sets):
                    raise _Refused(f"The method has no NW set '{sname}'.")
                sets = kept
                changes.append(f"NW set '{sname}' removed")
            for spec in nw_sets or []:
                old = next((s for s in sets if s.name == spec["name"]), None)
                made = self._nw_set(spec, refs, old.id if old else None)
                sets = [s for s in sets if s.name != spec["name"]] + [made]
                changes.append(f"NW set '{spec['name']}' "
                               f"{'replaced' if old else 'added'} "
                               f"({len(made.factors)} factors)")
            method.nw_sets = sets
            if description is not None:
                method.description = description
                changes.append("description updated")

            out = {"id": method.id, "name": method.name, "own": own,
                   "changes": changes, "factors_changed": changed_factors}
            if not own and not confirm_foreign:
                out["error"] = (f"'{method.name}' was not made by "
                                f"olcaBASIC.")
                out["foreign"] = True
                return out
            if dry_run or not changes:
                return out
            for cat in to_put:
                self.client.put(cat)
            self.client.put(method)
            if to_delete:
                others = set()
                for m in self.client.get_all(o.ImpactMethod):
                    if m.id != method.id:
                        others.update(c.id for c in m.impact_categories or [])
                for cat in to_delete:
                    if cat.id not in others:
                        self.client.delete(cat)
            self._cache.pop("ImpactMethod", None)
            self._cache.pop("ImpactCategory", None)
            out["edited"] = True
            return out
        except _Refused as e:
            return {"error": e.message, "where": e.where, "hint": e.hint}
        except Exception as ex:
            return {"error": str(ex)}

    @staticmethod
    def _without_category(nw_set, category_id: str):
        nw_set.factors = [f for f in nw_set.factors or []
                          if not (f.impact_category
                                  and f.impact_category.id == category_id)]
        return nw_set

    # ── projects ─────────────────────────────────────────────

    def make_project(self, name: str, folder: Optional[str], method: str,
                     variants: List[Dict], nw_set: Optional[str] = None,
                     with_costs: bool = False,
                     with_regionalisation: bool = False,
                     description: Optional[str] = None) -> Dict:
        """
        Make a project: a method and the variants to compare.

        variants: [{"name", "system", "amount", "unit", "allocation",
        "disabled", "description", "values": [{"name", "value",
        "process", "where"}], "where"}]. A project of that name that
        exists already is left as it is.
        """
        try:
            if folder:
                err = _validate_category(folder)
                if err:
                    return {"error": err}
            existing = self._existing(o.Project, name, None)
            if existing is not None:
                return {"id": existing.id, "name": existing.name,
                        "already_existed": True, "type": "PROJECT"}
            found = self.find_method_strict(method)
            if "error" in found:
                raise _Refused(found["error"], "method")
            m = next(d for d in self._get_descriptors(o.ImpactMethod)
                     if d.id == found["id"])
            project = o.Project(
                id=str(uuid.uuid4()), name=name, category=folder or None,
                impact_method=o.Ref(id=m.id, name=m.name,
                                    ref_type=o.RefType.ImpactMethod),
                is_with_costs=bool(with_costs),
                is_with_regionalization=bool(with_regionalisation))
            if description:
                project.description = description
            if nw_set:
                ref, err = self._nw_set_ref(m, nw_set)
                if err:
                    raise _Refused(err, "nw_set")
                project.nw_set = ref
            if not variants:
                raise _Refused("A project needs at least one variant.",
                               hint="Add VARIANT \"name\" SYSTEM \"system\" "
                                    "... END VARIANT blocks.")
            names = [str(v["name"]) for v in variants]
            if len(set(names)) != len(names):
                dupe = next(n for n in names if names.count(n) > 1)
                raise _Refused(f"The variant '{dupe}' is given twice.")
            project.variants = [self._variant(v) for v in variants]
            self.client.put(project)
            self._cache.pop("Project", None)
            return {"id": project.id, "name": name, "created": True,
                    "type": "PROJECT", "variants": len(project.variants)}
        except _Refused as e:
            return {"error": e.message, "where": e.where, "hint": e.hint}
        except Exception as ex:
            return {"error": str(ex)}

    def _variant(self, v: Dict) -> o.ProjectVariant:
        where = v.get("where")
        found = self.resolve_one("SYSTEM", str(v["system"]))
        if "id" not in found:
            raise _Refused(found["error"], where, found.get("hint", ""))
        system = self.client.get(o.ProductSystem, found["id"])
        variant = o.ProjectVariant(
            name=str(v["name"]),
            product_system=o.Ref(id=system.id, name=system.name,
                                 ref_type=o.RefType.ProductSystem),
            is_disabled=bool(v.get("disabled")))
        if v.get("description"):
            variant.description = str(v["description"])
        if v.get("amount") is not None:
            if float(v["amount"]) <= 0:
                raise _Refused(f"The amount of variant '{v['name']}' must "
                               f"be above 0.", where)
            variant.amount = float(v["amount"])
            unit = self._get_unit_ref(str(v.get("unit") or ""))
            if unit is None:
                raise _Refused(
                    f"Unit '{v.get('unit')}' is not in this database.",
                    where)
            variant.unit = unit
        else:
            variant.amount = system.target_amount or 1.0
            variant.unit = system.target_unit
        try:
            variant.allocation_method = self._resolve_allocation(
                v.get("allocation"))
        except ValueError as ex:
            raise _Refused(str(ex), where)
        redefs = []
        if v.get("values"):
            targets = self._parameter_targets(system)
            for value in v["values"]:
                vw = value.get("where") or where
                copies = [c for c in targets.get(value["name"], [])
                          if c["is_input"]]
                if value.get("process"):
                    copies = [c for c in copies if c["context"] is not None
                              and c["context"].name == value["process"]]
                if not copies:
                    raise _Refused(
                        f"'{system.name}' has no parameter "
                        f"'{value['name']}' that can be set"
                        + (f" in process '{value['process']}'"
                           if value.get("process") else "") + ".", vw,
                        hint=f"SHOW SYSTEM \"{system.name}\" PARAMS lists "
                             f"them.")
                for c in copies:
                    redefs.append(o.ParameterRedef(
                        name=value["name"], value=float(value["value"]),
                        context=c["context"]))
        variant.parameter_redefs = redefs
        return variant

    def calculate_project(self, ref: str) -> Dict:
        """
        Calculate every enabled variant of a project with the project's
        method and compare them. openLCA's IPC server has no project
        calculation, so each variant is one ordinary calculation with
        the variant's system, amount, allocation and parameter values.
        Returns the shape of run_scenarios, plus "variants" (what each
        was calculated for) and, with an NW set, "normalised" and
        "weighted".
        """
        try:
            project, err = self._get_one("PROJECT", ref)
            if err:
                return err
            if project.impact_method is None:
                return {"error": f"The project '{project.name}' has no "
                                 f"impact method."}
            results, info, normalised, weighted, costs = {}, {}, {}, {}, {}
            skipped = []
            for v in project.variants or []:
                if v.is_disabled:
                    skipped.append(v.name)
                    continue
                setup = o.CalculationSetup(
                    target=v.product_system,
                    impact_method=project.impact_method,
                    allocation=(v.allocation_method
                                or o.AllocationType.USE_DEFAULT_ALLOCATION),
                    parameters=list(v.parameter_redefs or []))
                if v.amount:
                    setup.amount = v.amount
                if v.unit is not None:
                    setup.unit = v.unit
                if project.nw_set is not None:
                    setup.nw_set = project.nw_set
                if project.is_with_costs:
                    setup.with_costs = True
                if project.is_with_regionalization:
                    setup.with_regionalization = True
                result = self.client.calculate(setup)
                try:
                    state = result.wait_until_ready()
                    if getattr(state, "error", None):
                        return {"error": f"openLCA could not calculate the "
                                         f"variant '{v.name}': {state.error}"}
                    results[v.name] = self._impacts_to_list(
                        result.get_total_impacts())
                    if project.nw_set is not None:
                        normalised[v.name] = {
                            i.impact_category.name: i.amount
                            for i in result.get_normalized_impacts()}
                        weighted[v.name] = {
                            i.impact_category.name: i.amount
                            for i in result.get_weighted_impacts()}
                    if project.is_with_costs:
                        costs[v.name] = result.get_total_costs().amount
                finally:
                    result.dispose()
                info[v.name] = {
                    "system": (v.product_system.name
                               if v.product_system else ""),
                    "amount": v.amount,
                    "unit": v.unit.name if v.unit is not None else "",
                    "parameters": {r.name: r.value
                                   for r in v.parameter_redefs or []}}
            if not results:
                return {"error": f"Every variant of '{project.name}' is "
                                 f"disabled."}
            out = {"project": project.name,
                   "system": f"project {project.name}",
                   "method": project.impact_method.name,
                   "scenario_count": len(results), "results": results,
                   "variants": info}
            if skipped:
                out["disabled"] = skipped
            if normalised:
                out["nw_set"] = project.nw_set.name
                out["normalised"] = normalised
                out["weighted"] = weighted
            if costs:
                out["costs"] = costs
            return out
        except _Refused as e:
            return {"error": e.message}
        except Exception as ex:
            return {"error": str(ex)}

    # ── stored results ───────────────────────────────────────

    def save_result(self, handle: str, name: str,
                    folder: Optional[str] = None,
                    description: Optional[str] = None,
                    replace: bool = False) -> Dict:
        """
        Store an open result in the database as an openLCA Result
        entity: the product system, the method, the impact totals and
        the inventory, with the reference flow. A stored result of that
        name is replaced only with replace=True.
        """
        try:
            r = self._results().get(handle)
            if r is None:
                return {"error": "That result is not open any more."}
            if not name or not name.strip():
                return {"error": "The stored result needs a name."}
            if folder:
                err = _validate_category(folder)
                if err:
                    return {"error": err}
            existing = self._existing(o.Result, name, None)
            if existing is not None and not replace:
                return {"error": f"A stored result called '{name}' exists "
                                 f"already.",
                        "hint": f"Use another name, DELETE RESULT "
                                f"\"{name}\" first, or add REPLACE.",
                        "exists": True}
            entity = o.Result(
                id=existing.id if existing is not None
                else str(uuid.uuid4()),
                name=name, category=folder or None,
                product_system=o.Ref(id=r.system.id, name=r.system.name,
                                     ref_type=o.RefType.ProductSystem))
            if description:
                entity.description = description
            if r.method is not None:
                entity.impact_method = o.Ref(
                    id=r.method.id, name=r.method.name,
                    ref_type=o.RefType.ImpactMethod)
                entity.impact_results = [
                    o.ImpactResult(indicator=v.impact_category,
                                   amount=v.amount)
                    for v in r.result.get_total_impacts()]
            flows = []
            demand = r.result.get_demand()
            if demand is not None and demand.tech_flow is not None \
                    and demand.tech_flow.flow is not None:
                system = self.client.get(o.ProductSystem, r.system.id)
                ref_flow = o.FlowResult(
                    flow=demand.tech_flow.flow, amount=demand.amount,
                    is_input=False, is_ref_flow=True)
                if system is not None and not r.setup.get("amount"):
                    ref_flow.amount = system.target_amount or demand.amount
                    ref_flow.unit = system.target_unit
                    ref_flow.flow_property = system.target_flow_property
                flows.append(ref_flow)
            for v in r.result.get_total_flows():
                ef = v.envi_flow
                if ef is None or ef.flow is None:
                    continue
                flows.append(o.FlowResult(
                    flow=ef.flow, amount=v.amount, is_input=bool(ef.is_input),
                    is_ref_flow=False, location=getattr(ef, "location", None)))
            entity.flow_results = flows
            self.client.put(entity)
            self._cache.pop("Result", None)
            return {"id": entity.id, "name": name, "saved": True,
                    "replaced": existing is not None,
                    "system": r.system.name,
                    "method": r.method.name if r.method else "",
                    "impact_results": len(entity.impact_results or []),
                    "flow_results": len(flows)}
        except Exception as ex:
            return {"error": str(ex)}

    # ── EPDs ─────────────────────────────────────────────────

    def set_analysis_group(self, system_id: str, name: str,
                           process_ids: List[str]) -> Dict:
        """Put the processes of a product system that are in
        process_ids into one analysis group (replacing the group of
        that name). Processes that are not in the system are left out.
        Nothing is written when the group is already as asked."""
        try:
            system = self.client.get(o.ProductSystem, system_id)
            if system is None:
                return {"error": f"Product system not found: {system_id}"}
            wanted = set(process_ids)
            refs = [o.Ref(id=d.id, name=d.name, ref_type=o.RefType.Process)
                    for d in self._system_processes(system)
                    if d.id in wanted]
            groups = list(system.analysis_groups or [])
            old = next((g for g in groups if g.name == name), None)
            if old is not None and {r.id for r in old.processes or []} == {
                    r.id for r in refs}:
                return {"system_id": system_id, "group": name,
                        "processes": len(refs), "changed": False}
            taken = {r.id for g in groups if g.name != name
                     for r in g.processes or []}
            refs = [r for r in refs if r.id not in taken]
            groups = [g for g in groups if g.name != name]
            if refs:
                groups.append(o.AnalysisGroup(name=name, processes=refs))
            system.analysis_groups = groups
            self.client.put(system)
            self._cache.pop("ProductSystem", None)
            return {"system_id": system_id, "group": name,
                    "processes": len(refs), "changed": True}
        except Exception as ex:
            return {"error": str(ex)}

    def save_epd(self, name: str, folder: Optional[str],
                 modules: List[Dict], product_result: str,
                 amount: float, unit: str,
                 fields: Optional[Dict[str, Any]] = None,
                 replace: bool = False) -> Dict:
        """
        Write an openLCA Epd entity.

        modules: [{"name", "result_id"}], one per declared module, each
        pointing at a stored Result. product_result: the id of the
        stored Result whose reference flow is the declared product.
        amount and unit: the declared (or functional) unit. fields:
        "manufacturer", "verifier", "program_operator", "data_generator"
        (actors), "pcr" (a source), "registration_id", "urn",
        "valid_from", "valid_until" (dates), "description".

        An EPD of that name is replaced only with replace=True.
        """
        fields = dict(fields or {})
        try:
            if folder:
                err = _validate_category(folder)
                if err:
                    return {"error": err}
            existing = self._existing(o.Epd, name, None)
            if existing is not None and not replace:
                return {"error": f"An EPD called '{name}' is in the "
                                 f"database already.", "exists": True,
                        "hint": "EPD SAVE REPLACE writes over it."}
            result = self.client.get(o.Result, product_result)
            ref = next((f for f in (result.flow_results or [])
                        if f.is_ref_flow), None) if result else None
            if ref is None or ref.flow is None:
                return {"error": "The stored result of the product has no "
                                 "reference flow."}
            fp_ref, unit_ref, err = self._exchange_unit(ref.flow.id, unit)
            if err:
                return {"error": f"The declared unit '{unit}' does not fit "
                                 f"the product flow '{ref.flow.name}': "
                                 f"{err}."}
            epd = o.Epd(
                id=existing.id if existing is not None else str(uuid.uuid4()),
                name=name, category=folder or None, tags=[OWN_TAG],
                product=o.EpdProduct(flow=ref.flow, flow_property=fp_ref,
                                     unit=unit_ref, amount=float(amount)),
                modules=[o.EpdModule(
                    name=m["name"], multiplier=1.0,
                    result=o.Ref(id=m["result_id"], name=m.get("result"),
                                 ref_type=o.RefType.Result))
                    for m in modules])
            for key in ("manufacturer", "verifier", "program_operator",
                        "data_generator"):
                if fields.get(key):
                    setattr(epd, key, self._field(key, self._actor,
                                                  fields[key]))
            if fields.get("pcr"):
                epd.pcr = self._field("pcr", self._source, fields["pcr"])
            for key in ("valid_from", "valid_until"):
                if fields.get(key):
                    iso, err = parse_date(fields[key])
                    if err:
                        raise _Refused(err, key)
                    setattr(epd, key, iso)
            if epd.valid_from and epd.valid_until \
                    and epd.valid_until <= epd.valid_from:
                raise _Refused("VALID UNTIL is not after VALID FROM.",
                               "valid_until")
            for key in ("registration_id", "urn", "description"):
                if fields.get(key):
                    setattr(epd, key, str(fields[key]))
            self.client.put(epd)
            self._cache.pop("Epd", None)
            return {"id": epd.id, "name": name, "saved": True,
                    "replaced": existing is not None,
                    "product": ref.flow.name, "modules": len(modules)}
        except _Refused as e:
            return {"error": e.message, "where": e.where, "hint": e.hint}
        except Exception as ex:
            return {"error": str(ex)}

    # ── export and shutdown ──────────────────────────────────

    def export_json_ld(self, word: str, ref: str, path: str) -> Dict:
        """Ask openLCA to write an entity, with what it depends on, to a
        JSON-LD zip file. The file is written by openLCA, on the machine
        openLCA runs on."""
        try:
            found = self.resolve_one(word, ref)
            if "id" not in found:
                return found
            cls = self._entity_class(word)
            data, err = self.client.rpc_call("export/json-ld", {
                "path": path,
                "models": [{"@type": cls.__name__, "@id": found["id"]}]})
            if err and "does not understand" in str(err).lower():
                return self._unsupported("export/json-ld",
                                         "Exporting JSON-LD")
            if err:
                return {"error": f"openLCA could not write the export: "
                                 f"{err}"}
            return {"exported": True, "type": word, "name": found["name"],
                    "path": path, "note": str(data or "")}
        except _Refused as e:
            return {"error": e.message}
        except Exception as ex:
            return {"error": str(ex)}

    def shutdown_server(self) -> Dict:
        """Stop openLCA's IPC server and close its database
        (runtime/shutdown). Open results are disposed first."""
        self.close_all_results()
        try:
            _, err = self.client.rpc_call("runtime/shutdown", None)
        except Exception as ex:      # the server may drop the connection
            return {"shut_down": True, "note": str(ex)}
        if err and "does not understand" in str(err).lower():
            return {"error": f"openLCA did not stop its server: {err}"}
        return {"shut_down": True}


def _formula_mentions(data, pattern, name: str) -> bool:
    """True if a formula anywhere in an entity's JSON names a
    parameter, or a parameter redefinition without a context sets it."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key in _FORMULA_KEYS and isinstance(value, str):
                if pattern.search(value):
                    return True
            elif key in ("parameterRedefs",) or (
                    key == "parameters" and isinstance(value, list)
                    and value and isinstance(value[0], dict)
                    and "context" not in value[0]
                    and "@type" not in value[0]
                    and "parameterScope" not in value[0]):
                for redef in value or []:
                    if (isinstance(redef, dict) and redef.get("name") == name
                            and not redef.get("context")):
                        return True
            if _formula_mentions(value, pattern, name):
                return True
    elif isinstance(data, list):
        return any(_formula_mentions(v, pattern, name) for v in data)
    return False
