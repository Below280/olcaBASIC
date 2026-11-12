"""
Every entity type, in the language: the generic FIND, SHOW, DELETE,
MOVE and EXPORT, the MAKE and EDIT blocks, methods, projects, stored
results and SHUTDOWN SERVER.

Part of olcabasic.interpreter.Interpreter.
"""

import json
import os
from typing import Dict, List, Optional

from .ast_nodes import StringLiteral
from .errors import BasicError
from .formatting import (
    format_entities, format_entity, format_project_results,
)

FOREIGN_BACKUP = (
    "Methods from ecoinvent or openLCA Nexus are licensed and shared by "
    "every model in the database; a change cannot be undone without a "
    "backup. Back the database up first (in openLCA: right-click the "
    "database, Backup).")
FOREIGN_NEEDS_A_PERSON = (
    "Changing a method that olcaBASIC did not make needs a person at the "
    "olcaBASIC terminal to answer YES; it cannot be done through a "
    "Session or the MCP. Copy the method in openLCA and make your own "
    "with MAKE METHOD if you need different factors.")


class EntitiesInterpMixin:

    # ── helpers ──────────────────────────────────────────────

    def _engine_fail(self, result: Dict, line: int):
        """Raise the error an engine call returned, at the line it
        names when it names one."""
        where = result.get("where")
        at = where if isinstance(where, int) and where else line
        raise BasicError(result["error"], at, hint=result.get("hint") or "")

    def _text(self, expr) -> Optional[str]:
        return None if expr is None else self._eval_str(expr)

    def _refuse_flow_map(self, stmt):
        if stmt.entity_type == "FLOW MAP":
            raise BasicError(
                "olcaBASIC cannot reach flow maps: openLCA's IPC server "
                "has no method for them, and they are not stored as "
                "entities of the database.", stmt.line,
                hint="Flow maps are made and used in openLCA's import "
                     "dialogues.")

    def _build_folder(self, given, line: int) -> str:
        """The folder a new entity goes into: the one on the line, or
        the process folder (said once)."""
        if given is not None:
            return self._eval_str(given)
        folder = self.runtime.process_folder
        if folder:
            self._default("FOLDER", folder)
        return folder or ""

    # ── FIND ─────────────────────────────────────────────────

    def _exec_entity_find(self, stmt):
        self._require_bridge(stmt.line)
        self._refuse_flow_map(stmt)
        term = self._text(stmt.term) or ""
        folder = self._text(stmt.folder)
        result = self.bridge.find_entities(stmt.entity_type, term, folder)
        self._emit("find_entities", result)
        if "error" in result:
            self._engine_fail(result, stmt.line)
        self.out.write(format_entities(result))

    # ── SHOW ─────────────────────────────────────────────────

    def _show_json(self, etype: str, ref: str, line: int):
        result = self.bridge.entity_json(etype, ref)
        if "error" in result:
            self._engine_fail(result, line)
        self._emit("entity_json", result)
        self.out.write(json.dumps(result["json"], indent=2,
                                  ensure_ascii=False))

    def _show_usage(self, etype: str, ref: str, line: int):
        found = self.bridge.resolve_one(etype, ref)
        if "id" not in found:
            self._engine_fail(found, line)
        if not self.bridge.ipc_supports("data/get/usage") and etype in (
                "ACTOR", "SOURCE", "CURRENCY", "LOCATION", "DQ SYSTEM",
                "SOCIAL INDICATOR", "PARAMETER"):
            self.out.write(f"  Checking where '{found['name']}' is used "
                           f"(this reads every process)...")
        usage = self.bridge.entity_usage(etype, found["id"], found["name"],
                                         max_hits=50)
        if "error" in usage:
            raise BasicError(
                usage["error"], line,
                hint="openLCA answers this from version 2.7 "
                     "(data/get/usage)." if etype in (
                         "PROCESS", "SYSTEM") else "")
        usage = dict(usage, type=etype, name=found["name"], id=found["id"])
        self._emit("entity_usage", usage)
        label = self.bridge.entity_label(etype)
        if not usage["in_use"]:
            self.out.write(f"  Nothing uses the {label} '{found['name']}' "
                           f"({usage['how']}).")
            return
        self.out.write(f"  The {label} '{found['name']}' is used by:")
        for user in usage["users"]:
            self.out.write(f"    {user}")
        if not usage["complete"]:
            self.out.write("    ... and possibly more: the search stopped "
                           "at 50.")

    def _exec_entity_show(self, stmt):
        self._require_bridge(stmt.line)
        self._refuse_flow_map(stmt)
        ref = self._eval_str(stmt.ref)
        if stmt.mode == "JSON":
            return self._show_json(stmt.entity_type, ref, stmt.line)
        if stmt.mode == "USAGE":
            return self._show_usage(stmt.entity_type, ref, stmt.line)
        result = self.bridge.show_entity(stmt.entity_type, ref)
        if "error" in result:
            self._engine_fail(result, stmt.line)
        self._emit("show_entity", result)
        self.out.write(format_entity(result))

    # ── DELETE ───────────────────────────────────────────────

    def _confirm_foreign(self, what: str, name: str, factors: int,
                         confirmed: bool, line: int, command: str):
        """The PARAMETERISE rule for a method or category olcaBASIC did
        not make: refused without CONFIRM, and with it a person has to
        answer."""
        if not confirmed:
            raise BasicError(
                f"'{name}' was not made by olcaBASIC, and {command} would "
                f"{what} {factors} characterisation "
                f"factor{'s' if factors != 1 else ''}.", line,
                hint=f"{FOREIGN_BACKUP} Then add CONFIRM: {command} "
                     f"CONFIRM.")
        self.out.write(
            f"  '{name}' was not made by olcaBASIC. This will {what} "
            f"{factors} characterisation factor{'s' if factors != 1 else ''}"
            f" that every model using the method relies on.")
        self.out.write(f"  {FOREIGN_BACKUP}")
        answer = self._ask("  Are you sure? Type YES to go on: ", line,
                           FOREIGN_NEEDS_A_PERSON)
        if answer.strip().upper() != "YES":
            raise BasicError(f"{command} cancelled. Nothing was changed.",
                             line)

    def _exec_entity_delete(self, stmt):
        self._require_bridge(stmt.line)
        self._refuse_flow_map(stmt)
        etype = stmt.entity_type
        ref = self._eval_str(stmt.ref)
        label = self.bridge.entity_label(etype)
        found = self.bridge.resolve_one(etype, ref)
        if found.get("not_found"):
            self.out.write(f"  Not found: {ref} (nothing to delete)")
            return
        if "id" not in found:
            self._engine_fail(found, stmt.line)
        name = found["name"]

        foreign = False
        if etype in ("METHOD", "CATEGORY"):
            probe = self.bridge.delete_probe(etype, found["id"])
            if "error" in probe:
                self._engine_fail(probe, stmt.line)
            if not probe["own"]:
                foreign = True
                self._confirm_foreign(
                    "delete", name, probe["factors"], stmt.confirm,
                    stmt.line, f'DELETE {etype} "{name}"')

        if not self.bridge.ipc_supports("data/get/usage") and etype in (
                "ACTOR", "SOURCE", "CURRENCY", "LOCATION", "DQ SYSTEM",
                "SOCIAL INDICATOR", "PARAMETER"):
            self.out.write(f"  Checking where '{name}' is used (this reads "
                           f"every process)...")
        if not foreign:
            if not self.runtime.confirm_delete:
                answer = self._ask(
                    f"  Delete {label} '{name}'? (yes/no) ", stmt.line,
                    "Put CONFIRM DELETE ON before the DELETE line.")
                if answer.lower() not in ("yes", "y"):
                    self.out.write("  Cancelled.")
                    return
            else:
                self.out.write(f"  Deleting {label} '{name}'...")
        result = self.bridge.delete_any(etype, found["id"],
                                        confirm_foreign=foreign)
        if "error" in result:
            if result.get("in_use"):
                raise BasicError(
                    result["error"].rstrip(".") + ", so it was not deleted.",
                    stmt.line, hint=result.get("hint", ""))
            self._engine_fail(result, stmt.line)
        self._emit("delete_any", result)
        extra = (f" and {result['categories_deleted']} of its categories"
                 if result.get("categories_deleted") else "")
        self.out.write(f"  Deleted: {name}{extra}")
        self.bridge.refresh_caches()

    # ── MOVE ─────────────────────────────────────────────────

    def _exec_entity_move(self, stmt):
        self._require_bridge(stmt.line)
        self._refuse_flow_map(stmt)
        ref = self._eval_str(stmt.ref)
        dest = self._eval_str(stmt.destination)
        result = self.bridge.move_any(stmt.entity_type, ref, dest)
        if "error" in result:
            self._engine_fail(result, stmt.line)
        self._emit("move_any", result)
        label = self.bridge.entity_label(stmt.entity_type)
        self.out.write(f"  Moved {label} '{result['name']}' to '{dest}'")
        self.bridge.refresh_caches()

    # ── EXPORT ───────────────────────────────────────────────

    def _exec_entity_export(self, stmt):
        self._require_bridge(stmt.line)
        self._refuse_flow_map(stmt)
        ref = self._eval_str(stmt.ref)
        path = self._eval_str(stmt.filename)
        if not path.lower().endswith(".zip"):
            raise BasicError(
                f"'{path}' is not a .zip file name: openLCA writes JSON-LD "
                f"as a zip file.", stmt.line,
                hint=f'EXPORT {stmt.entity_type} "{ref}" TO "{path}.zip"')
        full = os.path.abspath(path)
        result = self.bridge.export_json_ld(stmt.entity_type, ref, full)
        if "error" in result:
            self._engine_fail(result, stmt.line)
        self._emit("export_json_ld", result)
        self.out.write(f"  Exported '{result['name']}' and what it depends "
                       f"on to {full}")
        self.out.write("  (openLCA wrote the file, on the machine openLCA "
                       "runs on.)")

    # ── MAKE / EDIT simple types ─────────────────────────────

    def _exec_make_entity(self, stmt):
        self._require_bridge(stmt.line)
        etype = stmt.entity_type
        name = self._eval_str(stmt.name)
        label = self.bridge.entity_label(etype)
        fields: Dict = {}
        where: Dict = {}
        for key, value, ln, kind in stmt.fields:
            self._at(ln)
            if kind == "number":
                fields[key] = self._number(value, key.replace("_", " "), ln)
            elif kind in ("yesno", "word"):
                fields[key] = value
            else:
                fields[key] = self._eval_str(value)
            where[key] = ln
        items = None
        if stmt.items is not None:
            items = []
            for item in stmt.items:
                ln = item["line"]
                self._at(ln)
                if etype == "UNITS":
                    items.append({
                        "name": self._eval_str(item["name"]),
                        "factor": self._number(item["factor"],
                                               "The factor of a unit", ln),
                        "reference": item["reference"],
                        "synonyms": self._text(item.get("synonyms")),
                        "description": self._text(item.get("description")),
                        "where": ln})
                else:
                    scores = []
                    for s in item["scores"]:
                        scores.append({
                            "position": s["position"],
                            "label": self._text(s["label"]) or "",
                            "description": self._text(s["description"]),
                            "uncertainty": (
                                None if s["uncertainty"] is None
                                else self._number(s["uncertainty"],
                                                  "UNCERTAINTY", s["line"])),
                        })
                    items.append({"name": self._eval_str(item["name"]),
                                  "scores": scores, "where": ln})
        self._at(stmt.line)
        folder = None
        if not stmt.editing:
            folder = self._build_folder(stmt.folder, stmt.line) or None
        fields["__where__"] = where
        result = self.bridge.make_entity(etype, name, folder, fields, items,
                                         editing=stmt.editing)
        if "error" in result:
            self._engine_fail(result, stmt.line)
        self._emit("make_entity", result)
        if result.get("already_existed"):
            self.out.write(
                f"  {label.capitalize()} exists already: {name} (left as "
                f"it is; EDIT {etype} \"{name}\" changes it)")
        elif stmt.editing:
            self.out.write(f"  Edited {label}: {name}")
        else:
            where_to = f" in {result['folder']}" if result.get("folder") \
                else ""
            self.out.write(f"  Created {label}: {name}{where_to}")
        if result.get("attached"):
            self.out.write(f"    attached file: {result['attached']}")
        if result.get("attach_error"):
            raise BasicError(
                f"The source '{name}' was saved, but its file was not "
                f"attached: {result['attach_error']}", where.get("attach",
                                                                 stmt.line),
                hint=result.get("attach_hint") or "")
        self.bridge.refresh_caches()

    # ── methods ──────────────────────────────────────────────

    def _factor_spec(self, f: Dict) -> Dict:
        ln = f["line"]
        self._at(ln)
        return {
            "flow": self._eval_str(f["flow"]),
            "compartment": self._text(f["compartment"]),
            "value": (None if f["value"] is None
                      else self._number(f["value"], "A factor", ln)),
            "formula": self._text(f["formula"]),
            "unit": f["unit"],
            "location": self._text(f["location"]),
            "uncertainty": self._uncertainty(f["uncertainty"], ln),
            "where": ln}

    def _category_specs(self, categories: List[Dict]) -> List[Dict]:
        out = []
        for c in categories:
            ln = c["line"]
            self._at(ln)
            params = []
            for p in c["parameters"]:
                params.append({
                    "name": p["name"],
                    "value": (None if p["value"] is None else self._number(
                        p["value"], f"PARAM {p['name']}", p["line"])),
                    "formula": self._text(p["formula"])})
            out.append({
                "name": self._eval_str(c["name"]),
                "unit": self._text(c["unit"]),
                "direction": c["direction"], "code": self._text(c["code"]),
                "description": self._text(c["description"]),
                "parameters": params,
                "factors": [self._factor_spec(f) for f in c["factors"]],
                "remove_factors": [
                    {"flow": self._eval_str(f["flow"]),
                     "compartment": self._text(f["compartment"]),
                     "where": f["line"]} for f in c["remove_factors"]],
                "where": ln})
        return out

    def _nw_specs(self, nw_sets: List[Dict]) -> List[Dict]:
        out = []
        for s in nw_sets:
            rows = []
            for r in s["factors"]:
                ln = r["line"]
                self._at(ln)
                rows.append({
                    "category": self._eval_str(r["category"]),
                    "normalisation": (
                        None if r["normalisation"] is None else self._number(
                            r["normalisation"], "A normalisation factor",
                            ln)),
                    "weighting": (
                        None if r["weighting"] is None else self._number(
                            r["weighting"], "A weighting factor", ln)),
                    "where": ln})
            out.append({"name": self._eval_str(s["name"]),
                        "unit": self._text(s["unit"]),
                        "description": self._text(s["description"]),
                        "factors": rows, "where": s["line"]})
        return out

    def _exec_method(self, stmt):
        self._require_bridge(stmt.line)
        name = self._eval_str(stmt.name)
        categories = self._category_specs(stmt.categories)
        nw_sets = self._nw_specs(stmt.nw_sets)
        self._at(stmt.line)
        if not stmt.editing:
            folder = self._build_folder(stmt.folder, stmt.line) or None
            result = self.bridge.make_method(
                name, folder, categories, nw_sets,
                description=self._text(stmt.description),
                source=self._text(stmt.source), code=self._text(stmt.code))
            if "error" in result:
                self._engine_fail(result, stmt.line)
            self._emit("make_method", result)
            if result.get("already_existed"):
                self.out.write(
                    f"  Impact method exists already: {name} (left as it "
                    f"is; EDIT METHOD \"{name}\" changes it)")
            else:
                self.out.write(
                    f"  Created impact method: {name} "
                    f"({result['categories']} categories, "
                    f"{result['factors']} factors, {result['nw_sets']} NW "
                    f"sets)")
            self.bridge.refresh_caches()
            return

        if stmt.source is not None or stmt.code is not None:
            raise BasicError(
                "EDIT METHOD changes categories, factors, NW sets and the "
                "description; SOURCE and CODE are set when the method is "
                "made.", stmt.line)
        args = dict(
            categories=categories,
            remove_categories=[self._eval_str(e)
                               for e, _ in stmt.remove_categories],
            nw_sets=nw_sets,
            remove_nw_sets=[self._eval_str(e) for e, _ in stmt.remove_nw_sets],
            description=self._text(stmt.description))
        plan = self.bridge.edit_method(name, dry_run=True,
                                       confirm_foreign=True, **args)
        if "error" in plan:
            self._engine_fail(plan, stmt.line)
        if not plan["changes"]:
            self.out.write(f"  Nothing to change in '{plan['name']}'.")
            return
        if not plan["own"]:
            self._confirm_foreign(
                "change", plan["name"], plan["factors_changed"],
                stmt.confirm, stmt.line, f'EDIT METHOD "{plan["name"]}"')
        result = self.bridge.edit_method(name, confirm_foreign=True, **args)
        if "error" in result:
            self._engine_fail(result, stmt.line)
        self._emit("edit_method", result)
        self.out.write(f"  Edited impact method: {result['name']}")
        for change in result["changes"]:
            self.out.write(f"    {change}")
        self.bridge.refresh_caches()

    # ── projects ─────────────────────────────────────────────

    def _exec_project(self, stmt):
        self._require_bridge(stmt.line)
        name = self._eval_str(stmt.name)
        method = self._method(self._eval_str(stmt.method), stmt.line)
        variants = []
        for v in stmt.variants:
            ln = v["line"]
            self._at(ln)
            amount = None
            if v["amount"] is not None:
                amount = self._number(v["amount"], "AMOUNT", ln)
            variants.append({
                "name": self._eval_str(v["name"]),
                "system": self._eval_str(v["system"]),
                "amount": amount, "unit": v["unit"],
                "allocation": v["allocation"] or None,
                "disabled": v["disabled"],
                "description": self._text(v["description"]),
                "values": [
                    {"name": x["name"],
                     "value": self._number(x["value"], x["name"], x["line"]),
                     "process": self._text(x["process"]),
                     "where": x["line"]} for x in v["values"]],
                "where": ln})
        self._at(stmt.line)
        folder = self._build_folder(stmt.folder, stmt.line) or None
        result = self.bridge.make_project(
            name, folder, method, variants, nw_set=self._text(stmt.nw_set),
            with_costs=stmt.with_costs,
            with_regionalisation=stmt.with_regionalisation,
            description=self._text(stmt.description))
        if "error" in result:
            self._engine_fail(result, stmt.line)
        self._emit("make_project", result)
        if result.get("already_existed"):
            self.out.write(
                f"  Project exists already: {name} (left as it is; DELETE "
                f"PROJECT \"{name}\" and make it again to change it)")
        else:
            self.out.write(f"  Created project: {name} "
                           f"({result['variants']} variants)")
        self.bridge.refresh_caches()

    def _exec_calculate_project(self, stmt):
        self._require_bridge(stmt.line)
        name = self._eval_str(stmt.name)
        self.out.write(f"  Calculating project: {name}...")
        result = self.bridge.calculate_project(name)
        if "error" in result:
            self._engine_fail(result, stmt.line)
        self._emit("calculate_project", result)
        self.runtime.store_results(result, "scenarios")
        self.out.write(format_project_results(result))

    # ── SAVE RESULT AS ───────────────────────────────────────

    def _exec_save_result_as(self, stmt):
        self._require_bridge(stmt.line)
        info = self._open_result_info(stmt.result_name, stmt.line)
        name = self._eval_str(stmt.name)
        folder = self._build_folder(stmt.folder, stmt.line) or None
        result = self.bridge.save_result(
            info["handle"], name, folder,
            description=self._text(stmt.description), replace=stmt.replace)
        if "error" in result:
            self._engine_fail(result, stmt.line)
        self._emit("save_result", result)
        verb = "Replaced" if result.get("replaced") else "Saved"
        self.out.write(
            f"  {verb} stored result: {name} ({result['impact_results']} "
            f"impact results, {result['flow_results']} flows)")
        self.bridge.refresh_caches()

    # ── SHUTDOWN SERVER ──────────────────────────────────────

    def _exec_shutdown(self, stmt):
        self._require_bridge(stmt.line)
        if not stmt.confirm:
            raise BasicError(
                "SHUTDOWN SERVER stops openLCA's IPC server and closes its "
                "database: nothing can reach openLCA afterwards until the "
                "server is started again by hand.", stmt.line,
                hint="If that is what you want: SHUTDOWN SERVER CONFIRM.")
        answer = self._ask(
            "  Stop openLCA's IPC server? Type YES to go on: ", stmt.line,
            "SHUTDOWN SERVER needs a person at the olcaBASIC terminal; it "
            "cannot be done through a Session or the MCP.")
        if answer.strip().upper() != "YES":
            raise BasicError("SHUTDOWN SERVER cancelled.", stmt.line)
        self.close_results()
        result = self.bridge.shutdown_server()
        if "error" in result:
            self._engine_fail(result, stmt.line)
        self.out.write("  openLCA's IPC server has stopped.")
