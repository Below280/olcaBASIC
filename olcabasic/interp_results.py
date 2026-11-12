"""
Results that stay open, in the language: CALCULATE keeps its result,
RESULT reads from it, CLOSE RESULT disposes it.

Part of olcabasic.interpreter.Interpreter.
"""

import json
from typing import Dict, Optional

from .ast_nodes import CalculateStmt, CloseResultStmt, Expr, ResultQueryStmt
from .errors import BasicError
from .formatting import format_impacts, format_query, query_to_csv

CURRENT = ""          # the name of the current (unnamed) result


class ResultsInterpMixin:

    # ── the open results of this session ─────────────────────

    def _max_open_results(self) -> int:
        return self.bridge.MAX_OPEN_RESULTS

    @staticmethod
    def _result_label(name: str) -> str:
        return name or "the current result"

    def _close_result(self, name: str) -> bool:
        info = self.runtime.open_results.pop(name, None)
        if info is None:
            return False
        if self.bridge is not None and self.bridge.connected:
            self.bridge.close_result(info["handle"])
        return True

    def close_results(self) -> int:
        """Dispose every open result of this session (RESET, the end of
        a program run from a file, leaving the interpreter)."""
        names = list(self.runtime.open_results)
        for name in names:
            self._close_result(name)
        return len(names)

    def _system_changed(self, system_id: str):
        """A stored product system, or a process in it, was changed: a
        result of it that is still open shows the model as it was, so
        it is closed."""
        if not system_id or self.bridge is None:
            return
        desc = self.bridge.find_system(system_id)
        if desc is None:
            return
        for name, info in list(self.runtime.open_results.items()):
            if info.get("system") == desc.name:
                self._close_result(name)
                self.out.write(
                    f"  Closed {self._result_label(name)}: it was "
                    f"calculated before '{desc.name}' changed.")

    def _open_result_info(self, name: str, line: int) -> Dict:
        info = self.runtime.open_results.get(name)
        if info is not None:
            return info
        others = [n for n in self.runtime.open_results if n]
        if name:
            listed = (", ".join(others) if others else "none")
            raise BasicError(
                f"No open result is called '{name}'.", line,
                hint=f"Named results that are open: {listed}. A result is "
                     f"named when it is calculated: CALCULATE \"system\" "
                     f"USING \"method\" AS {name}.")
        hint = ('CALCULATE "system" USING "method" first; its result '
                'stays open for RESULT queries.')
        if others:
            hint = (f"Named results are open ({', '.join(others)}): add IN "
                    f"name to the RESULT line, or CALCULATE again.")
        raise BasicError("No result is open.", line, hint=hint)

    def _current_handle(self) -> Optional[str]:
        info = self.runtime.open_results.get(CURRENT)
        return info["handle"] if info else None

    # ── CALCULATE ────────────────────────────────────────────

    def _exec_calculate(self, stmt: CalculateStmt):
        self._require_bridge(stmt.line)
        system = self._eval_str(stmt.system)
        method = self._method(self._eval_str(stmt.method), stmt.line)
        if stmt.ignore_factors:
            self._accept_no_factors(
                [self._eval_str(e) for e in stmt.ignore_factors], method,
                stmt.line)
        self._require_valid(system, stmt.line, "CALCULATE", method=method,
                            allocation=stmt.allocation)
        self._defaults(stmt)
        name = stmt.result_name
        if name.upper() == "ALL":
            raise BasicError(
                "A result cannot be called ALL: CLOSE RESULT ALL closes "
                "every result.", stmt.line, hint="Choose another name.")

        amount = None
        if stmt.amount is not None:
            amount = self._eval(stmt.amount)
            if not isinstance(amount, (int, float)) or isinstance(amount, bool):
                raise BasicError("AMOUNT must be a number.", stmt.line)
            if amount <= 0:
                raise BasicError(
                    f"AMOUNT must be above zero (got {amount}).", stmt.line)
        options = dict(
            allocation=stmt.allocation or None,
            amount=amount, unit=stmt.unit or None,
            flow_property=(self._eval_str(stmt.flow_property)
                           if stmt.flow_property is not None else None),
            with_costs=stmt.with_costs,
            with_regionalisation=stmt.with_regionalisation,
            nw_set=(self._eval_str(stmt.nw_set)
                    if stmt.nw_set is not None else None),
            parameter_set=(self._eval_str(stmt.parameter_set)
                           if stmt.parameter_set is not None else None))
        self._before_calculate(stmt, system, method)

        # The result this one replaces goes first, so it does not count
        # towards the limit.
        self._close_result(name)
        open_now = self.runtime.open_results
        if len(open_now) >= self._max_open_results():
            listed = ", ".join(self._result_label(n) for n in open_now)
            raise BasicError(
                f"{len(open_now)} results are open already, which is the "
                f"most a session holds: {listed}.", stmt.line,
                hint="CLOSE RESULT name closes one of them; CLOSE RESULT "
                     "ALL closes them all.")

        self.out.write(f"  Calculating: {system} using {method}...")
        result = self.bridge.open_result(system, method, **options)
        if "error" in result:
            self._emit("calculate", result)
            raise BasicError(result["error"], stmt.line,
                             hint=result.get("hint", ""))
        open_now[name] = {"handle": result.pop("handle"),
                          "system": result["system"],
                          "method": result["method"], "line": stmt.line}
        result["open_as"] = name or "(current)"
        self._emit("calculate", result)
        self.runtime.store_results(result, "calculate")
        self.out.write(format_impacts(result))
        if name:
            self.out.write(f"  Result kept open as: {name}")
        elif "RESULT OPEN" not in self.runtime.defaults_shown:
            self.runtime.defaults_shown.add("RESULT OPEN")
            self.out.write(
                "  NOTE: the result stays open until the next CALCULATE or "
                "CLOSE RESULT. RESULT reads more from it without "
                "calculating again (HELP RESULT).")

    def _before_calculate(self, stmt, system: str, method: str):
        """Checks that need the model, before openLCA calculates.
        (The rules of job 2 hook in here.)"""

    # ── CLOSE RESULT ─────────────────────────────────────────

    def _exec_close_result(self, stmt: CloseResultStmt):
        if stmt.all:
            n = self.close_results()
            self.out.write(f"  Closed {n} result{'s' if n != 1 else ''}.")
            return
        if stmt.name and stmt.name not in self.runtime.open_results:
            self._open_result_info(stmt.name, stmt.line)      # raises
        if self._close_result(stmt.name):
            self.out.write(f"  Closed {self._result_label(stmt.name)}.")
        else:
            self.out.write("  No result is open.")

    # ── RESULT ... ───────────────────────────────────────────

    def _exec_result_query(self, stmt: ResultQueryStmt):
        self._require_bridge(stmt.line)
        info = self._open_result_info(stmt.result_name, stmt.line)
        args = {}
        for key, value in stmt.args.items():
            if isinstance(value, Expr):
                value = self._eval_str(value)
            args[key] = value
        result = self.bridge.result_query(info["handle"], stmt.query, **args)
        if "error" in result:
            raise BasicError(result["error"], stmt.line,
                             hint=result.get("hint", ""))
        result["result"] = stmt.result_name or "(current)"
        self._cut(result, stmt.top)
        self._emit("result_query", result)
        self.runtime.store_results(result, "query")
        self.out.write(format_query(result))
        if stmt.save is not None:
            self._save_query(result, self._eval_str(stmt.save), stmt.line)

    @staticmethod
    def _cut(result: Dict, top: int):
        """Order the rows (largest first, where amounts can be compared)
        and keep the TOP n."""
        rows = result.get("rows", [])
        key = result.get("sort_by") or (
            "amount" if "amount" in result.get("columns", []) else None)
        ordered = key is not None and not result.get("keep_order")
        within = result.get("rank_within")
        total = len(rows)

        def size(row):
            v = row.get(key)
            return abs(v) if isinstance(v, (int, float)) else 0.0

        if within:
            groups: Dict[str, list] = {}
            for row in rows:
                groups.setdefault(row.get(within, ""), []).append(row)
            rows = []
            for group in groups.values():
                if ordered:
                    group.sort(key=size, reverse=True)
                rows.extend(group[:top] if top else group)
        else:
            if ordered:
                rows = sorted(rows, key=size, reverse=True)
            if top:
                rows = rows[:top]
        result["rows"] = rows
        result["row_count"] = total
        if top:
            result["top"] = top

    def _save_query(self, result: Dict, filename: str, line: int):
        if filename.lower().endswith(".json"):
            text = json.dumps(result, indent=1)
        else:
            if result.get("query") == "sankey":
                raise BasicError(
                    "Sankey data is nodes and links, which a table "
                    "cannot hold.", line,
                    hint="Save it as JSON: SAVE \"file.json\".")
            text = query_to_csv(result)
        with open(filename, "w", newline="", encoding="utf-8") as f:
            f.write(text)
        self.out.write(f"  Saved to {filename}")
