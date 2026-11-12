"""
The wider fields of processes, flows and product systems, in the
language: the values the parser collected are worked out, checked
before anything is created, and written after the process or system
exists.

Part of olcabasic.interpreter.Interpreter.
"""

from typing import Any, Dict, List, Optional

from .ast_nodes import EditSystemStmt, Expr
from .errors import BasicError
from .engine.fields import make_uncertainty
from .formatting import (format_process_fields, format_system_fields,
                         format_scenarios)


class FieldsInterpMixin:

    # ── values ───────────────────────────────────────────────

    def _number(self, expr, what: str, line: int) -> float:
        value = self._eval(expr)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise BasicError(f"{what} must be a number, not {value!r}.", line)
        return float(value)

    def _uncertainty(self, spec, line: int) -> Optional[Dict]:
        """{"kind", "values"} with the numbers worked out and checked,
        or None for UNCERTAINTY NONE."""
        if spec is None:
            return None
        line = spec.get("line") or line
        values = [self._number(v, f"UNCERTAINTY {spec['kind']}", line)
                  for v in spec["values"]]
        _, err = make_uncertainty(spec["kind"], values)
        if err:
            raise BasicError(err, line)
        return {"kind": spec["kind"], "values": values}

    def _exchange_extras(self, extras: Dict, line: int) -> Dict:
        """The extras of one INPUT or OUTPUT line as plain values."""
        out: Dict[str, Any] = {}
        if not extras:
            return out
        if "uncertainty" in extras:
            out["uncertainty"] = self._uncertainty(extras["uncertainty"], line)
        if "base_uncertainty" in extras:
            out["base_uncertainty"] = self._number(
                extras["base_uncertainty"], "BASE UNCERTAINTY", line)
        if "avoided" in extras:
            out["avoided"] = bool(extras["avoided"])
        if "cost" in extras:
            cost = extras["cost"]
            if cost is None:
                out["cost"] = None
            else:
                out["cost"] = {
                    "value": (self._number(cost["value"], "COST", line)
                              if "value" in cost else 0.0),
                    "formula": (self._eval_str(cost["formula"])
                                if "formula" in cost else None),
                    "currency": self._eval_str(cost["currency"])}
        if "site" in extras:
            out["site"] = (None if extras["site"] is None
                           else self._eval_str(extras["site"]))
        if "property" in extras:
            out["property"] = self._eval_str(extras["property"])
        return out

    def _process_fields(self, parsed: Dict) -> Dict:
        """The field lines of a PROCESS or EDIT block as plain values,
        each with the line it was written on ("where")."""
        out: Dict[str, Any] = {}
        ev = self._eval_str
        for block in parsed.get("allocation") or []:
            entries = []
            for e in block["entries"]:
                entry = {"product": ev(e["product"]), "where": e["line"]}
                if "formula" in e:
                    entry["formula"] = ev(e["formula"])
                else:
                    entry["value"] = self._number(
                        e["value"], "An allocation share", e["line"])
                if e.get("exchange"):
                    entry["exchange"] = dict(e["exchange"],
                                             name=ev(e["exchange"]["name"]))
                entries.append(entry)
            if not entries:
                raise BasicError(
                    f"ALLOCATION {block['type']} has no factors.",
                    block["line"],
                    hint="Give one line per product: \"product\", share. "
                         "In EDIT PROCESS, REMOVE ALLOCATION removes the "
                         "factors.")
            out.setdefault("allocation", {})[block["type"]] = entries
        if "default_allocation" in parsed:
            out["default_allocation"] = parsed["default_allocation"][0]
            out["default_allocation_where"] = parsed["default_allocation"][1]
        doc, where = {}, {}
        for field_name, kind, value, line in parsed.get("document") or []:
            where.setdefault(field_name, line)
            if kind in ("text", "date", "actor", "source"):
                if field_name in doc:
                    raise BasicError(
                        "That documentation field is given twice.", line)
                doc[field_name] = ev(value)
            elif kind == "bool":
                doc[field_name] = value
            elif kind == "sources":
                doc.setdefault(field_name, []).append(ev(value))
            elif kind == "aspect":
                doc.setdefault(field_name, []).append(
                    (ev(value[0]), ev(value[1])))
            elif kind == "review":
                doc.setdefault(field_name, []).append({
                    "type": ev(value["type"]),
                    "details": (ev(value["details"])
                                if "details" in value else None),
                    "report": (ev(value["report"])
                               if "report" in value else None),
                    "reviewers": [ev(a) for a in value["reviewers"]],
                    "scopes": [{"name": ev(s["name"]),
                                "methods": [ev(m) for m in s["methods"]]}
                               for s in value["scopes"]],
                    "assessment": [(ev(a), ev(v))
                                   for a, v in value["assessment"]]})
            elif kind == "compliance":
                doc.setdefault(field_name, []).append({
                    "system": ev(value["system"]),
                    "comment": (ev(value["comment"])
                                if "comment" in value else None),
                    "aspects": [(ev(a), ev(v))
                                for a, v in value["aspects"]]})
        if doc:
            out["document"], out["document_where"] = doc, where
        for s in parsed.get("social") or []:
            raw = self._eval(s["raw"])
            entry = {"indicator": ev(s["indicator"]),
                     "raw": (f"{raw:g}" if isinstance(raw, (int, float))
                             and not isinstance(raw, bool) else str(raw)),
                     "risk": s["risk"], "where": s["line"]}
            if "activity" in s:
                entry["activity"] = self._number(s["activity"], "ACTIVITY",
                                                 s["line"])
            for key in ("comment", "source"):
                if key in s:
                    entry[key] = ev(s[key])
            if "quality" in s:
                entry["quality"] = (s["quality"] if isinstance(s["quality"], str)
                                    else ev(s["quality"]))
            out.setdefault("social", []).append(entry)
        if "social_schema" in parsed:
            out["social_schema"] = ev(parsed["social_schema"][0])
            out["social_schema_where"] = parsed["social_schema"][1]
        for key in ("type", "infrastructure", "process_pedigree"):
            if key in parsed:
                out[key] = parsed[key][0]
                out[key + "_where"] = parsed[key][1]
        return out

    def _fields_error(self, result: Dict, default_line: int):
        where = result.get("where")
        line = where if isinstance(where, int) and where else default_line
        raise BasicError(result["error"], line, hint=result.get("hint") or "")

    # ── MAKE PROCESS ─────────────────────────────────────────

    def _make_process_fields(self, stmt, ex_list, check_exchanges) -> Dict:
        """Collect and check the wider fields of a PROCESS block before
        anything is written. Returns the fields to write once the
        process exists (empty when the block has none)."""
        fields = self._process_fields(stmt.fields)
        views = []
        for i, (ex, ex_dict) in enumerate(zip(ex_list, check_exchanges),
                                          start=1):
            line = ex.line or stmt.line
            self._at(line)
            views.append({
                "internal_id": i, "flow_id": ex_dict.get("flow_id"),
                "flow_name": ex_dict.get("view_name", ""),
                "aliases": [ex_dict.get("flow_name", "")],
                "is_input": ex_dict.get("is_input", True),
                "is_qref": bool(ex_dict.get("is_qref")),
                "flow_type": ex_dict.get("flow_type", "product"),
                "avoided": False})
            extras = self._exchange_extras(ex.extras, line)
            if extras:
                fields.setdefault("exchanges", []).append(
                    dict(extras, internal_id=i, where=line))
        for let_stmt in stmt.local_params:
            if let_stmt.uncertainty != "unset":
                line = let_stmt.line or stmt.line
                fields.setdefault("parameters", {})[let_stmt.name] = {
                    "uncertainty": self._uncertainty(let_stmt.uncertainty,
                                                     line),
                    "where": line}
        if "process_pedigree" in fields and stmt.process_schema is not None:
            fields["has_process_schema"] = True
        if not fields:
            return {}
        self._at(stmt.line)
        checked = self.bridge.check_process_fields(fields, views)
        if "error" in checked:
            self._fields_error(checked, stmt.line)
        return fields

    def _write_process_fields(self, process_id: str, fields: Dict,
                              line: int, quiet: bool = False) -> List[str]:
        if not fields:
            return []
        fields = dict(fields)
        fields.pop("has_process_schema", None)
        result = self.bridge.set_process_fields(process_id, fields)
        self._emit("set_process_fields", result)
        if "error" in result:
            self._fields_error(result, line)
        changes = result.get("changes", [])
        if not quiet:
            for c in changes:
                self.out.write(f"    {c}")
        return changes

    # ── LET x = 5 UNCERTAINTY ... ────────────────────────────

    def _let_uncertainty(self, stmt):
        """A top-level LET with UNCERTAINTY: kept with the variable and
        written to the global parameter when there is one."""
        if stmt.uncertainty == "unset":
            return
        if self.runtime.current_scope is not self.runtime.global_scope:
            raise BasicError(
                "UNCERTAINTY belongs to a parameter, and a variable inside "
                "a SUB or FUNCTION does not become one.", stmt.line,
                hint="Set it on a top-level LET, or on a LET inside a "
                     "PROCESS block.")
        spec = self._uncertainty(stmt.uncertainty, stmt.line)
        if self._expr_is_variable(stmt.expr) and spec is not None:
            raise BasicError(
                f"'{stmt.name}' is calculated from other variables, so it "
                f"has no uncertainty of its own.", stmt.line,
                hint="Put UNCERTAINTY on the variables it is calculated "
                     "from.")
        self.runtime.var_uncertainty[stmt.name] = spec
        if stmt.name in self.runtime.synced_globals:
            self._sync_uncertainty(stmt.name, stmt.line)

    def _sync_uncertainty(self, name: str, line: int):
        if name not in self.runtime.var_uncertainty:
            return
        spec = self.runtime.var_uncertainty[name]
        if self.runtime.synced_uncertainty.get(name, "unset") == spec:
            return
        result = self.bridge.set_parameter_uncertainty(name, spec)
        if "error" in result:
            raise BasicError(f"Global parameter '{name}': "
                             f"{result['error']}", line)
        self.runtime.synced_uncertainty[name] = spec

    # ── SYSTEM blocks, EDIT SYSTEM ───────────────────────────

    def _system_specs(self, sets: List[Dict], groups: List[Dict]):
        ev = self._eval_str
        out_sets = []
        seen = set()
        for s in sets:
            name = ev(s["name"])
            if name in seen:
                raise BasicError(f"There are two PARAMETER SET \"{name}\" "
                                 f"blocks.", s["line"])
            seen.add(name)
            out_sets.append({
                "name": name, "baseline": s["baseline"],
                "description": (ev(s["description"])
                                if "description" in s else None),
                "values": [{
                    "name": v["name"],
                    "value": self._number(v["value"], f"'{v['name']}'",
                                          v["line"]),
                    "process": ev(v["process"]) if "process" in v else None,
                    "where": v["line"]} for v in s["values"]]})
        if sum(1 for s in out_sets if s["baseline"]) > 1:
            raise BasicError(
                "Only one parameter set can be the BASELINE.",
                next(s["line"] for s in sets if s["baseline"]))
        out_groups = []
        seen = set()
        for g in groups:
            name = ev(g["name"])
            if name in seen:
                raise BasicError(f"There are two ANALYSIS GROUP \"{name}\" "
                                 f"blocks.", g["line"])
            seen.add(name)
            if not g["processes"]:
                raise BasicError(
                    f"ANALYSIS GROUP \"{name}\" names no process.",
                    g["line"], hint="List the processes of the group, one "
                                    "per line.")
            out_groups.append({
                "name": name,
                "color": ev(g["color"]) if "color" in g else None,
                "processes": [{
                    "name": ev(p["name"]),
                    "location": ev(p["location"]) if "location" in p else None,
                    "where": p["line"]} for p in g["processes"]]})
        return out_sets, out_groups

    def _write_system_fields(self, system: str, line: int, **kwargs):
        result = self.bridge.set_system_fields(system, **kwargs)
        self._emit("set_system_fields", result)
        if "error" in result:
            self._fields_error(result, line)
        for c in result.get("changes", []):
            self.out.write(f"    {c}")
        if any("analysis group" in c or "parameter set" in c
               for c in result.get("changes", [])):
            # an open result of this system no longer matches it
            self._system_changed(result.get("system_id", ""))
        return result


    def _exec_edit_system(self, stmt: EditSystemStmt):
        self._require_bridge(stmt.line)
        target = self._eval_str(stmt.target)
        sets, groups = self._system_specs(stmt.parameter_sets,
                                          stmt.analysis_groups)
        kwargs: Dict[str, Any] = {}
        if sets:
            kwargs["parameter_sets"] = sets
        if groups:
            kwargs["analysis_groups"] = groups
        if stmt.remove_parameter_sets:
            kwargs["remove_parameter_sets"] = [
                self._eval_str(e) for e, _ in stmt.remove_parameter_sets]
        if stmt.remove_analysis_groups:
            kwargs["remove_analysis_groups"] = [
                self._eval_str(e) for e, _ in stmt.remove_analysis_groups]
        if stmt.set_description is not None:
            kwargs["description"] = self._eval_str(stmt.set_description)
        if not kwargs:
            self.out.write(f"  Nothing to change in '{target}'.")
            return
        self.out.write(f"  Edited system: {target}")
        self._write_system_fields(target, stmt.line, **kwargs)

    def _run_stored_scenarios(self, stmt, system: str, method: str):
        self.out.write("  Running the parameter sets stored on the "
                       "system...")
        result = self.bridge.run_parameter_sets(
            system, method, stmt.allocation or None)
        self._emit("run_parameter_sets", result)
        if "error" in result:
            raise BasicError(result["error"], stmt.line)
        self.runtime.store_results(result, "scenarios")
        self.out.write(format_scenarios(result))

    # ── SHOW ─────────────────────────────────────────────────

    def _show_process_fields(self, process_id: str, part: str, line: int):
        result = self.bridge.get_process_fields(process_id)
        self._emit("get_process_fields", result)
        if "error" in result:
            raise BasicError(result["error"], line)
        self.out.write(format_process_fields(result, part))

    def _show_system_fields(self, ref: str, part: str, line: int):
        result = self.bridge.get_system_fields(ref)
        self._emit("get_system_fields", result)
        if "error" in result:
            raise BasicError(result["error"], line)
        self.out.write(format_system_fields(result, part))
