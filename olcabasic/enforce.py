"""
The rules the language enforces.

These used to be advice in the MCP server's instructions (ask which
method, never pick between same-named processes silently, establish the
database family first, never present a structural check as proof the
model is right). Advice can be ignored; a refusal cannot. Each rule
here is a refusal with a line number and a hint that says what to type.
"""

from typing import Dict, List

from .errors import BasicError

# The line that always ends CHECK ... TIER 1 output.
TIER_1_CAVEAT = (
    "  Tier 1 checks structure only: it does not show that the amounts or "
    "the results are right.\n"
    "  Next: CHECK \"{system}\" TIER 2 AGAINST \"source file\" compares the "
    "model with its source data, and CHECK \"{system}\" TIER 3 looks at "
    "whether the results are plausible."
)

# What the interpreter does when an optional argument is left out.
DEFAULTS: Dict[str, str] = {
    "ALLOCATE": "ALLOCATE AS_DEFINED (allocation as set in each process)",
    "LINKING": "LINKING PREFER_DEFAULTS (default providers where they are "
               "set, otherwise the first provider openLCA finds)",
    "TOP": "TOP {value}",
    "LEVELS": "LEVELS {value}",
    "MAX": "MAX {value}",
    "RUNS": "RUNS {value}",
    "TIER": "TIER 1 (structure only)",
    "TARGET": "TARGET 1 (one reference unit of the product)",
    "USAGE LIMIT": "LIMIT {value} (stop after that many uses are found)",
    "FOLDER": "FOLDER \"{value}\" (the process folder, for entities made "
              "without FOLDER)",
}

MAX_CANDIDATES = 12


