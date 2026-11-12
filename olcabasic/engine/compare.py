"""
Does a PROCESS block still say what the database holds?

MAKE PROCESS on a process that exists leaves the process alone, so a
program can be run twice. That is only safe when the block has not
changed since: a block that was edited and run again used to print a
warning and leave the old process in place, and the results then came
from a model the program no longer described.

process_block_differences builds the process the block describes
without saving it, and compares it with the stored one: exchanges
(flow, direction, amount or formula, unit, provider, pedigree, comment,
uncertainty, cost, site, avoided), parameters, allocation factors,
documentation, social aspects, type, infrastructure, schemas, location
and description. It returns one sentence per difference.

Not compared: what openLCA or olcaBASIC writes by itself (ids, version,
last change, tags, the data quality ratings in the description), and
the automatic parameters' names (their values are compared as the
amounts they stand for).
"""

import re
from typing import Any, Dict, List, Optional

import olca_schema as o

from . import ratings_block
from .fields import (ALLOCATION_NAMES, DOCUMENT_FIELDS, _Refused,
                     uncertainty_dict)

#: An automatic parameter: pNN_process__flow_unit (see _make_param_name).
AUTO_PARAMETER = re.compile(r"^p\d\d_")

#: Two numbers are the same within this (relative).
SAME_NUMBER = 1e-9

#: No more than this many differences are listed in the error.
MAX_DIFFERENCES = 12


def _same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) \
            and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(a - b) <= SAME_NUMBER * max(abs(a), abs(b), 1e-300) \
            or a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def _blank(value):
    """None, '' and [] are all 'not set'."""
    return None if value in (None, "", [], {}, False) else value


def _show(value) -> str:
    if value is None:
        return "nothing"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, dict) and "text" in value:
        return str(value["text"])
    if isinstance(value, (dict, list)):
        text = str(value)
        return text if len(text) <= 80 else text[:77] + "..."
    return f"'{value}'" if isinstance(value, str) else str(value)


