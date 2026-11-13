"""
The rules that stop a model being calculated when it is not the model
the program describes (olcaBASIC 0.4.0, second rebuild).

    stale systems      a product system is stale once a process in it
                       has been edited, relinked, moved or parameterised;
                       it has to be built again and pass VALIDATE
    factors            an elementary flow that olcaBASIC created must
                       have a characterisation factor in the method, or
                       be accepted with IGNORE FACTORS on a CALCULATE
    uncertainty        Monte Carlo needs something uncertain
    allocation         physical or economic allocation needs factors on
                       every process with more than one product

Each is an error with a line and a hint. They are checked where the
validation gate is (EnforcementMixin._require_valid), so every command
that calculates goes through them.

Part of olcabasic.interpreter.Interpreter.
"""

from typing import Dict, List, Optional

from .errors import BasicError


class ModelRulesMixin:

    # ── stale product systems ────────────────────────────────

    def _mark_stale(self, process_id: str, process_name: str, why: str):
        """A process changed: every product system that contains it no
        longer shows the model, and says so until it is rebuilt."""
        if not process_id or self.bridge is None:
            return
        found = self.bridge.systems_containing(process_id)
        if "error" in found:
            return
        marked = []
        for system in found["systems"]:
            self.runtime.stale_systems[system["id"]] = {
                "name": system["name"], "process": process_name, "why": why}
            self.runtime.revalidate.add(system["name"])
            self._forget_validation(system["id"])
            # an open result of this system no longer matches it
            self._system_changed(system["id"])
            marked.append(system["name"])
        if marked:
            names = ", ".join(f'"{n}"' for n in marked)
            one = len(marked) == 1
            self.out.write(
                f"  NOTE: product system{'' if one else 's'} {names} "
                f"contain{'s' if one else ''} '{process_name}' and "
                f"{'is' if one else 'are'} now out of date. Nothing can be "
                f"calculated on {'it' if one else 'them'} until "
                f"{'it is' if one else 'they are'} built again: DELETE "
                f"SYSTEM, SYSTEM, then VALIDATE.")

    def _system_rebuilt(self, system_id: str):
        """A product system was created (a new one has a new id)."""
        self.runtime.stale_systems.pop(system_id, None)
        if self.bridge is not None:
            self.bridge.forget_system_members(system_id)

    def _require_fresh(self, desc, line: int, command: str):
        stale = self.runtime.stale_systems.get(desc.id)
        if stale is not None:
            raise BasicError(
                f"{command} refused: '{desc.name}' is out of date. "
                f"'{stale['process']}' was changed ({stale['why']}) after "
                f"the system was built.", line,
                hint=f"Build the system again, then check it: CONFIRM "
                     f"DELETE ON, DELETE SYSTEM \"{desc.name}\", SYSTEM "
                     f"\"{desc.name}\" (or EPD SYSTEMS for an EPD), then "
                     f"VALIDATE \"{desc.name}\".")
        # The bridge rule, read from the database: holds for a system
        # made or relinked outside olcaBASIC (the openLCA app, Python).
        loose = self.bridge.system_unbridged(desc.id, self._build_folders())
        if "error" not in loose and loose.get("unbridged"):
            shown = loose["unbridged"][:5]
            more = len(loose["unbridged"]) - len(shown)
            listing = "\n".join(f"    {u}" for u in shown)
            if more > 0:
                listing += f"\n    ... and {more} more"
            raise BasicError(
                f"{command} refused: '{desc.name}' links background "
                f"processes straight into its own processes, with no "
                f"bridge:\n{listing}", line,
                hint="Every background input goes through a bridge. Make "
                     "the bridges (BRIDGE \"name\" ... END BRIDGE), point "
                     "the inputs at them, then build the system again "
                     "and VALIDATE it.")
        # The structure check: does the system still link what its
        # foreground processes ask for? It reads the database, so it
        # holds after RESET, in a new session, and after edits made in
        # the openLCA app.
        drift = self.bridge.system_drift(desc.id, self._build_folders())
        if "error" not in drift and drift.get("drift"):
            shown = drift["drift"][:5]
            more = len(drift["drift"]) - len(shown)
            listing = "\n".join(f"    {d}" for d in shown)
            if more > 0:
                listing += f"\n    ... and {more} more"
            raise BasicError(
                f"{command} refused: '{desc.name}' is out of date. Its "
                f"processes have changed since the system was built:\n"
                f"{listing}", line,
                hint=f"Build the system again, then check it: CONFIRM "
                     f"DELETE ON, DELETE SYSTEM \"{desc.name}\", SYSTEM "
                     f"\"{desc.name}\" (or EPD SYSTEMS for an EPD), then "
                     f"VALIDATE \"{desc.name}\".")
        if desc.name in self.runtime.revalidate:
            last = self.runtime.validation.get(desc.id)
            if not last or not last.get("valid", False):
                raise BasicError(
                    f"{command} refused: '{desc.name}' was built again "
                    f"after one of its processes changed, and has not "
                    f"passed VALIDATE since.", line,
                    hint=f"VALIDATE \"{desc.name}\" first (EPD CHECK does "
                         f"it for the systems of an EPD).")
            self.runtime.revalidate.discard(desc.name)

    # ── elementary flows without characterisation factors ────

    def _own_emission(self, flow_id: str, name: str):
        """Remember an elementary flow olcaBASIC created: a method that
        has no factor for it gives it no weight at all."""
        if flow_id and flow_id != "(to be created)":
            self.runtime.own_elementary[flow_id] = name

    def _note_elementary(self, flow_id: str, name: str):
        """An existing elementary flow a block uses: remembered if
        olcaBASIC made it (in this session or an earlier one)."""
        if not flow_id or flow_id in self.runtime.own_elementary:
            return
        if flow_id in self.runtime.checked_elementary:
            return
        self.runtime.checked_elementary.add(flow_id)
        if self.bridge.flow_is_own(flow_id):
            self._own_emission(flow_id, name)

    def _accept_no_factors(self, names: List[str], method: str, line: int):
        """IGNORE FACTORS "flow": accept, knowingly, that a flow the
        program created adds nothing under this method."""
        own = self.runtime.own_elementary
        missing = self._without_factors(method, line, accepted=False)
        by_name = {f["name"].lower(): f for f in missing}
        for name in names:
            flow = by_name.get(name.lower())
            if flow is None:
                known = any(n.lower() == name.lower() for n in own.values())
                why = ("it has a characterisation factor in this method"
                       if known else
                       "it is not an elementary flow this program created")
                listed = ", ".join(f'"{f["name"]}"' for f in missing)
                raise BasicError(
                    f"IGNORE FACTORS \"{name}\": there is nothing to "
                    f"ignore, because {why}.", line,
                    hint=(f"Flows without a factor in '{method}': {listed}."
                          if missing else "Remove IGNORE FACTORS from the "
                                          "line."))
            self.runtime.accepted_no_factors.add((method, flow["id"]))

    def _without_factors(self, method: str, line: int,
                         accepted: bool = True) -> List[Dict]:
        own = self.runtime.own_elementary
        if not own:
            return []
        found = self.bridge.uncharacterised_flows(method, list(own))
        if "error" in found:
            raise BasicError(found["error"], line)
        flows = found["flows"]
        if accepted:
            flows = [f for f in flows if (method, f["id"])
                     not in self.runtime.accepted_no_factors]
        return flows

    def _require_factors(self, method: str, line: int, command: str):
        missing = self._without_factors(method, line)
        if missing:
            names = ", ".join(f"'{f['name']}'" for f in missing)
            one = len(missing) == 1
            first = missing[0]["name"]
            raise BasicError(
                f"{command} refused: '{method}' has no characterisation "
                f"factor for {names}, which this program created. "
                f"{'It' if one else 'They'} would add nothing to any "
                f"result.", line,
                hint=f"Use a flow the method knows (FIND FLOW shows the "
                     f"names in the database), or give the flow a factor "
                     f"in a method of your own (EDIT METHOD). To accept it "
                     f"knowingly: CALCULATE \"system\" USING \"{method}\" "
                     f"IGNORE FACTORS \"{first}\".")
        ignored = [self.runtime.own_elementary.get(flow_id, flow_id)
                   for accepted_for, flow_id
                   in sorted(self.runtime.accepted_no_factors)
                   if accepted_for == method]
        if ignored:
            names = ", ".join(f"'{n}'" for n in ignored)
            self.out.write(
                f"  NOTE: {names} {'has' if len(ignored) == 1 else 'have'} "
                f"no characterisation factor in '{method}' and "
                f"add{'s' if len(ignored) == 1 else ''} nothing to these "
                f"results (accepted with IGNORE FACTORS).")
        return ignored

    # ── allocation factors ───────────────────────────────────

    def _require_allocation_factors(self, system: str, allocation: str,
                                    line: int, command: str):
        found = self.bridge.allocation_gaps(system, allocation or None,
                                            self._build_folders())
        if "error" in found:
            return                  # the engine reports a bad system or word
        gaps = found["gaps"]
        if not gaps:
            return
        g = gaps[0]
        products = ", ".join(f'"{p}"' for p in g["products"])
        more = (f" ({len(gaps) - 1} more process"
                f"{'es' if len(gaps) > 2 else ''} like it: "
                + ", ".join(f"'{x['process']}'" for x in gaps[1:4]) + ")"
                if len(gaps) > 1 else "")
        raise BasicError(
            f"{command} refused: '{g['process']}' has {len(g['products'])} "
            f"products ({products}) and no {g['method']} allocation "
            f"factors, so openLCA cannot share its inputs and emissions "
            f"between them{more}.", line,
            hint=f"Give the factors in the process: EDIT PROCESS "
                 f"\"{g['process']}\" / ALLOCATION {g['method']} / "
                 f"\"product\", share (one line per product, adding up to "
                 f"1) / END ALLOCATION / END EDIT. (Each / is a new line.) "
                 f"Or calculate with ALLOCATE NONE.")

    # ── Monte Carlo ──────────────────────────────────────────

    def _foreground_uncertainty(self, system: str, line: int) -> Dict:
        found = self.bridge.foreground_uncertainty(system,
                                                   self._build_folders())
        if "error" in found:
            raise BasicError(found["error"], line)
        return found
