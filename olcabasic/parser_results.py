"""
Parsing for results that stay open: the extra words on CALCULATE, the
RESULT family and CLOSE RESULT.

Part of olcabasic.parser.Parser.
"""

from .ast_nodes import CalculateStmt, CloseResultStmt, ResultQueryStmt
from .tokeniser import TokenType

# The words that may follow RESULT, for the "is this a RESULT command"
# test in parse_statement (RESULT is not a reserved word).
RESULT_HEADS = ("IMPACTS", "CATEGORIES", "PROCESSES", "DEMAND", "FLOWS",
                "FLOW", "CONTRIBUTION", "FACTORS", "INTENSITY", "SCALING",
                "TOTALITY", "REQUIREMENTS", "TREE", "COSTS", "NORMALISED",
                "NORMALIZED", "WEIGHTED", "SANKEY")

RESULT_FORMS = """\
RESULT IMPACTS [CATEGORY "x"]
RESULT IMPACTS BY GROUP [CATEGORY "x"]
RESULT IMPACTS BY TAG CATEGORY "x"
RESULT CATEGORIES | PROCESSES | DEMAND
RESULT FLOWS [FLOW "y"] | FLOWS LIST
RESULT FLOWS OF PROCESS "x" [DIRECT] [FLOW "y"]
RESULT FLOWS BY GROUP FLOW "y" | FLOWS BY TAG FLOW "y"
RESULT FLOW "y" BY PROCESS
RESULT CONTRIBUTION BY PROCESS [DIRECT] [CATEGORY "x"]
RESULT CONTRIBUTION OF PROCESS "x" [DIRECT] [CATEGORY "y"]
RESULT CONTRIBUTION BY FLOW [CATEGORY "x" [FLOW "y"]]
RESULT FACTORS CATEGORY "x" [FLOW "y"]
RESULT INTENSITY OF PROCESS "x" [CATEGORY "y" | FLOWS | FLOW "y"]
RESULT SCALING [OF PROCESS "x" [UNSCALED]]
RESULT TOTALITY [OF PROCESS "x"]
RESULT REQUIREMENTS [OF PROCESS "x"]
RESULT TREE CATEGORY "x" | FLOW "y" | COSTS [LEVELS n] [TOP n]
RESULT COSTS [BY PROCESS | BY GROUP | BY TAG | TREE]
RESULT COSTS OF PROCESS "x" [DIRECT]
RESULT COSTS INTENSITY OF PROCESS "x"
RESULT NORMALISED | WEIGHTED
RESULT SANKEY CATEGORY "x" | FLOW "y" [MIN SHARE n%] [MAX NODES n]
Every form can end with: [IN name] [TOP n] [SAVE "file.csv"]
A process can be narrowed with LOCATION "code" or PRODUCT "flow"; a flow
with IN "compartment" straight after its name."""