class CompareMixin:

    def _amounts(self, process) -> Dict[str, float]:
        """The values of a process's automatic parameters by name."""
        return {p.name: p.value for p in process.parameters or []
                if AUTO_PARAMETER.match(p.name or "")
                and p.is_input_parameter and not p.formula}

    def _exchange_row(self, ex, autos: Dict[str, float]) -> Dict[str, Any]:
        formula = (ex.amount_formula or "").strip()
        if formula in autos:
            amount = autos[formula]
        elif formula:
            amount = re.sub(r"\s+", "", formula)
        else:
            amount = ex.amount
        cost = None
        if ex.cost_value is not None or ex.cost_formula:
            cost = {"value": ex.cost_value or 0.0,
                    "formula": ex.cost_formula or "",
                    "currency": ex.currency.id if ex.currency else ""}
        u = uncertainty_dict(ex.uncertainty)
        return {
            "amount": amount,
            "unit": ex.unit.name if ex.unit else "",
            "provider": (ex.default_provider.id
                         if ex.default_provider is not None else None),
            "reference product": bool(ex.is_quantitative_reference),
            "avoided": bool(ex.is_avoided_product),
            "pedigree": _blank(ex.dq_entry),
            "comment": _blank(ex.description),
            "uncertainty": {"text": u["text"]} if u else None,
            "base uncertainty": _blank(ex.base_uncertainty),
            "cost": cost,
            "site": ex.location.id if ex.location else None,
        }

    def _block_view(self, process) -> Dict[str, Any]:
        autos = self._amounts(process)
        exchanges: Dict[tuple, List[Dict]] = {}
        names: Dict[tuple, str] = {}
        by_internal = {}
        for ex in process.exchanges or []:
            key = (ex.flow.id if ex.flow else "", bool(ex.is_input))
            exchanges.setdefault(key, []).append(
                self._exchange_row(ex, autos))
            label = (ex.flow.name if ex.flow and ex.flow.name else "") \
                or self.flow_info(key[0]).get("name", key[0])
            names[key] = label
            by_internal[ex.internal_id] = label
        parameters = {}
        for p in process.parameters or []:
            if p.name in autos:
                continue
            u = uncertainty_dict(p.uncertainty)
            parameters[p.name] = {
                "value": (re.sub(r"\s+", "", p.formula) if p.formula
                          else p.value),
                "uncertainty": {"text": u["text"]} if u else None}
        allocation = {}
        for f in process.allocation_factors or []:
            word = ALLOCATION_NAMES.get(f.allocation_type, "?")
            key = (word, f.product.id if f.product else "",
                   by_internal.get(f.exchange.internal_id, "")
                   if f.exchange is not None else "")
            allocation[key] = (re.sub(r"\s+", "", f.formula) if f.formula
                               else f.value)
        doc = process.process_documentation
        document = {}
        for field_name, kind in DOCUMENT_FIELDS.items():
            value = getattr(doc, field_name, None) if doc is not None else None
            if value in (None, [], ""):
                continue
            document[field_name] = self._doc_plain(kind, value)
        social = {}
        for a in process.social_aspects or []:
            social[a.social_indicator.id if a.social_indicator else ""] = {
                "raw": a.raw_amount or "",
                "risk": a.risk_level.name if a.risk_level else "",
                "activity": a.activity_value,
                "comment": a.comment or "",
                "source": a.source.id if a.source else "",
                "quality": a.quality or ""}
        default = process.default_allocation_method
        return {
            "exchanges": exchanges, "names": names,
            "parameters": parameters, "allocation": allocation,
            "document": document, "social": social,
            "fields": {
                "type": ("LCI RESULT" if process.process_type
                         == o.ProcessType.LCI_RESULT else "UNIT"),
                "infrastructure": bool(process.is_infrastructure_process),
                "default allocation": (ALLOCATION_NAMES.get(default, "")
                                       if default is not None else ""),
                "location": process.location.id if process.location else None,
                "description": _blank(
                    ratings_block.strip(process.description).strip()),
                "flow schema": (process.exchange_dq_system.id
                                if process.exchange_dq_system else None),
                "process schema": (process.dq_system.id
                                   if process.dq_system else None),
                "process pedigree": _blank(process.dq_entry),
                "social schema": (process.social_dq_system.id
                                  if process.social_dq_system else None),
            },
        }

    def _name_of_process(self, process_id: Optional[str]) -> str:
        if not process_id:
            return "no provider"
        for d in self._get_descriptors(o.Process):
            if d.id == process_id:
                return f"'{d.name}'"
        return process_id

    def process_block_differences(
            self, process_id: str, name: str, category: str,
            exchanges: List[Dict], parameters: Optional[List[Dict]] = None,
            description: str = "", location: Optional[str] = None,
            flow_schema: Optional[str] = None,
            process_schema: Optional[str] = None,
            fields: Optional[Dict] = None,
            documentation: Optional[Dict[str, str]] = None) -> Dict:
        """
        Compare the process a PROCESS block describes with the stored
        process of that name. The arguments are those of create_process,
        plus the block's wider fields (as for set_process_fields) and
        the documentation its DATA line sets.

        Returns {"process_id", "process_name", "differences": [...]}:
        one sentence per difference, none when the block still says
        what the database holds. Nothing is written.
        """
        try:
            stored = self.client.get(o.Process, process_id)
            if stored is None:
                return {"error": f"Process not found: {process_id}"}
            built = self.create_process(
                name, category, [dict(e) for e in exchanges],
                [dict(p) for p in parameters or []] or None, description,
                location, flow_schema, process_schema, _build_only=True)
            if "error" in built:
                return built
            fresh = built["process"]
            if fields:
                fields = dict(fields)
                fields.pop("has_process_schema", None)
                plan = self._resolve_process_fields(
                    fields, self._exchange_views(fresh), fresh)
                self._apply_process_fields(fresh, plan)
            if documentation:
                doc = fresh.process_documentation or o.ProcessDocumentation()
                for field_name, value in documentation.items():
                    setattr(doc, field_name, value)
                fresh.process_documentation = doc
            have, want = self._block_view(stored), self._block_view(fresh)
            given = set((fields or {}).get("document") or {}) \
                | set(documentation or {})
            return {"process_id": stored.id, "process_name": stored.name,
                    "differences": self._differences(have, want, given)}
        except _Refused as e:
            return {"error": e.message, "where": e.where, "hint": e.hint}
        except Exception as ex:
            return {"error": str(ex)}

    def _differences(self, have: Dict, want: Dict, given_doc: set) -> List[str]:
        """have: the stored process; want: what the block describes."""
        out: List[str] = []
        names = dict(have["names"])
        names.update(want["names"])
        for key in sorted(set(have["exchanges"]) | set(want["exchanges"]),
                          key=lambda k: (not k[1], names.get(k, ""))):
            word = "INPUT" if key[1] else "OUTPUT"
            label = f'{word} "{names.get(key, key[0])}"'
            stored = have["exchanges"].get(key, [])
            block = want["exchanges"].get(key, [])
            if len(stored) != len(block):
                if not stored:
                    out.append(f"{label} is in the block and not in the "
                               f"database.")
                elif not block:
                    out.append(f"{label} is in the database and not in the "
                               f"block.")
                else:
                    out.append(f"{label} is there {len(stored)} times in "
                               f"the database and {len(block)} in the block.")
                continue
            for s_row, b_row in zip(stored, block):
                for what in s_row:
                    a, b = s_row[what], b_row[what]
                    if _same(a, b):
                        continue
                    if what == "provider":
                        a, b = (self._name_of_process(a),
                                self._name_of_process(b))
                        out.append(f"{label}: the provider is {a} in the "
                                   f"database and {b} in the block.")
                    else:
                        out.append(f"{label}: {what} is {_show(a)} in the "
                                   f"database and {_show(b)} in the block.")
        for name in sorted(set(have["parameters"]) | set(want["parameters"])):
            a, b = have["parameters"].get(name), want["parameters"].get(name)
            if a is None:
                out.append(f"Parameter {name} is in the block and not in "
                           f"the database.")
            elif b is None:
                out.append(f"Parameter {name} is in the database and not "
                           f"in the block.")
            else:
                for what in ("value", "uncertainty"):
                    if not _same(a[what], b[what]):
                        out.append(
                            f"Parameter {name}: {what} is {_show(a[what])} "
                            f"in the database and {_show(b[what])} in the "
                            f"block.")
        for key in sorted(set(have["allocation"]) | set(want["allocation"])):
            a, b = have["allocation"].get(key), want["allocation"].get(key)
            if not _same(a, b):
                product = self.flow_info(key[1]).get("name", key[1])
                of = f" for '{key[2]}'" if key[2] else ""
                out.append(
                    f"ALLOCATION {key[0]} \"{product}\"{of}: "
                    f"{_show(a)} in the database and {_show(b)} in the "
                    f"block.")
        for field_name in sorted(set(have["document"]) | set(want["document"])):
            a = have["document"].get(field_name)
            b = want["document"].get(field_name)
            # The stored process may hold documentation the block never
            # set (olcaBASIC dates a new process; a person adds a review
            # in openLCA). Only what the block gives is compared.
            if field_name not in given_doc:
                continue
            if field_name in ("valid_from", "valid_until", "creation_date"):
                a, b = str(a or "")[:10], str(b or "")[:10]
            if not _same(a, b):
                out.append(
                    f"DOCUMENT {field_name.replace('_', ' ')}: {_show(a)} in "
                    f"the database and {_show(b)} in the block.")
        for key in sorted(set(have["social"]) | set(want["social"])):
            a, b = have["social"].get(key), want["social"].get(key)
            if not _same(a, b):
                out.append("The SOCIAL lines differ from the social aspects "
                           "in the database.")
                break
        for what in have["fields"]:
            a, b = have["fields"][what], want["fields"][what]
            if not _same(a, b):
                if what == "description":
                    out.append("The DESCRIPTION differs from the one in the "
                               "database.")
                else:
                    out.append(f"{what.capitalize()} is {_show(a)} in the "
                               f"database and {_show(b)} in the block.")
        return out
