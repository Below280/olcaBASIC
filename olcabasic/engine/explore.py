"""
Reading the database: searching, listing and inspecting. Nothing here
writes to openLCA.

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


class ExploreMixin:
    """Reading the database: searching, listing and inspecting. Nothing here"""

    # ── database info ────────────────────────────────────────

    def get_database_info(self) -> Dict:
        """Counts of key entities in the connected database."""
        try:
            return {
                "status": "connected",
                "product_systems": len(self._get_descriptors(o.ProductSystem)),
                "processes": len(self._get_descriptors(o.Process)),
                "flows": len(self._get_descriptors(o.Flow)),
                "impact_methods": len(self._get_descriptors(o.ImpactMethod)),
                "parameters": len(self._get_descriptors(o.Parameter)),
                "database_family": self._detect_database_family(),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ── data quality systems ──────────────────────────────────

    def list_dq_systems(self) -> Dict:
        """
        List all DQ (Data Quality) systems in the database.

        Returns process schemas, flow schemas, and social schemas
        available for assignment to processes. Indicators are listed in
        position order, which is the order of the scores in a pedigree
        entry such as "(1;2;4;1;3)". The user picks which
        ones to use; the IDs are then passed to create_process via
        flow_schema or process_schema.
        """
        try:
            descriptors = list(self.client.get_descriptors(o.DQSystem))
            if not descriptors:
                return {
                    "dq_systems": [],
                    "count": 0,
                    "note": "No DQ systems in this database. "
                            "Flow and process schemas cannot be set.",
                }

            systems = []
            for desc in descriptors:
                full = self.client.get(o.DQSystem, desc.id)
                indicator_count = (
                    len(full.indicators) if full and full.indicators else 0
                )
                indicators = []
                if full and full.indicators:
                    # Pedigree entries such as "(1;2;4;1;3)" follow the
                    # indicator positions, so list them in that order
                    for ind in sorted(full.indicators,
                                      key=lambda i: i.position or 0):
                        indicators.append({
                            "position": ind.position,
                            "name": ind.name,
                            "scores": len(ind.scores) if ind.scores else 0,
                        })

                systems.append({
                    "id": desc.id,
                    "name": desc.name,
                    "indicator_count": indicator_count,
                    "indicators": indicators,
                })

            return {"dq_systems": systems, "count": len(systems)}

        except Exception as e:
            return {"error": str(e)}

    # ── listing / search ─────────────────────────────────────

    def list_product_systems(self, search_term: str = "") -> Dict:
        """List product systems, optionally those whose name contains
        search_term."""
        systems = self._get_descriptors(o.ProductSystem)
        if search_term:
            term = search_term.lower()
            systems = [s for s in systems if term in s.name.lower()]
        return {
            "count": len(systems),
            "systems": [{"id": s.id, "name": s.name} for s in systems],
        }

    def list_impact_methods(self, search_term: str = "") -> Dict:
        """List impact methods, optionally those whose name contains
        search_term."""
        methods = self._get_descriptors(o.ImpactMethod)
        if search_term:
            term = search_term.lower()
            methods = [m for m in methods if term in m.name.lower()]
        return {
            "count": len(methods),
            "methods": [{"id": m.id, "name": m.name} for m in methods],
        }

    def get_system_parameters(self, system_ref: str,
                              name_filter: str = "") -> Dict:
        """List parameters for a product system, with optional name filter."""
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}

        params = self.client.get_parameters(o.ProductSystem, system.id)
        result = []
        for p in params:
            if name_filter and name_filter.lower() not in p.name.lower():
                continue
            result.append({
                "name": p.name,
                "value": p.value,
                "context_id": p.context.id if p.context else None,
            })

        return {
            "system": system.name,
            "system_id": system.id,
            "count": len(result),
            "parameters": result,
        }

    def get_global_parameters(self, name_filter: str = "",
                              limit: int = 50) -> Dict:
        """
        Look up global (database-level) parameters.

        Returns name, value, scope, and formula for each match.
        Use name_filter to narrow results. Without a filter,
        results are capped at limit to avoid dumping thousands
        of parameters.
        """
        descriptors = self._get_descriptors(o.Parameter)
        if name_filter:
            term = name_filter.lower()
            descriptors = [d for d in descriptors if term in d.name.lower()]

        total = len(descriptors)
        descriptors = descriptors[:limit]

        results = []
        for desc in descriptors:
            param = self.client.get(o.Parameter, desc.id)
            if param:
                results.append({
                    "name": param.name,
                    "value": param.value,
                    "scope": str(param.parameter_scope) if param.parameter_scope else "",
                    "formula": param.formula or None,
                    "is_input": getattr(param, "is_input_parameter", True),
                })

        return {
            "count": len(results),
            "total_matches": total,
            "truncated": total > limit,
            "filter": name_filter or "(all)",
            "parameters": results,
        }

    def search_processes(self, search_term: str,
                         category_filter: str = "",
                         location_filter: str = "",
                         limit: int = 20,
                         with_location: bool = False) -> Dict:
        """Search processes by name, category, and/or location.

        location_filter matches the location code of the process (GB,
        RER, RoW) or, as before, text in its name. with_location=True
        adds each process's location code to the results."""
        # V06: Reject invalid limits
        MAX_SEARCH_LIMIT = 200
        if limit <= 0:
            return {
                "error": f"limit must be a positive integer (got {limit}). "
                         f"Use 1–{MAX_SEARCH_LIMIT}."
            }
        elif limit > MAX_SEARCH_LIMIT:
            limit = MAX_SEARCH_LIMIT

        processes = self._get_descriptors(o.Process)
        term = search_term.lower()
        cat = category_filter.lower() if category_filter else ""
        loc = location_filter.lower() if location_filter else ""
        all_matches = []
        for p in processes:
            if term and term not in p.name.lower():
                continue
            proc_cat = getattr(p, "category", "") or ""
            if cat and cat not in proc_cat.lower():
                continue
            # Location filter: the location code on the process, or the
            # location written into its name (older ecoinvent exports
            # do that, e.g. "| Cutoff, U - GB")
            proc_loc = getattr(p, "location", "") or ""
            if loc and loc != proc_loc.lower() and loc not in p.name.lower():
                continue
            match = {
                "id": p.id,
                "name": p.name,
                "category": proc_cat,
            }
            if with_location:
                match["location"] = proc_loc
            all_matches.append(match)

        truncated = len(all_matches) > limit

        return {
            "search_term": search_term,
            "category_filter": category_filter or "(all)",
            "count": min(len(all_matches), limit),
            "total_matches": len(all_matches),
            "truncated": truncated,
            "processes": all_matches[:limit],
        }

    def search_flows(self, search_term: str = "",
                     category_filter: str = "",
                     limit: int = 20) -> Dict:
        """Search flows by name and/or category folder."""
        # V06: Reject invalid limits
        MAX_SEARCH_LIMIT = 200
        if limit <= 0:
            return {
                "error": f"limit must be a positive integer (got {limit}). "
                         f"Use 1–{MAX_SEARCH_LIMIT}."
            }
        elif limit > MAX_SEARCH_LIMIT:
            limit = MAX_SEARCH_LIMIT

        flows = self._get_descriptors(o.Flow)
        matches = []
        term = search_term.lower() if search_term else ""
        cat = category_filter.lower() if category_filter else ""

        for f in flows:
            if term and term not in f.name.lower():
                continue
            flow_cat = getattr(f, "category", "") or ""
            if cat and cat not in flow_cat.lower():
                continue
            matches.append({
                "id": f.id,
                "name": f.name,
                "category": flow_cat,
                "flow_type": str(getattr(f, "flow_type", "")),
                "ref_unit": getattr(f, "ref_unit", ""),
            })
            if len(matches) >= limit:
                break

        return {
            "search_term": search_term or "(all)",
            "category_filter": category_filter or "(all)",
            "count": len(matches),
            "flows": matches,
        }

    def chemical_synonyms(self, chemical_name: str,
                          search_database: bool = True,
                          max_synonyms: int = 20) -> Dict:
        """
        Look up chemical synonyms via PubChem (US NIH, free, no key).

        Takes a chemical name (common name, trade name, or IUPAC),
        returns known synonyms, CAS number, and IUPAC name.
        If search_database is True, also searches the connected
        openLCA database for matches against each synonym.

        Only call this when the user has approved a deeper search,
        or when a basic search_processes call returned few results
        and the user said yes to trying synonyms.
        """
        try:
            encoded = urllib.parse.quote(chemical_name)
            url = (
                f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/"
                f"compound/name/{encoded}/synonyms/JSON"
            )

            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Below280-openLCA-MCP/1.0")

            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json_module.loads(resp.read().decode())

            synonyms_list = (
                data.get("InformationList", {})
                .get("Information", [{}])[0]
                .get("Synonym", [])
            )

            # Extract CAS number (format: digits-digits-digit)
            import re
            cas = None
            for s in synonyms_list:
                if re.match(r"^\d{2,7}-\d{2}-\d$", s):
                    cas = s
                    break

            # Take the most useful synonyms (skip catalog numbers)
            useful = []
            for s in synonyms_list:
                if len(s) > 80:
                    continue
                if any(c in s for c in [";", "  ", "\t"]):
                    continue
                useful.append(s)
                if len(useful) >= max_synonyms:
                    break

            result = {
                "query": chemical_name,
                "cas_number": cas,
                "iupac_name": useful[0] if useful else None,
                "synonym_count": len(synonyms_list),
                "synonyms": useful,
            }

            # Search the openLCA database for matches
            if search_database and useful:
                db_matches = []
                seen_ids = set()
                processes = self._get_descriptors(o.Process)

                for synonym in useful[:10]:
                    term = synonym.lower()
                    for p in processes:
                        if p.id in seen_ids:
                            continue
                        if term in p.name.lower():
                            db_matches.append({
                                "id": p.id,
                                "name": p.name,
                                "matched_synonym": synonym,
                                "category": getattr(p, "category", ""),
                            })
                            seen_ids.add(p.id)
                            if len(db_matches) >= 20:
                                break
                    if len(db_matches) >= 20:
                        break

                result["database_matches"] = db_matches
                result["database_match_count"] = len(db_matches)

            return result

        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {
                    "query": chemical_name,
                    "error": f"Chemical '{chemical_name}' not found in PubChem",
                    "suggestion": "Try a different name, CAS number, or IUPAC name",
                }
            return {"error": f"PubChem API error: {e.code} {e.reason}"}
        except Exception as e:
            return {"error": f"PubChem lookup failed: {e}"}

    def get_process_details(self, process_id: str) -> Dict:
        """Full process information including exchanges and parameters."""
        try:
            process = self.client.get(o.Process, process_id)
            if not process:
                return {"error": f"Process not found: {process_id}"}

            exchanges = []
            if process.exchanges:
                for ex in process.exchanges:
                    exchanges.append({
                        "flow": ex.flow.name if ex.flow else "Unknown",
                        "amount": ex.amount,
                        "formula": getattr(ex, "amount_formula", None),
                        "unit": ex.unit.name if ex.unit else "",
                        "is_input": ex.is_input,
                        "is_qref": getattr(ex, "is_quantitative_reference", False),
                        "provider": (ex.default_provider.name
                                     if getattr(ex, "default_provider", None)
                                     else None),
                    })

            parameters = []
            if process.parameters:
                for p in process.parameters:
                    parameters.append({
                        "name": p.name,
                        "value": p.value,
                        "formula": getattr(p, "formula", None),
                        "is_input": getattr(p, "is_input_parameter", True),
                    })

            location_name = ""
            if hasattr(process, "location") and process.location:
                location_name = getattr(process.location, "name", "")

            return {
                "id": process.id,
                "name": process.name,
                "category": getattr(process, "category", ""),
                "location": location_name,
                "description": getattr(process, "description", ""),
                "exchanges": exchanges,
                "parameters": parameters,
            }
        except Exception as e:
            return {"error": str(e)}

    def find_flow_usage(self, flow_id: str, max_hits: int = 10,
                        progress=None, prefer_categories=None,
                        workers: int = 8) -> Dict:
        """
        Find where a flow is used: by processes that produce it, in
        process exchanges, and (for elementary flows) in impact category
        characterisation factors.

        openLCA's IPC server has no 'where used' query (the desktop
        Usage view runs inside openLCA), so this reads processes. To keep
        it quick it (1) asks openLCA for the flow's providers first,
        (2) reads processes in prefer_categories (e.g. the user's own
        folders) before the rest, (3) reads several processes at once,
        and (4) stops as soon as max_hits uses are found. progress, if
        given, is called with (checked, total) as it goes.
        """
        import threading
        from concurrent.futures import ThreadPoolExecutor
        try:
            flow = self.client.get(o.Flow, flow_id)
            if flow is None:
                return {"error": f"Flow not found: {flow_id}"}
            used_by = []

            # 1. Any process producing the flow is a use, and openLCA
            #    can answer that directly
            try:
                for tf in self.client.get_providers(
                        o.Ref(id=flow_id, ref_type=o.RefType.Flow)) or []:
                    if tf.provider and tf.provider.name not in used_by:
                        used_by.append(tf.provider.name)
            except Exception:
                pass

            others = []     # EPDs and stored results that use the flow

            def result(methods, checked, total):
                out = {
                    "flow_id": flow_id, "flow_name": flow.name,
                    "used_by_processes": used_by[:max_hits],
                    "used_in_impact_categories": methods,
                    "in_use": bool(used_by or methods or others),
                    "complete": len(used_by) + len(methods) < max_hits,
                    "processes_checked": checked, "processes_total": total,
                }
                if others:
                    out["used_elsewhere"] = others
                return out

            descs = list(self.client.get_descriptors(o.Process))
            if len(used_by) >= max_hits:
                return result([], 0, len(descs))

            # 2. The user's own folders first
            prefer = [c.lower().rstrip("/") for c in (prefer_categories or []) if c]

            def preferred(d):
                cat = (getattr(d, "category", "") or "").lower()
                return any(cat == c or cat.startswith(c + "/") for c in prefer)
            descs.sort(key=lambda d: 0 if preferred(d) else 1)

            # 3. Several reads at once, one client per worker thread
            #    (the IPC client isn't thread-safe; the server is)
            url = getattr(self.client, "url", None)
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
                    # A process that can't be read can't be ruled out
                    raise RuntimeError(
                        f"could not read process '{d.name}' ({d.id}), so "
                        f"the search for uses of the flow is incomplete")
                return any(
                    ex.flow and ex.flow.id == flow_id
                    for ex in (proc.exchanges or []))

            checked = 0
            batch = max(workers * 25, 50)
            n_workers = workers if url is not None else 1
            with ThreadPoolExecutor(max_workers=n_workers) as pool:
                for i in range(0, len(descs), batch):
                    chunk = descs[i:i + batch]
                    for d, hit in zip(chunk, pool.map(uses, chunk)):
                        if hit and d.name not in used_by:
                            used_by.append(d.name)
                    checked += len(chunk)
                    if progress:
                        progress(checked, len(descs))
                    # 4. Stop once enough uses are found
                    if len(used_by) >= max_hits:
                        return result([], checked, len(descs))

            # EPD datasets and stored results also point at flows
            for otype, label in ((getattr(o, "Epd", None), "EPD"),
                                 (getattr(o, "Result", None), "result")):
                if otype is None:
                    continue
                try:
                    descs_other = list(self.client.get_descriptors(otype))
                except Exception:
                    descs_other = []
                for d in descs_other:
                    entity = self.client.get(otype, d.id)
                    if entity is None:
                        continue
                    refs = []
                    product = getattr(entity, "product", None)
                    if product is not None and getattr(product, "flow", None):
                        refs.append(product.flow.id)
                    for fr in getattr(entity, "flow_results", None) or []:
                        if fr.flow:
                            refs.append(fr.flow.id)
                    if flow_id in refs:
                        others.append(f"{d.name} ({label})")

            methods = []
            if flow.flow_type == o.FlowType.ELEMENTARY_FLOW:
                for d in self.client.get_descriptors(o.ImpactCategory):
                    cat = self.client.get(o.ImpactCategory, d.id)
                    if cat and any(f.flow and f.flow.id == flow_id
                                   for f in (cat.impact_factors or [])):
                        methods.append(d.name)
                        if len(used_by) + len(methods) >= max_hits:
                            break
            return result(methods, checked, len(descs))
        except Exception as ex:
            return {"error": str(ex)}

    # ── process metadata (tags and documentation) ────────────

    def get_process_tags(self, process_id: str, prefix: str = "") -> Dict:
        """The tags of a process that have the form 'key=value' (and,
        if prefix is given, start with 'prefix:'), as {key: value}.
        Returns {"error": ...} if the process cannot be read."""
        try:
            process = self.client.get(o.Process, process_id)
            if not process:
                return {"error": f"Process not found: {process_id}"}
            out = {}
            lead = f"{prefix}:" if prefix else ""
            for tag in process.tags or []:
                if lead and not tag.startswith(lead):
                    continue
                key, sep, value = tag[len(lead):].partition("=")
                if sep:
                    out[key] = value
            return {"process_id": process.id, "process_name": process.name,
                    "category": getattr(process, "category", "") or "",
                    "description": getattr(process, "description", "") or "",
                    "tags": out}
        except Exception as ex:
            return {"error": str(ex)}

    def process_structure(self, process_id: str) -> Dict:
        """How a process is wired, from one read: its reference
        exchange, its technosphere inputs with their providers, its
        local parameters, its tags and what documentation it carries.

        Returns {"id", "name", "category", "description", "tags",
        "qref": {"flow_id", "flow", "amount", "formula", "unit",
        "is_input"} or None, "links": [{"flow_id", "flow", "amount",
        "formula", "unit", "is_input", "provider_id", "provider"}],
        "parameters": {name: value}, "exchange_count",
        "exchanges_without_pedigree", "has_dq_entry", "valid_from",
        "valid_until"}. links holds every exchange that has a default
        provider (inputs, and waste outputs sent to treatment)."""
        try:
            process = self.client.get(o.Process, process_id)
            if not process:
                return {"error": f"Process not found: {process_id}"}
            qref, links, no_pedigree, count = None, [], 0, 0
            for ex in process.exchanges or []:
                count += 1
                row = {
                    "flow_id": ex.flow.id if ex.flow else None,
                    "flow": ex.flow.name if ex.flow else "",
                    "amount": ex.amount,
                    "formula": getattr(ex, "amount_formula", None),
                    "unit": ex.unit.name if ex.unit else "",
                    "is_input": bool(ex.is_input),
                }
                if getattr(ex, "is_quantitative_reference", False):
                    qref = row
                    continue
                if not getattr(ex, "dq_entry", None):
                    no_pedigree += 1
                provider = getattr(ex, "default_provider", None)
                if provider is not None:
                    row["provider_id"] = provider.id
                    row["provider"] = provider.name or ""
                    links.append(row)
            doc = getattr(process, "process_documentation", None)
            return {
                "id": process.id, "name": process.name,
                "category": getattr(process, "category", "") or "",
                "description": getattr(process, "description", "") or "",
                "tags": list(process.tags or []),
                "qref": qref, "links": links,
                "parameters": {p.name: p.value
                               for p in process.parameters or []},
                "exchange_count": count,
                "exchanges_without_pedigree": no_pedigree,
                "has_dq_entry": bool(getattr(process, "dq_entry", None)),
                "valid_from": getattr(doc, "valid_from", None) if doc else None,
                "valid_until": getattr(doc, "valid_until", None) if doc else None,
            }
        except Exception as ex:
            return {"error": str(ex)}

    def get_method_categories(self, method_ref: str) -> Dict:
        """The impact categories of a method, in the method's order:
        {"method", "method_id", "count", "categories": [{"id", "name",
        "unit"}]}. method_ref is a UUID or the full name."""
        found = self.find_method_strict(method_ref)
        if "error" in found:
            return found
        try:
            method = self.client.get(o.ImpactMethod, found["id"])
            cats = []
            for ref in (method.impact_categories or []) if method else []:
                cats.append({"id": ref.id, "name": ref.name,
                             "unit": getattr(ref, "ref_unit", "") or ""})
            return {"method": found["name"], "method_id": found["id"],
                    "count": len(cats), "categories": cats}
        except Exception as ex:
            return {"error": str(ex)}

    def _extract_links(self, system) -> List[Dict]:
        """Extract process links from a product system."""
        links = []
        process_links = getattr(system, "process_links", None)
        if not process_links:
            return links
        for link in process_links:
            provider = getattr(link, "provider", None)
            flow = getattr(link, "flow", None)
            receiving = getattr(link, "process", None)
            links.append({
                "provider_id": provider.id if provider else None,
                "provider_name": getattr(provider, "name", None) if provider else None,
                "flow_id": flow.id if flow else None,
                "flow_name": getattr(flow, "name", None) if flow else None,
                "receiving_process_id": receiving.id if receiving else None,
                "receiving_process_name": getattr(receiving, "name", None) if receiving else None,
            })
        return links

    def get_system_links(self, system_ref: str,
                          search_term: str = "",
                          limit: int = 50) -> Dict:
        """
        Show which providers are linked to which exchanges in a
        product system. Use search_term to filter by flow or
        provider name (e.g. 'electricity', 'sodium hydroxide').

        Without a filter on large systems, results will be generic
        background links. Always filter when looking for a specific
        connection.
        """
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}

        try:
            full_system = self.client.get(o.ProductSystem, system.id)
            if not full_system:
                return {"error": "Could not load product system details"}

            links = self._extract_links(full_system)

            # Filter by search term if provided
            if search_term:
                term = search_term.lower()
                links = [
                    lnk for lnk in links
                    if (term in (lnk.get("flow_name") or "").lower()
                        or term in (lnk.get("provider_name") or "").lower()
                        or term in (lnk.get("receiving_process_name") or "").lower())
                ]

            total = len(links)

            return {
                "system": system.name,
                "system_id": system.id,
                "search_term": search_term or "(all)",
                "link_count": min(total, limit),
                "total_matching": total,
                "truncated": total > limit,
                "links": links[:limit],
            }
        except Exception as e:
            error_str = str(e).lower()
            if "connection" in error_str or "closed" in error_str:
                return {
                    "error": (
                        f"System too large to load via IPC. This happens "
                        f"with systems backed by large background databases "
                        f"where the full product system exceeds the IPC "
                        f"transfer limit. Use contribution_analysis to "
                        f"identify providers, or check the graph view in "
                        f"openLCA directly."
                    ),
                }
            return {"error": str(e)}

    def get_data_quality(self, process_id: str) -> Dict:
        """
        Extract pedigree matrix / data quality entries for a process
        and all its exchanges.

        Pedigree format: '(R;C;T;G;F)' where:
          R = Reliability
          C = Completeness
          T = Temporal correlation
          G = Geographical correlation
          F = Further technological correlation
        Values 1-5, lower is better.
        """
        DQ_LABELS = [
            "Reliability", "Completeness", "Temporal correlation",
            "Geographical correlation", "Further technological correlation",
        ]

        def parse_pedigree(entry):
            if not entry:
                return None
            values = entry.strip("()").split(";")
            parsed = {}
            for i, v in enumerate(values):
                label = DQ_LABELS[i] if i < len(DQ_LABELS) else f"Indicator {i+1}"
                try:
                    parsed[label] = int(v.strip())
                except (ValueError, TypeError):
                    parsed[label] = v.strip()
            return parsed

        try:
            process = self.client.get(o.Process, process_id)
            if not process:
                return {"error": f"Process not found: {process_id}"}

            # Process-level DQ
            result = {
                "process_id": process.id,
                "process_name": process.name,
                "process_dq_system": (
                    process.dq_system.name
                    if getattr(process, "dq_system", None) else None),
                "exchange_dq_system": (
                    process.exchange_dq_system.name
                    if getattr(process, "exchange_dq_system", None) else None),
                "process_dq_entry": getattr(process, "dq_entry", None),
                "process_dq_parsed": parse_pedigree(
                    getattr(process, "dq_entry", None)),
            }

            # Exchange-level DQ
            exchanges_dq = []
            if process.exchanges:
                for ex in process.exchanges:
                    dq_entry = getattr(ex, "dq_entry", None)
                    if dq_entry or getattr(ex, "base_uncertainty", None):
                        exchanges_dq.append({
                            "flow": ex.flow.name if ex.flow else "?",
                            "is_input": ex.is_input,
                            "amount": ex.amount,
                            "unit": ex.unit.name if ex.unit else "",
                            "dq_entry": dq_entry,
                            "dq_parsed": parse_pedigree(dq_entry),
                            "base_uncertainty": getattr(
                                ex, "base_uncertainty", None),
                            "uncertainty_type": (
                                str(ex.uncertainty.distribution_type)
                                if getattr(ex, "uncertainty", None) else None),
                        })

            result["exchanges_with_dq"] = exchanges_dq
            result["exchanges_dq_count"] = len(exchanges_dq)
            result["total_exchanges"] = (
                len(process.exchanges) if process.exchanges else 0)

            return result

        except Exception as e:
            return {"error": str(e)}