class ResultsParserMixin:

    # ── CALCULATE options ────────────────────────────────────

    def parse_calculate(self, line: int) -> CalculateStmt:
        from .parser import ParseError
        self.advance()  # consume CALCULATE
        if self.at_word("PROJECT"):
            return self.parse_calculate_project(line)
        system = self.parse_string_or_expr()
        self.expect_keyword("USING")
        method = self.parse_string_or_expr()
        stmt = CalculateStmt(line=line, system=system, method=method)
        while self.peek().type in (TokenType.KEYWORD, TokenType.IDENTIFIER):
            if self.match_keyword("ALLOCATE"):
                stmt.allocation = self.parse_allocation()
            elif self.match_word("AMOUNT"):
                stmt.amount = self.parse_expr()
                if self.peek().type == TokenType.COMMA:
                    self.advance()
                if self.peek().type not in (TokenType.IDENTIFIER,
                                            TokenType.KEYWORD):
                    raise ParseError(
                        "AMOUNT needs a unit.", line,
                        hint="For example: AMOUNT 2.5 kg")
                stmt.unit = self.parse_unit()
                if self.match_keyword("PROPERTY"):
                    stmt.flow_property = self.parse_string_or_expr()
            elif self.match_keyword("WITH"):
                if self.match_word("COSTS"):
                    stmt.with_costs = True
                elif self.match_word("REGIONALISATION", "REGIONALIZATION"):
                    stmt.with_regionalisation = True
                else:
                    raise ParseError(
                        f"WITH '{self.peek().value}' is not something "
                        f"CALCULATE can do.", line,
                        hint="Use WITH COSTS or WITH REGIONALISATION.")
            elif self.at_word("NW"):
                self.advance()
                if not self.match_keyword("SET"):
                    raise ParseError("Expected NW SET \"name\".", line)
                stmt.nw_set = self.parse_string_or_expr()
            elif (self.at_word("PARAMETER")
                  and self.peek_at(1).upper() == "SET"):
                self.advance()
                self.advance()
                stmt.parameter_set = self.parse_string_or_expr()
            elif self.at_word("IGNORE"):
                self.advance()
                if not self.match_word("FACTORS"):
                    raise ParseError(
                        "Expected IGNORE FACTORS \"flow name\".", line)
                stmt.ignore_factors.append(self.parse_string_or_expr())
                while self.peek().type == TokenType.COMMA:
                    self.advance()
                    stmt.ignore_factors.append(self.parse_string_or_expr())
            elif self.match_keyword("AS"):
                tok = self.peek()
                if tok.type != TokenType.IDENTIFIER:
                    raise ParseError(
                        "AS needs a name for the result: a plain word, "
                        "not a reserved word or a string.", line,
                        hint="For example: CALCULATE \"system\" USING "
                             "\"method\" AS base")
                stmt.result_name = self.advance().value
            else:
                break
        self.expect_newline()
        stmt.defaulted = self._defaulted(ALLOCATE=stmt.allocation)
        return stmt

    # ── CLOSE RESULT ─────────────────────────────────────────

    def parse_close_result(self, line: int) -> CloseResultStmt:
        self.advance()  # CLOSE
        self.advance()  # RESULT
        stmt = CloseResultStmt(line=line)
        tok = self.peek()
        if tok.type in (TokenType.IDENTIFIER, TokenType.KEYWORD):
            word = self.advance().value
            if word.upper() == "ALL":
                stmt.all = True
            else:
                stmt.name = word
        self.expect_newline()
        return stmt

    # ── RESULT ... ───────────────────────────────────────────

    def _result_error(self, message: str, line: int):
        from .parser import ParseError
        return ParseError(message, line,
                          hint="HELP RESULT lists every form.")

    def parse_result_query(self, line: int) -> ResultQueryStmt:
        """RESULT <head> [modifiers]. The modifiers are read in any
        order, then checked against the forms each head allows."""
        start = self.pos
        self.advance()  # RESULT
        head = self.advance().upper()
        if head == "NORMALIZED":
            head = "NORMALISED"
        m = {}            # what the line said
        stmt = ResultQueryStmt(line=line)

        def process_selectors():
            while True:
                if self.match_keyword("LOCATION"):
                    m["location"] = self.parse_string_or_expr()
                elif self.at_keyword("PRODUCT"):
                    self.advance()
                    m["product"] = self.parse_string_or_expr()
                else:
                    break

        def flow_name():
            m["flow"] = self.parse_string_or_expr()
            if (self.at_keyword("IN")
                    and self.peek_at(1).type == TokenType.STRING):
                self.advance()
                m["compartment"] = self.parse_string_or_expr()

        if head == "FLOW":
            # RESULT FLOW "x" BY PROCESS
            flow_name()

        while self.peek().type in (TokenType.KEYWORD, TokenType.IDENTIFIER):
            if self.match_keyword("BY"):
                if self.at_keyword("PROCESS", "FLOW"):
                    m["by"] = self.advance().upper()
                elif self.at_word("GROUP", "TAG"):
                    m["by"] = self.advance().upper()
                else:
                    raise self._result_error(
                        "BY must be followed by PROCESS, FLOW, GROUP or "
                        "TAG.", line)
            elif self.at_word("OF"):
                self.advance()
                if not self.match_keyword("PROCESS"):
                    raise self._result_error(
                        "Expected OF PROCESS \"name\".", line)
                m["process"] = self.parse_string_or_expr()
                process_selectors()
            elif self.match_keyword("CATEGORY"):
                m["category"] = self.parse_string_or_expr()
            elif self.match_keyword("FLOW"):
                flow_name()
            elif self.match_keyword("FLOWS"):
                m["flows"] = True
            elif self.match_keyword("LIST"):
                m["list"] = True
            elif self.match_word("DIRECT"):
                m["direct"] = True
            elif self.match_word("UNSCALED"):
                m["unscaled"] = True
            elif self.match_word("COSTS"):
                m["costs"] = True
            elif self.match_word("INTENSITY"):
                m["intensity"] = True
            elif self.match_keyword("TREE"):
                m["tree"] = True
            elif self.match_word("LEVELS"):
                m["levels"] = self.parse_int("LEVELS")
            elif self.match_keyword("TOP"):
                stmt.top = self.parse_int("TOP")
                if stmt.top < 1:
                    raise self._result_error("TOP needs a number above 0.",
                                             line)
            elif self.at_word("MIN"):
                self.advance()
                if not self.match_word("SHARE"):
                    raise self._result_error("Expected MIN SHARE n%.", line)
                m["min_share"] = self._percent("MIN SHARE") / 100.0
            elif self.at_keyword("MAX"):
                self.advance()
                if not self.match_word("NODES"):
                    raise self._result_error("Expected MAX NODES n.", line)
                m["max_nodes"] = self.parse_int("MAX NODES")
            elif self.match_keyword("SAVE"):
                stmt.save = self.parse_string_or_expr()
            elif self.match_keyword("IN"):
                tok = self.peek()
                if tok.type != TokenType.IDENTIFIER:
                    raise self._result_error(
                        "IN needs the name the result was given with "
                        "CALCULATE ... AS name.", line)
                stmt.result_name = self.advance().value
            elif self.at_keyword("LOCATION", "PRODUCT") and "process" in m:
                process_selectors()
            else:
                break
        words = " ".join(t.value for t in self.tokens[start:self.pos])
        self.expect_newline()

        stmt.words = words
        stmt.query, stmt.args = self._result_form(head, m, stmt, line)
        return stmt

    def _result_form(self, head: str, m: dict, stmt, line: int):
        """Check the modifiers against the head and name the query."""
        def only(*allowed):
            extra = [k for k in m if k not in allowed]
            if extra:
                word = {"by": "BY " + str(m.get("by", "")),
                        "process": "OF PROCESS", "list": "LIST",
                        "flows": "FLOWS", "tree": "TREE",
                        "min_share": "MIN SHARE", "max_nodes": "MAX NODES",
                        "compartment": "IN \"compartment\""}.get(
                            extra[0], extra[0].upper())
                raise self._result_error(
                    f"RESULT {head} does not take {word}.", line)

        def need(key, what):
            if key not in m:
                raise self._result_error(
                    f"RESULT {head} needs {what}.", line)

        sel = ("location", "product")
        args = {k: m[k] for k in ("category", "flow", "compartment",
                                  "process", "location", "product")
                if k in m}
        by = m.get("by")

        if head == "IMPACTS":
            if by == "GROUP":
                only("by", "category")
                return "impacts_by_group", args
            if by == "TAG":
                only("by", "category")
                need("category", "CATEGORY \"name\" with BY TAG")
                return "impacts_by_tag", args
            only("category")
            return "impacts", args
        if head in ("CATEGORIES", "PROCESSES", "DEMAND", "NORMALISED",
                    "WEIGHTED"):
            only()
            return head.lower(), {}
        if head == "FLOWS":
            if m.get("list"):
                only("list")
                return "flows_list", {}
            if by in ("GROUP", "TAG"):
                only("by", "flow", "compartment")
                need("flow", f"FLOW \"name\" with BY {by}")
                return "flows_by_" + by.lower(), args
            only("process", "direct", "flow", "compartment", *sel)
            if m.get("direct"):
                args["direct"] = True
            return "flows", args
        if head == "FLOW":
            only("by", "flow", "compartment")
            if by != "PROCESS":
                raise self._result_error(
                    "Expected RESULT FLOW \"name\" BY PROCESS.", line)
            return "flow_by_process", args
        if head == "CONTRIBUTION":
            if by == "FLOW":
                only("by", "category", "flow", "compartment")
                return "contribution_flow", args
            if by == "PROCESS" or "process" in m:
                if by == "PROCESS" and "process" in m:
                    raise self._result_error(
                        "Use BY PROCESS (every process) or OF PROCESS "
                        "\"name\" (one of them), not both.", line)
                only("by", "process", "direct", "category", *sel)
                if m.get("direct"):
                    args["direct"] = True
                return "contribution_process", args
            raise self._result_error(
                "RESULT CONTRIBUTION needs BY PROCESS, BY FLOW or OF "
                "PROCESS \"name\".", line)
        if head == "FACTORS":
            only("category", "flow", "compartment")
            need("category", "CATEGORY \"name\"")
            return "factors", args
        if head == "INTENSITY":
            only("process", "category", "flows", "flow", "compartment", *sel)
            need("process", "OF PROCESS \"name\"")
            if m.get("flows"):
                args["flows"] = True
            if sum(k in m for k in ("category", "flows", "flow")) > 1:
                raise self._result_error(
                    "RESULT INTENSITY takes one of CATEGORY \"name\", "
                    "FLOWS or FLOW \"name\".", line)
            return "intensity", args
        if head == "SCALING":
            only("process", "unscaled", *sel)
            if m.get("unscaled"):
                args["unscaled"] = True
            return "scaling", args
        if head in ("TOTALITY", "REQUIREMENTS"):
            only("process", *sel)
            return head.lower(), args
        if head == "TREE":
            only("category", "flow", "compartment", "costs", "levels")
            if sum(k in m for k in ("category", "flow", "costs")) != 1:
                raise self._result_error(
                    "RESULT TREE takes one of CATEGORY \"name\", FLOW "
                    "\"name\" or COSTS.", line)
            if m.get("costs"):
                args["costs"] = True
            if "levels" in m:
                args["levels"] = m["levels"]
            if stmt.top:
                args["top"] = stmt.top
                stmt.top = 0          # TOP limits each level of a tree
            return "tree", args
        if head == "COSTS":
            if m.get("tree"):
                only("tree", "levels")
                args = {"costs": True}
                if "levels" in m:
                    args["levels"] = m["levels"]
                if stmt.top:
                    args["top"] = stmt.top
                    stmt.top = 0
                return "tree", args
            only("by", "process", "direct", "intensity", *sel)
            if by:
                if by == "FLOW":
                    raise self._result_error(
                        "RESULT COSTS takes BY PROCESS, BY GROUP or BY "
                        "TAG.", line)
                only("by")
                args["by"] = by.lower()
                return "costs", args
            if m.get("intensity") or m.get("direct"):
                need("process", "OF PROCESS \"name\"")
            if m.get("intensity") and m.get("direct"):
                raise self._result_error(
                    "Use DIRECT or INTENSITY, not both.", line)
            for flag in ("direct", "intensity"):
                if m.get(flag):
                    args[flag] = True
            return "costs", args
        if head == "SANKEY":
            only("category", "flow", "compartment", "min_share", "max_nodes")
            if sum(k in m for k in ("category", "flow")) != 1:
                raise self._result_error(
                    "RESULT SANKEY takes CATEGORY \"name\" or FLOW "
                    "\"name\".", line)
            for k in ("min_share", "max_nodes"):
                if k in m:
                    args[k] = m[k]
            return "sankey", args
        raise self._result_error(f"RESULT {head} is not a result query.",
                                 line)
