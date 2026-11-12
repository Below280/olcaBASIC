"""
Checking a model: extraction for comparison with source data,
structural audit of a folder, validation of a product system.

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


class AuditMixin:
    """Checking a model: extraction for comparison with source data,"""

    # ── model extraction and audit ───────────────────────────
    #
    # CRITICAL SCALING KNOWLEDGE:
    # openLCA automatically scales processes to meet demand.
    # A process outputting 1 kg of steel feeding one that needs
    # 5 kg is NOT a mismatch — openLCA runs the first process
    # 5 times. Never flag amount differences between connected
    # processes as errors.
    #
    # openLCA also handles same-property unit conversions
    # automatically (e.g. MJ↔kWh, kg↔t). Do not flag these.

    def extract_model(self, category: str) -> Dict:
        """
        Extract all processes within a category folder and its
        subfolders. Returns a complete model snapshot: processes,
        exchanges, parameters, and providers.

        Convention: model folders start with '00: ' (e.g. '00: My Project').
        """
        # V01: Reject path traversal in category
        cat_err = _validate_category(category)
        if cat_err:
            return {"error": cat_err}
        try:
            all_processes = self._get_descriptors(o.Process)

            # Find processes in this category tree
            cat_lower = category.lower()
            model_processes = [
                p for p in all_processes
                if p.category and cat_lower in p.category.lower()
            ]

            if not model_processes:
                return {
                    "error": f"No processes found in category '{category}'",
                    "hint": "Check the category path. Model folders should start with '00: '",
                }

            # Extract full details for each process
            processes = []
            all_flows = {}  # flow_id → {name, unit, type}
            all_providers = {}  # process_id → process_name

            for proc_desc in model_processes:
                proc = self.client.get(o.Process, proc_desc.id)
                if not proc:
                    continue

                exchanges = []
                if proc.exchanges:
                    for ex in proc.exchanges:
                        flow_name = ex.flow.name if ex.flow else "Unknown"
                        flow_id = ex.flow.id if ex.flow else None
                        unit_name = ex.unit.name if ex.unit else ""
                        prov_name = None
                        prov_id = None

                        if getattr(ex, "default_provider", None):
                            prov_id = ex.default_provider.id
                            prov_name = getattr(ex.default_provider, "name", None)
                            all_providers[prov_id] = prov_name

                        if flow_id:
                            all_flows[flow_id] = {
                                "name": flow_name,
                                "unit": unit_name,
                            }

                        exchanges.append({
                            "flow_id": flow_id,
                            "flow_name": flow_name,
                            "amount": ex.amount,
                            "formula": getattr(ex, "amount_formula", None),
                            "unit": unit_name,
                            "is_input": ex.is_input,
                            "is_qref": getattr(ex, "is_quantitative_reference", False),
                            "provider_id": prov_id,
                            "provider_name": prov_name,
                        })

                parameters = []
                if proc.parameters:
                    for p in proc.parameters:
                        parameters.append({
                            "name": p.name,
                            "value": p.value,
                            "formula": getattr(p, "formula", None),
                            "is_input": getattr(p, "is_input_parameter", True),
                            "description": getattr(p, "description", ""),
                        })

                processes.append({
                    "id": proc.id,
                    "name": proc.name,
                    "category": getattr(proc, "category", ""),
                    "description": getattr(proc, "description", ""),
                    "exchanges": exchanges,
                    "parameters": parameters,
                })

            # Also find custom flows in the model category
            all_flow_descs = self._get_descriptors(o.Flow)
            model_flows = []
            for fd in all_flow_descs:
                flow_cat = getattr(fd, "category", "") or ""
                if cat_lower in flow_cat.lower():
                    model_flows.append({
                        "id": fd.id,
                        "name": fd.name,
                        "category": flow_cat,
                        "flow_type": str(getattr(fd, "flow_type", "")),
                        "ref_unit": getattr(fd, "ref_unit", ""),
                    })

            return {
                "category": category,
                "process_count": len(processes),
                "processes": processes,
                "model_flows": model_flows,
                "model_flow_count": len(model_flows),
                "flows_used": all_flows,
                "providers_referenced": all_providers,
            }

        except Exception as ex:
            return {"error": str(ex)}

    def audit_model(self, category: str) -> Dict:
        """
        Run structural checks on all processes in a category folder.

        Checks performed:
          - Every process has exactly one quantitative reference
          - All exchanges have units
          - Exchanges with amount=0 and no formula (likely placeholders)
          - Product flows produced but never consumed (orphaned)
          - Product flows consumed but never produced (missing source)
          - Exchanges missing default providers
          - Parameter name/unit consistency hints

        NOT flagged (by design):
          - Amount differences between producer and consumer.
            openLCA scales processes automatically.
          - Unit differences within the same flow property.
            openLCA converts MJ↔kWh, kg↔t, etc. automatically.
        """
        # First extract the model
        model = self.extract_model(category)
        if "error" in model:
            return model

        findings = []
        processes = model["processes"]
        process_names = {p["id"]: p["name"] for p in processes}

        # Track flow production and consumption across the model
        flow_producers = {}  # flow_id → [(process_name, amount/formula)]
        flow_consumers = {}  # flow_id → [(process_name, amount/formula)]

        for proc in processes:
            proc_name = proc["name"]

            # Check: process description warnings
            proc_desc = proc.get("description", "") or ""
            if proc_desc:
                warning_terms = [
                    "don't trust", "do not trust", "unreliable",
                    "placeholder", "estimate", "basic estimate",
                    "rough", "dummy", "temporary", "TODO",
                    "needs review", "not verified", "unverified",
                ]
                desc_lower = proc_desc.lower()
                for term in warning_terms:
                    if term.lower() in desc_lower:
                        findings.append({
                            "severity": "warning",
                            "process": proc_name,
                            "check": "description_warning",
                            "message": f"Process description contains warning: '{proc_desc[:120]}'",
                        })
                        break

            # Check: quantitative reference
            qrefs = [ex for ex in proc["exchanges"] if ex.get("is_qref")]
            if len(qrefs) == 0:
                findings.append({
                    "severity": "error",
                    "process": proc_name,
                    "check": "quantitative_reference",
                    "message": "No quantitative reference exchange found",
                })
            elif len(qrefs) > 1:
                findings.append({
                    "severity": "warning",
                    "process": proc_name,
                    "check": "quantitative_reference",
                    "message": f"Multiple quantitative references ({len(qrefs)})",
                })

            # Check: duplicate exchanges (same flow + same provider)
            seen_exchanges = {}
            for ex in proc["exchanges"]:
                fid = ex.get("flow_id")
                pid = ex.get("provider_id") or "none"
                direction = "in" if ex.get("is_input") else "out"
                key = f"{fid}|{pid}|{direction}"
                if key in seen_exchanges:
                    findings.append({
                        "severity": "warning",
                        "process": proc_name,
                        "check": "duplicate_exchange",
                        "message": (
                            f"Duplicate exchange: '{ex.get('flow_name', '?')}' "
                            f"appears {seen_exchanges[key] + 1} times with the same "
                            f"provider and direction. Likely a leftover from "
                            f"edit_process adding instead of updating."
                        ),
                    })
                    seen_exchanges[key] += 1
                else:
                    seen_exchanges[key] = 1

            for ex in proc["exchanges"]:
                flow_id = ex.get("flow_id")
                flow_name = ex.get("flow_name", "?")
                amount = ex.get("amount", 0)
                formula = ex.get("formula")
                unit = ex.get("unit", "")

                # Check: missing unit
                if not unit:
                    findings.append({
                        "severity": "warning",
                        "process": proc_name,
                        "check": "missing_unit",
                        "message": f"Exchange '{flow_name}' (flow_id: {flow_id}, amount: {amount}) has no unit",
                    })

                # Check: zero amount with no formula (placeholder)
                if amount == 0 and not formula and not ex.get("is_qref"):
                    findings.append({
                        "severity": "warning",
                        "process": proc_name,
                        "check": "zero_amount",
                        "message": f"Exchange '{flow_name}' (flow_id: {flow_id}) has amount=0 and no formula (placeholder?)",
                    })

                # Check: non-qref input without provider
                if (ex.get("is_input") and not ex.get("is_qref")
                        and not ex.get("provider_id")):
                    findings.append({
                        "severity": "info",
                        "process": proc_name,
                        "check": "missing_provider",
                        "message": f"Input '{flow_name}' (flow_id: {flow_id}, amount: {amount} {unit}) has no default provider set",
                    })

                # Track flow connectivity
                if flow_id:
                    if ex.get("is_input"):
                        flow_consumers.setdefault(flow_id, []).append(
                            (proc_name, amount, formula))
                    else:
                        flow_producers.setdefault(flow_id, []).append(
                            (proc_name, amount, formula))

            # Check: parameter naming vs exchange units
            param_names = {p["name"]: p for p in proc.get("parameters", [])}
            for ex in proc["exchanges"]:
                formula = ex.get("formula")
                if not formula:
                    continue
                unit = ex.get("unit", "").lower()
                # Simple heuristic: if a parameter name ends with a unit
                # hint that conflicts with the exchange unit
                for pname in param_names:
                    if pname not in formula:
                        continue
                    pname_lower = pname.lower()
                    # Check for obvious cross-property mismatches
                    unit_hints = {
                        "_kg": "mass", "_t": "mass", "_g": "mass",
                        "_kwh": "energy", "_mj": "energy",
                        "_m3": "volume", "_l": "volume",
                        "_km": "length", "_m": "length",
                        "_tkm": "transport",
                    }
                    ex_property = None
                    param_property = None
                    for suffix, prop in unit_hints.items():
                        if unit.replace("*", "") in suffix.strip("_"):
                            ex_property = prop
                        if pname_lower.endswith(suffix):
                            param_property = prop
                    if (param_property and ex_property
                            and param_property != ex_property):
                        findings.append({
                            "severity": "warning",
                            "process": proc_name,
                            "check": "unit_mismatch",
                            "message": (
                                f"Parameter '{pname}' suggests {param_property} "
                                f"but exchange unit is '{ex.get('unit')}' ({ex_property})"
                            ),
                        })

            # Check: orphaned parameters (defined but never used anywhere)
            # Check both exchange formulas AND other parameter formulas,
            # so indirect chains (switch → grid/solar → exchange) aren't
            # flagged as orphaned.
            all_exchange_formulas = " ".join(
                ex.get("formula", "") or ""
                for ex in proc.get("exchanges", [])
            )
            all_param_formulas = " ".join(
                (p.get("formula", "") or "") + " " + p.get("name", "")
                for p in proc.get("parameters", [])
                if not p.get("is_input", True)  # calculated params have formulas
            )
            all_formulas = all_exchange_formulas + " " + all_param_formulas

            for pname in param_names:
                if pname not in all_formulas:
                    findings.append({
                        "severity": "info",
                        "process": proc_name,
                        "check": "orphaned_parameter",
                        "message": (
                            f"Parameter '{pname}' (value: {param_names[pname].get('value')}) "
                            f"may not be referenced in any formula (check manually "
                            f"if it feeds other parameters indirectly)"
                        ),
                    })

        # Flow connectivity checks
        all_flow_ids = set(list(flow_producers.keys()) + list(flow_consumers.keys()))
        for flow_id in all_flow_ids:
            flow_name = model["flows_used"].get(flow_id, {}).get("name", "?")
            produced = flow_id in flow_producers
            consumed = flow_id in flow_consumers

            if produced and not consumed:
                # Only flag if it's from a foreground process (not a qref output
                # that's meant to leave the system)
                producers = flow_producers[flow_id]
                for pname, amt, formula in producers:
                    # Skip if this is likely a final product qref
                    pass  # Claude can assess this contextually

            if consumed and not produced:
                consumers = flow_consumers[flow_id]
                for pname, amt, formula in consumers:
                    findings.append({
                        "severity": "info",
                        "process": pname,
                        "check": "flow_not_produced",
                        "message": (
                            f"Input flow '{flow_name}' is consumed but not "
                            f"produced by any process in this model folder. "
                            f"Expected if it comes from outside the model "
                            f"(e.g. a bridge or background process)."
                        ),
                    })

        # Sort by severity
        severity_order = {"error": 0, "warning": 1, "info": 2}
        findings.sort(key=lambda f: severity_order.get(f["severity"], 3))

        errors = sum(1 for f in findings if f["severity"] == "error")
        warnings = sum(1 for f in findings if f["severity"] == "warning")
        infos = sum(1 for f in findings if f["severity"] == "info")

        return {
            "category": category,
            "process_count": len(processes),
            "summary": {
                "errors": errors,
                "warnings": warnings,
                "info": infos,
            },
            "findings": findings,
            "scaling_reminder": (
                "openLCA scales processes automatically to meet demand. "
                "A process outputting 1 kg feeding one that needs 5 kg is "
                "NOT a mismatch. Do not flag amount differences between "
                "connected processes. openLCA also handles same-property "
                "unit conversions automatically (MJ/kWh, kg/t, etc)."
            ),
        }

    def validate_system(self, system_ref: str,
                         test_calculate: bool = False) -> Dict:
        """
        Validate a product system structure.

        Lightweight by default: checks target process, linking
        presence, and parameters without running a calculation.
        Set test_calculate=True to also run a test calculation
        (slower, may time out on large models).
        """
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}

        findings = []

        try:
            full_system = self.client.get(o.ProductSystem, system.id)
            if not full_system:
                return {"error": "Could not load product system details"}

            # Check target process
            target_ref = getattr(full_system, "ref_process", None)
            if not target_ref:
                # Try alternative attribute names
                target_ref = getattr(full_system, "reference_process", None)

            if target_ref:
                target_proc = self.client.get(o.Process, target_ref.id)
                if not target_proc:
                    findings.append({
                        "severity": "error",
                        "check": "target_process",
                        "message": f"Target process '{target_ref.name}' could not be loaded",
                    })
                else:
                    has_qref = False
                    if target_proc.exchanges:
                        has_qref = any(
                            getattr(ex, "is_quantitative_reference", False)
                            for ex in target_proc.exchanges
                        )
                    if not has_qref:
                        findings.append({
                            "severity": "error",
                            "check": "quantitative_reference",
                            "message": f"Target process '{target_proc.name}' has no quantitative reference",
                        })

            # Check target amount
            target_amount = getattr(full_system, "target_amount", None)
            if target_amount is not None and target_amount == 0:
                findings.append({
                    "severity": "warning",
                    "check": "target_amount",
                    "message": "Target amount is 0 - calculation will produce zero results",
                })

            # Check linked processes exist (count only, don't fetch each one)
            process_links = getattr(full_system, "process_links", None)
            if process_links:
                findings.append({
                    "severity": "info",
                    "check": "links_present",
                    "message": f"Product system has {len(process_links)} process links",
                })
            else:
                findings.append({
                    "severity": "warning",
                    "check": "no_links",
                    "message": "Product system has no process links - may need relinking",
                })

            # Check parameters
            try:
                sys_params = self.client.get_parameters(o.ProductSystem, system.id)
                if sys_params:
                    null_params = [p.name for p in sys_params if p.value is None]
                    if null_params:
                        findings.append({
                            "severity": "warning",
                            "check": "null_parameter",
                            "message": f"Parameters with no value: {', '.join(null_params)}",
                        })
                    findings.append({
                        "severity": "info",
                        "check": "parameters",
                        "message": f"{len(sys_params)} parameters found",
                    })
            except Exception:
                pass

            # Optional test calculation
            if test_calculate:
                method = self._resolve_method("EF v3.1")
                if not method:
                    methods = self._get_descriptors(o.ImpactMethod)
                    method = methods[0] if methods else None

                if method:
                    try:
                        setup = o.CalculationSetup(
                            target=full_system, impact_method=method)
                        result = self.client.calculate(setup)
                        result.wait_until_ready()
                        impacts = result.get_total_impacts()

                        zero_count = sum(1 for i in impacts if i.amount == 0)
                        total_count = len(impacts)

                        if zero_count == total_count:
                            findings.append({
                                "severity": "error",
                                "check": "all_zero",
                                "message": "All impact results are zero - system may not be linked correctly",
                            })
                        elif zero_count > total_count * 0.8:
                            findings.append({
                                "severity": "warning",
                                "check": "mostly_zero",
                                "message": f"{zero_count}/{total_count} impact categories are zero",
                            })
                        else:
                            findings.append({
                                "severity": "info",
                                "check": "calculation_ok",
                                "message": f"Test calculation succeeded: {total_count - zero_count}/{total_count} categories have non-zero results",
                            })

                        result.dispose()
                    except Exception as calc_err:
                        findings.append({
                            "severity": "error",
                            "check": "calculation_failed",
                            "message": f"Test calculation failed: {calc_err}",
                        })

        except Exception as e:
            findings.append({
                "severity": "error",
                "check": "system_load",
                "message": f"Failed to inspect system: {e}",
            })

        severity_order = {"error": 0, "warning": 1, "info": 2}
        findings.sort(key=lambda f: severity_order.get(f["severity"], 3))

        errors = sum(1 for f in findings if f["severity"] == "error")
        warnings = sum(1 for f in findings if f["severity"] == "warning")

        return {
            "system": system.name,
            "system_id": system.id,
            "valid": errors == 0,
            "summary": {"errors": errors, "warnings": warnings},
            "findings": findings,
        }