class EnforcementMixin:
    """Rule checks shared by the interpreter's commands."""

    # ── database family ──────────────────────────────────────

    def _require_family(self, line: int, what: str):
        """Anything that picks a flow property from a unit needs to know
        which family of names the database uses."""
        family = self.bridge.database_family
        if family not in ("ecoinvent", "flcac"):
            raise BasicError(
                f"The database family is not known, so {what} can't choose "
                f"the right flow property for a unit.", line,
                hint='Say which it is first: DATABASE FAMILY "ecoinvent" '
                     '(ecoinvent, EN15804GD, HiQLCD, BAFU) or DATABASE '
                     'FAMILY "flcac" (US LCA Commons, US LCI, USEEIO).')

    # ── impact methods ───────────────────────────────────────

    def _method(self, name: str, line: int) -> str:
        """The exact name of the one method called this, or an error
        that lists the near misses."""
        found = self.bridge.find_method_strict(name)
        if "error" not in found:
            return found["name"]
        candidates = found.get("candidates") or []
        if candidates:
            shown = ", ".join(f'"{c}"' for c in candidates)
            hint = (f"Use the full name. Close matches: {shown}. "
                    f"FIND METHOD \"{name}\" lists them.")
        else:
            hint = ("PRINT METHODS lists every impact method in the "
                    "database.")
        raise BasicError(found["error"], line, hint=hint)

    # ── ambiguous process names ──────────────────────────────

    def _ambiguous_process(self, name: str, location: str, line: int,
                           candidates: List[Dict]):
        """A name that could mean several processes is an error."""
        rows = [f"    {c['location'] or '(no location)':<16} {c['id']}"
                for c in candidates[:MAX_CANDIDATES]]
        more = len(candidates) - MAX_CANDIDATES
        if more > 0:
            rows.append(f"    ... and {more} more (FIND PROCESS \"{name}\" "
                        f"lists them all)")
        where = f" at LOCATION \"{location}\"" if location else ""
        listing = "\n".join(rows)
        if location:
            fix = ("Add PROVIDER \"uuid\" to the line to pick one of them.")
        else:
            fix = ("Add LOCATION \"code\" to the line (or PROVIDER \"uuid\" "
                   "if two share a location).")
        raise BasicError(
            f"'{name}' matches {len(candidates)} processes{where}:\n"
            f"{listing}", line, hint=fix)

    def _ambiguous_flow(self, name: str, folder: str, line: int,
                        candidates: List[Dict]):
        """A flow name that could mean several flows is an error, the
        same as for processes."""
        rows = [f"    {c['category'] or '(no folder)':<40} {c['id']}"
                for c in candidates[:MAX_CANDIDATES]]
        more = len(candidates) - MAX_CANDIDATES
        if more > 0:
            rows.append(f"    ... and {more} more (FIND FLOW \"{name}\" "
                        f"lists them all)")
        where = f" in '{folder}'" if folder else ""
        listing = "\n".join(rows)
        raise BasicError(
            f"'{name}' matches {len(candidates)} flows{where}:\n{listing}",
            line,
            hint=("Add FOLDER \"path\" to the line to say which folder the "
                  "flow is in, or give the flow's UUID in place of its "
                  "name."))

    # ── validation before calculation ────────────────────────

    def _record_validation(self, result: Dict):
        """Remember how the last VALIDATE of each system went."""
        system_id = result.get("system_id")
        if system_id:
            self.runtime.validation[system_id] = result

    def _forget_validation(self, system_id: str):
        self.runtime.validation.pop(system_id, None)

    def _require_valid(self, system: str, line: int, command: str,
                       method: str = "", allocation: str = "",
                       check_allocation: bool = True):
        """The gate every calculating command goes through. Refused:
        a system whose last VALIDATE in this session failed; a system
        that is out of date; a method with no factor for a flow the
        program created; allocation without factors (see
        enforce_model.py for the last three)."""
        desc = self.bridge.find_system(system)
        if desc is None:
            return                      # the engine reports the missing system
        self._require_validated(desc, line, command)
        self._require_fresh(desc, line, command)
        if method:
            self._require_factors(method, line, command, system=desc.id)
        if check_allocation:
            self._require_allocation_factors(desc.id, allocation, line,
                                             command)

    def _require_validated(self, desc, line: int, command: str):
        last = self.runtime.validation.get(desc.id)
        when = "earlier in this session"
        if last is None and desc.name in self.runtime.revalidate:
            return      # rebuilt after a change: _require_fresh asks for VALIDATE
        if last is None:
            when = "just now"
            # Not validated in this session (a new session, or after
            # RESET): VALIDATE now, so a failure is never forgotten.
            result = self.bridge.validate_system(desc.id, False)
            if "error" in result:
                raise BasicError(
                    f"{command} refused: '{desc.name}' could not be "
                    f"checked with VALIDATE ({result['error']}).", line,
                    hint=f"VALIDATE \"{desc.name}\" and fix what it "
                         f"reports.")
            self._record_validation(result)
            last = self.runtime.validation.get(desc.id) or result
            self.out.write(
                f"  NOTE: '{desc.name}' had not been checked in this "
                f"session, so VALIDATE ran first: "
                f"{'passed' if last.get('valid', True) else 'failed'}.")
        if last.get("valid", True):
            return
        problems = "; ".join(
            f["message"] for f in last.get("findings", [])
            if f.get("severity") == "error") or "it has errors"
        raise BasicError(
            f"{command} refused: '{desc.name}' failed VALIDATE {when} "
            f"({problems}).", line,
            hint=f"Fix the links, or DELETE SYSTEM \"{desc.name}\" and "
                 f"SYSTEM \"{desc.name}\" again. Then VALIDATE "
                 f"\"{desc.name}\" before calculating.")

    # ── defaults are stated, once ────────────────────────────

    def _defaults(self, stmt, **values):
        """Say which defaults were applied for the arguments the
        program left out. Each default is stated once per session."""
        for key in getattr(stmt, "defaulted", ()) or ():
            self._default(key, values.get(key))

    def _default(self, key: str, value=None):
        if key in self.runtime.defaults_shown:
            return
        self.runtime.defaults_shown.add(key)
        text = DEFAULTS.get(key, key).format(value=value)
        self.out.write(f"  NOTE: default used: {text}.")

    # ── bridges ──────────────────────────────────────────────

    @staticmethod
    def _bridge_name(name: str, unit: str, line: int) -> str:
        """Bridges are called 'BRIDGE | what | unit'. A plain name is
        given the prefix and the unit; a name already in that form must
        end with the same unit."""
        parts = [p.strip() for p in name.split("|")]
        if parts[0].upper() == "BRIDGE" and len(parts) >= 2:
            if len(parts) >= 3 and parts[-1] != unit:
                raise BasicError(
                    f"The bridge name ends with '{parts[-1]}' but its unit "
                    f"is '{unit}'.", line,
                    hint=f"Name it \"BRIDGE | {' | '.join(parts[1:-1])} | "
                         f"{unit}\", or change the unit.")
            if len(parts) == 2:
                return f"BRIDGE | {parts[1]} | {unit}"
            return "BRIDGE | " + " | ".join(parts[1:])
        return f"BRIDGE | {name.strip()} | {unit}"

    @staticmethod
    def _is_bridge(name: str, category: str = "") -> bool:
        """A bridge is named 'BRIDGE | ...' or sits in a Bridges folder."""
        segments = [seg.strip().lower() for seg in (category or "").split("/")]
        return (name.upper().replace(" ", "").startswith("BRIDGE|")
                or "bridges" in segments)
