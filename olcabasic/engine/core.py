"""
The connection, the descriptor cache, name resolution, the database
family and its units, and the parameter look-up that calculations
share.

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


def _checked(client):
    """The client, with put() made to fail loudly. olca-ipc logs a
    refused save and returns None, so a program would carry on as if
    the entity had been written. Here a refused save raises, and the
    engine reports it as the error of the command that asked for it."""
    put = getattr(client, "put", None)
    if put is None or getattr(put, "_olcabasic_checked", False):
        return client

    def checked_put(entity, *args, **kwargs):
        ref = put(entity, *args, **kwargs)
        if ref is None:
            kind = type(entity).__name__
            name = getattr(entity, "name", None) or getattr(entity, "id", "")
            raise RuntimeError(
                f"openLCA did not save the {kind} '{name}'. Nothing was "
                f"changed. openLCA's own log (Help, Open log file) says "
                f"why.")
        return ref

    checked_put._olcabasic_checked = True
    try:
        client.put = checked_put
    except Exception:
        pass
    return client


class CoreMixin:
    """The connection, the descriptor cache, name resolution, the database"""

    def __init__(self, client: Client):
        self.client = _checked(client)
        self._cache: Dict[str, Any] = {}
        self._cache_ts: Dict[str, float] = {}
        self._cache_ttl: float = 1800  # 30 minutes
        self._system_lock = threading.Lock()  # serialise product system creation

    # ── public helpers used by the language ──────────────────

    def get_descriptors(self, entity_type):
        """Descriptors (id, name, category and so on) of every entity of
        one olca_schema type. Cached for 30 minutes; clear_caches() or
        any engine write to that type refreshes it."""
        return self._get_descriptors(entity_type)

    def find_process(self, ref: str):
        """Descriptor of the process with this UUID or exact name, or
        the single process whose name contains it. None otherwise."""
        return self._resolve_process(ref)

    def find_system(self, ref: str):
        """Descriptor of a product system by UUID, name or unique part
        of a name. None otherwise."""
        return self._resolve_system(ref)

    def find_method(self, ref: str):
        """Descriptor of an impact method by UUID, name or unique part
        of a name. None otherwise."""
        return self._resolve_method(ref)

    def clear_caches(self):
        """Forget cached descriptor lists so the next call reads them
        from openLCA again."""
        self._cache.clear()
        self._cache_ts.clear()

    def cache_size(self) -> int:
        """Number of cached entries (descriptor lists and unit lookups)."""
        return len(self._cache)

    @property
    def database_family(self) -> str:
        """'ecoinvent', 'flcac' or 'unknown' (detected on first use, or
        set with set_database_family)."""
        return self._detect_database_family()

    # ── helpers ──────────────────────────────────────────────

    def _get_descriptors(self, entity_type):
        """Cached descriptor fetch. Per-key expiry, refreshes every 30 minutes."""
        key = entity_type.__name__
        now = time.time()
        if key in self._cache and (now - self._cache_ts.get(key, 0)) < self._cache_ttl:
            return self._cache[key]
        descriptors = list(self.client.get_descriptors(entity_type))
        self._cache[key] = descriptors
        self._cache_ts[key] = now
        return descriptors

    def _resolve(self, entity_type, ref: str):
        """Find a descriptor by ID, exact name, or unique partial name match."""
        items = self._get_descriptors(entity_type)
        for item in items:
            if item.id == ref:
                return item
        for item in items:
            if item.name == ref:
                return item
        matches = [item for item in items if ref.lower() in item.name.lower()]
        return matches[0] if len(matches) == 1 else None

    def _resolve_system(self, ref: str):
        """Find a product system by ID or name. Returns descriptor or None."""
        return self._resolve(o.ProductSystem, ref)

    def _resolve_method(self, ref: str):
        """Find an impact method by ID or name. Returns descriptor or None."""
        return self._resolve(o.ImpactMethod, ref)

    def _resolve_process(self, ref: str):
        """Find a process by ID or name. Returns descriptor or None."""
        return self._resolve(o.Process, ref)

    # Allocation method mapping — keys are the accepted string values
    # from the tool parameter; values are olca_schema enum members.
    ALLOCATION_TYPES = {
        "as_defined":  o.AllocationType.USE_DEFAULT_ALLOCATION,
        "physical":    o.AllocationType.PHYSICAL_ALLOCATION,
        "economic":    o.AllocationType.ECONOMIC_ALLOCATION,
        "causal":      o.AllocationType.CAUSAL_ALLOCATION,
        "none":        o.AllocationType.NO_ALLOCATION,
    }

    def _resolve_allocation(self, value: Optional[str] = None) -> o.AllocationType:
        """Map an allocation parameter string to an olca AllocationType.

        Returns USE_DEFAULT_ALLOCATION when *value* is None or omitted,
        matching the openLCA GUI default ("As defined in processes").
        """
        if value is None:
            return o.AllocationType.USE_DEFAULT_ALLOCATION
        key = value.strip().lower()
        alloc = self.ALLOCATION_TYPES.get(key)
        if alloc is None:
            valid = ", ".join(sorted(self.ALLOCATION_TYPES.keys()))
            raise ValueError(
                f"Unknown allocation method '{value}'. "
                f"Valid options: {valid}"
            )
        return alloc

    def _impacts_to_list(self, impacts) -> List[Dict]:
        """Convert impact results to JSON-serialisable list."""
        return [{
            "category": i.impact_category.name,
            "amount": i.amount,
            "unit": getattr(i.impact_category, "ref_unit", ""),
            "category_id": i.impact_category.id,
        } for i in impacts]

    # ── model building ───────────────────────────────────────
    #
    # Patterns lifted directly from create_east_bros_model.py:
    #   make_flow  → create_flow
    #   e()        → _build_exchange
    #   proc()     → create_process
    #   bridge_proc() → create_bridge
    #   get_unit / get_fp → find_unit

    # ── database family detection and unit mapping ─────────────
    #
    # Two database families with different flow property names:
    #   ecoinvent family: ecoinvent, EN15804GD, HiQLCD, BAFU
    #   FLCAC family: LCA Commons, US LCI, USEEIO
    #
    # Auto-detected on first use by checking telltale FP names.

    ECOINVENT_FP_MAP = {
        "kg": "Mass", "g": "Mass", "t": "Mass",
        "mg": "Mass", "lb av": "Mass", "oz av": "Mass",
        "sh tn": "Mass", "long tn": "Mass",
        "kWh": "Energy", "MJ": "Energy", "GJ": "Energy",
        "kJ": "Energy", "J": "Energy", "Wh": "Energy",
        "MWh": "Energy", "btu": "Energy",
        "t*km": "Mass transport", "tkm": "Mass transport",
        "kg*km": "Mass transport", "t*mi": "Mass transport",
        "t*nmi": "Mass transport",
        "p*km": "Person transport", "p*mi": "Person transport",
        "m3": "Volume", "l": "Volume", "ml": "Volume",
        "cm3": "Volume", "dm3": "Volume",
        "m2": "Area", "km2": "Area", "ha": "Area", "ft2": "Area",
        "h": "Time", "min": "Time", "s": "Time",
        "d": "Time", "a": "Time", "hr": "Time",
        "km": "Length", "m": "Length", "cm": "Length",
        "mm": "Length", "mi": "Length", "ft": "Length",
        "in": "Length", "nmi": "Length",
        "Item(s)": "Number of items",
    }

    FLCAC_FP_MAP = {
        "kg": "Mass", "g": "Mass", "t": "Mass",
        "mg": "Mass", "lb av": "Mass", "oz av": "Mass",
        "sh tn": "Mass", "long tn": "Mass",
        "kWh": "Energy", "MJ": "Energy", "GJ": "Energy",
        "kJ": "Energy", "J": "Energy", "Wh": "Energy",
        "MWh": "Energy", "btu": "Energy",
        "t*km": "Goods transport (mass*distance)",
        "tkm": "Goods transport (mass*distance)",
        "kg*km": "Goods transport (mass*distance)",
        "t*mi": "Goods transport (mass*distance)",
        "t*nmi": "Goods transport (mass*distance)",
        "p*km": "Person transport", "p*mi": "Person transport",
        "m3": "Volume", "l": "Volume", "ml": "Volume",
        "cm3": "Volume", "dm3": "Volume",
        "m2": "Area", "km2": "Area", "ha": "Area", "ft2": "Area",
        "h": "Duration", "min": "Duration", "s": "Duration",
        "d": "Duration", "a": "Duration", "hr": "Duration",
        "km": "Length", "m": "Length", "cm": "Length",
        "mm": "Length", "mi": "Length", "ft": "Length",
        "in": "Length", "nmi": "Length",
        "Item(s)": "Number of items",
        "Dozen(s)": "Number of items",
        "kW": "Power", "MW": "Power", "W": "Power",
        "Bq": "Radioactivity", "kBq": "Radioactivity",
        "mol": "Mole",
    }

    def _detect_database_family(self):
        """
        Auto-detect whether the connected database uses ecoinvent
        or FLCAC flow property naming. Checks for telltale FP names.
        Stores the result for the rest of the session.
        """
        if hasattr(self, "_db_family") and self._db_family:
            return self._db_family

        self._ensure_unit_cache()

        # ecoinvent has "Time"; FLCAC has "Duration"
        # ecoinvent has "Mass transport"; FLCAC has "Goods transport..."
        has_time = "Time" in self._fp_lookup
        has_duration = "Duration" in self._fp_lookup
        has_mass_transport = "Mass transport" in self._fp_lookup
        has_goods_transport = "Goods transport (mass*distance)" in self._fp_lookup

        if has_time and has_mass_transport:
            self._db_family = "ecoinvent"
        elif has_duration and has_goods_transport:
            self._db_family = "flcac"
        elif has_time:
            self._db_family = "ecoinvent"
        elif has_duration:
            self._db_family = "flcac"
        else:
            self._db_family = "unknown"

        logger.info(f"Detected database family: {self._db_family}")
        return self._db_family

    def set_database_family(self, family: str) -> Dict:
        """
        Set the database family manually from user input.

        family: 'ecoinvent' or 'flcac'

        Call this when the user tells you which database type they
        have. If they don't know, call database_info instead which
        auto-detects.
        """
        family = family.lower().strip()

        # W02: Detect current family *before* overwriting, so we can
        # warn if the user is switching away from the auto-detected one.
        # Temporarily clear the cache to force fresh detection.
        prev_family = getattr(self, "_db_family", None)
        self._db_family = None
        detected = self._detect_database_family()
        # Restore the previous value so the overwrite below is clean
        self._db_family = prev_family

        if family in ("ecoinvent", "ei"):
            self._db_family = "ecoinvent"
        elif family in ("flcac", "lca commons", "uslci", "useeio"):
            self._db_family = "flcac"
        else:
            return {
                "error": f"Unknown family '{family}'. Use 'ecoinvent' or 'flcac'.",
                "ecoinvent_includes": "ecoinvent, EN15804GD, HiQLCD, BAFU",
                "flcac_includes": "LCA Commons, US LCI, USEEIO",
            }

        # W02: Warn if overriding a different auto-detected family
        warning = None
        if detected != "unknown" and detected != self._db_family:
            warning = (
                f"Auto-detected family was '{detected}' but you've "
                f"overridden it to '{self._db_family}'. This changes "
                f"unit-to-flow-property mapping for all subsequent "
                f"operations. Call set_database_family('{detected}') "
                f"to revert."
            )

        logger.info(f"Database family set by user: {self._db_family}")
        result = {
            "database_family": self._db_family,
            "unit_mapping": "ecoinvent" if self._db_family == "ecoinvent" else "FLCAC",
        }
        if warning:
            result["warning"] = warning
        return result

    @property
    def UNIT_FP_MAP(self):
        """Return the correct unit map for the detected database family."""
        family = self._detect_database_family()
        if family == "flcac":
            return self.FLCAC_FP_MAP
        return self.ECOINVENT_FP_MAP  # default for ecoinvent or unknown

    def _ensure_unit_cache(self):
        """Build unit cache on first use. Maps unit name → unit_ref."""
        if hasattr(self, "_unit_cache_built") and self._unit_cache_built:
            return
        self._unit_lookup = {}
        for ug_ref in self.client.get_descriptors(o.UnitGroup):
            ug = self.client.get(o.UnitGroup, ug_ref.id)
            if ug and ug.units:
                for u in ug.units:
                    self._unit_lookup[u.name] = o.Ref(
                        id=u.id, name=u.name, ref_type=o.RefType.Unit,
                    )
        self._fp_lookup = {}
        for fp_ref in self.client.get_descriptors(o.FlowProperty):
            self._fp_lookup[fp_ref.name] = fp_ref
        self._unit_cache_built = True

    def find_unit(self, unit_name: str) -> Dict:
        """
        Look up a unit and its flow property by name.
        Returns unit ref and flow property ref, or an error.
        """
        self._ensure_unit_cache()

        unit_ref = self._unit_lookup.get(unit_name)
        if not unit_ref:
            available = sorted(self._unit_lookup.keys())[:30]
            return {
                "error": f"Unit '{unit_name}' not found",
                "available_sample": available,
            }

        # Find flow property from candidate list
        fp_ref = self._get_fp_ref(unit_name)

        return {
            "unit_id": unit_ref.id,
            "unit_name": unit_ref.name,
            "flow_property_id": fp_ref.id if fp_ref else None,
            "flow_property_name": fp_ref.name if fp_ref else None,
        }

    def _get_unit_ref(self, unit_name: str):
        """Internal: get unit Ref or None."""
        self._ensure_unit_cache()
        return self._unit_lookup.get(unit_name)

    @staticmethod
    def _is_global(param) -> bool:
        """openLCA lists the parameters of processes among the
        parameter descriptors too. Only a global one can be redefined
        without a context, edited as a global or shown as one."""
        scope = getattr(param, "parameter_scope", None)
        return scope is None or scope == o.ParameterScope.GLOBAL_SCOPE

    def _parameter_targets(self, system,
                           names=None) -> Dict[str, List[Dict]]:
        """Every redefinable copy of every parameter in a system.

        Returns {name: [{"context": Ref|None, "value": float,
        "is_input": bool}, ...]}.

        The same name can exist in several processes (each with its
        own process-scope copy) and as a global parameter. Earlier
        versions built {name: context} with a dict, so only the last
        copy survived and a scenario changed one process but not the
        others. Every copy is kept here so callers can redefine all
        of them.

        Global parameters are added from the database if openLCA
        didn't return them with the system, so a global referenced
        in any formula can always be redefined. Pass names to limit
        the global lookup to the parameters actually needed.
        """
        targets: Dict[str, List[Dict]] = {}
        for p in self.client.get_parameters(o.ProductSystem, system.id):
            targets.setdefault(p.name, []).append({
                "context": p.context,
                "value": p.value,
                "is_input": True,
            })

        have_global = {n for n, copies in targets.items()
                       if any(c["context"] is None for c in copies)}
        for desc in self._get_descriptors(o.Parameter):
            if desc.name in have_global:
                continue
            if names is not None and desc.name not in names:
                continue
            param = self.client.get(o.Parameter, desc.id)
            if not param or not self._is_global(param):
                continue
            targets.setdefault(param.name, []).append({
                "context": None,
                "value": param.value,
                "is_input": bool(getattr(param, "is_input_parameter", True)),
            })
        return targets

    @staticmethod
    def _split_targets(targets: Dict[str, List[Dict]],
                       names) -> Dict[str, List]:
        """Sort requested names into redefinable, dependent (formula
        parameters, which openLCA calculates rather than accepts a
        value for) and missing."""
        ok, dependent, missing = [], [], []
        for name in names:
            copies = targets.get(name)
            if not copies:
                missing.append(name)
            elif not any(c["is_input"] for c in copies):
                dependent.append(name)
            else:
                ok.append(name)
        return {"ok": ok, "dependent": dependent, "missing": missing}
