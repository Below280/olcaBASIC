"""
Parsing for the wider fields of processes, flows and product systems:
uncertainty, avoided products, costs, exchange sites, allocation
factors, documentation, social aspects, process type, parameter sets
and analysis groups.

Part of olcabasic.parser.Parser.
"""

from .ast_nodes import EditSystemStmt, NumberLiteral
from .tokeniser import TokenType

UNCERTAINTY_COUNTS = {"LOGNORMAL": 2, "NORMAL": 2, "TRIANGLE": 3,
                      "UNIFORM": 2}
UNCERTAINTY_HINT = ("UNCERTAINTY LOGNORMAL gm, gsd | NORMAL mean, sd | "
                    "TRIANGLE min, mode, max | UNIFORM min, max")

# Words that start an extra on an INPUT or OUTPUT line.
EXCHANGE_EXTRA_WORDS = ("UNCERTAINTY", "BASE", "AVOIDED", "COST", "SITE")

# DOCUMENT block: the words of each line -> (field, kind). Longer word
# sequences come first so that DATA COLLECTION is not read as DATA.
DOCUMENT_LINES = [
    (("DATA", "COLLECTION"), "data_collection_description", "text"),
    (("DATA", "SELECTION"), "data_selection_description", "text"),
    (("DATA", "TREATMENT"), "data_treatment_description", "text"),
    (("INTENDED", "APPLICATION"), "intended_application", "text"),
    (("INVENTORY", "METHOD"), "inventory_method_description", "text"),
    (("MODELLING", "CONSTANTS"), "modeling_constants_description", "text"),
    (("MODELING", "CONSTANTS"), "modeling_constants_description", "text"),
    (("USE", "ADVICE"), "use_advice", "text"),
    (("VALID", "FROM"), "valid_from", "date"),
    (("VALID", "UNTIL"), "valid_until", "date"),
    (("FLOW", "COMPLETENESS"), "flow_completeness", "aspect"),
    (("COMPLETENESS",), "completeness_description", "text"),
    (("CREATED",), "creation_date", "date"),
    (("DOCUMENTOR",), "data_documentor", "actor"),
    (("GENERATOR",), "data_generator", "actor"),
    (("OWNER",), "data_set_owner", "actor"),
    (("GEOGRAPHY",), "geography_description", "text"),
    (("COPYRIGHT",), "is_copyright_protected", "bool"),
    (("PROJECT",), "project_description", "text"),
    (("PUBLICATION",), "publication", "source"),
    (("RESTRICTIONS",), "restrictions_description", "text"),
    (("SAMPLING",), "sampling_description", "text"),
    (("SOURCE",), "sources", "sources"),
    (("TECHNOLOGY",), "technology_description", "text"),
    (("TIME",), "time_description", "text"),
    (("REVIEW",), "reviews", "review"),
    (("COMPLIANCE",), "compliance_declarations", "compliance"),
]

DOCUMENT_HELP = (
    "COMPLETENESS, COMPLIANCE, COPYRIGHT YES|NO, CREATED, DATA COLLECTION, "
    "DATA SELECTION, DATA TREATMENT, DOCUMENTOR, FLOW COMPLETENESS, "
    "GENERATOR, GEOGRAPHY, INTENDED APPLICATION, INVENTORY METHOD, "
    "MODELLING CONSTANTS, OWNER, PROJECT, PUBLICATION, RESTRICTIONS, "
    "REVIEW, SAMPLING, SOURCE, TECHNOLOGY, TIME, USE ADVICE, VALID FROM, "
    "VALID UNTIL")

SOCIAL_MODIFIERS = ("ACTIVITY", "COMMENT", "SOURCE", "QUALITY")


class FieldsParserMixin:

    def _err(self, message, line=None, hint=""):
        from .parser import ParseError
        return ParseError(message, line or self.current_line(), hint=hint)

    def _end_of_line(self) -> bool:
        return self.peek().type in (TokenType.NEWLINE, TokenType.EOF,
                                    TokenType.COMMENT)

    def _yes_no(self, what: str) -> bool:
        """YES or NO; nothing after the word means YES."""
        if self.match_word("YES"):
            return True
        if self.match_word("NO"):
            return False
        if self._end_of_line():
            return True
        raise self._err(f"{what} takes YES or NO.")

    # ── uncertainty ──────────────────────────────────────────

    def parse_uncertainty(self):
        """After the word UNCERTAINTY: a distribution and its numbers,
        or NONE to remove one."""
        line = self.current_line()
        if self.at_keyword("NONE"):
            self.advance()
            return None
        tok = self.peek()
        kind = tok.upper() if tok.type in (TokenType.IDENTIFIER,
                                           TokenType.KEYWORD) else ""
        if kind == "LOG" and self.peek_at(1).upper() == "NORMAL":
            self.advance()
            kind = "LOGNORMAL"
        if kind not in UNCERTAINTY_COUNTS:
            raise self._err(
                f"UNCERTAINTY needs a distribution, not '{tok.value}'.",
                line, hint=UNCERTAINTY_HINT)
        self.advance()
        values = []
        for i in range(UNCERTAINTY_COUNTS[kind]):
            if i and self.peek().type == TokenType.COMMA:
                self.advance()
            if self._end_of_line():
                raise self._err(
                    f"UNCERTAINTY {kind} takes "
                    f"{UNCERTAINTY_COUNTS[kind]} numbers.", line,
                    hint=UNCERTAINTY_HINT)
            values.append(self.parse_add_expr())
        return {"kind": kind, "values": values, "line": line}

    # ── extras on an exchange line ───────────────────────────

    def at_exchange_extra(self) -> bool:
        return (self.at_word(*EXCHANGE_EXTRA_WORDS)
                or (self.at_keyword("NOT")
                    and self.peek_at(1).upper() == "AVOIDED")
                or (self.at_word("NO")
                    and self.peek_at(1).upper() in ("COST", "SITE")))

    def parse_exchange_extra(self, extras: dict):
        """One of UNCERTAINTY, BASE UNCERTAINTY, AVOIDED, COST, SITE
        (and their removals, for EDIT): into the extras dict."""
        line = self.current_line()
        if self.match_word("UNCERTAINTY"):
            extras["uncertainty"] = self.parse_uncertainty()
        elif self.match_word("BASE"):
            if not self.match_word("UNCERTAINTY"):
                raise self._err("Expected BASE UNCERTAINTY n.", line)
            extras["base_uncertainty"] = self.parse_add_expr()
        elif self.match_word("AVOIDED"):
            extras["avoided"] = True
        elif self.at_keyword("NOT"):
            self.advance()
            self.advance()
            extras["avoided"] = False
        elif self.match_word("NO"):
            what = self.advance().upper()
            extras["cost" if what == "COST" else "site"] = None
        elif self.match_word("COST"):
            cost = {"line": line}
            if self.match_keyword("FORMULA"):
                cost["formula"] = self.parse_string_or_expr()
            else:
                cost["value"] = self.parse_add_expr()
                if self.match_keyword("FORMULA"):
                    cost["formula"] = self.parse_string_or_expr()
            if not self.match_word("CURRENCY"):
                raise self._err(
                    "COST needs a currency.", line,
                    hint="For example: COST 12.5 CURRENCY \"EUR\"")
            cost["currency"] = self.parse_string_or_expr()
            extras["cost"] = cost
        elif self.match_word("SITE"):
            extras["site"] = self.parse_string_or_expr()

    # ── lines of a PROCESS or EDIT PROCESS block ─────────────

    PROCESS_FIELD_WORDS = ("ALLOCATION", "DEFAULT", "DOCUMENT", "SOCIAL",
                           "TYPE", "INFRASTRUCTURE")

    def at_process_field(self) -> bool:
        if self.at_word(*self.PROCESS_FIELD_WORDS):
            return True
        return (self.at_keyword("PROCESS")
                and self.peek_at(1).upper() == "PEDIGREE")

    def parse_process_field(self, fields: dict):
        """One field line or block of a process, into the fields dict."""
        line = self.current_line()
        if self.match_word("ALLOCATION"):
            self._parse_allocation_block(fields, line)
        elif self.match_word("DEFAULT"):
            if not self.match_word("ALLOCATION"):
                raise self._err("Expected DEFAULT ALLOCATION PHYSICAL, "
                                "ECONOMIC, CAUSAL or NONE.", line)
            tok = self.peek()
            if tok.upper() not in ("PHYSICAL", "ECONOMIC", "CAUSAL", "NONE"):
                raise self._err(
                    f"DEFAULT ALLOCATION '{tok.value}' is not a method.",
                    line, hint="Use PHYSICAL, ECONOMIC, CAUSAL or NONE.")
            fields["default_allocation"] = (self.advance().upper(), line)
            self.expect_newline()
        elif self.match_word("DOCUMENT"):
            self._parse_document_block(fields, line)
        elif self.match_word("SOCIAL"):
            if self.match_word("SCHEMA"):
                fields["social_schema"] = (self.parse_string_or_expr(), line)
            else:
                fields.setdefault("social", []).append(
                    self._parse_social(line))
            self.expect_newline()
        elif self.match_word("TYPE"):
            if self.match_word("UNIT"):
                self.match_keyword("PROCESS")
                fields["type"] = ("UNIT", line)
            elif self.match_word("LCI"):
                if not self.match_word("RESULT"):
                    raise self._err("Expected TYPE LCI RESULT.", line)
                fields["type"] = ("LCI_RESULT", line)
            else:
                raise self._err(
                    f"TYPE '{self.peek().value}' is not a process type.",
                    line, hint="Use TYPE UNIT or TYPE LCI RESULT.")
            self.expect_newline()
        elif self.match_word("INFRASTRUCTURE"):
            fields["infrastructure"] = (self._yes_no("INFRASTRUCTURE"), line)
            self.expect_newline()
        elif self.at_keyword("PROCESS"):
            self.advance()
            self.advance()      # PEDIGREE
            ped = self.parse_pedigree()
            fields["process_pedigree"] = (
                ped if isinstance(ped, str)
                else "(" + ";".join(str(n) for n in ped) + ")", line)
            self.expect_newline()

    def _parse_allocation_block(self, fields: dict, line: int):
        tok = self.peek()
        kind = tok.upper()
        if kind not in ("PHYSICAL", "ECONOMIC", "CAUSAL"):
            raise self._err(
                f"ALLOCATION '{tok.value}' is not a set of factors."
                if not self._end_of_line() else "ALLOCATION needs a method.",
                line, hint="Start the block with ALLOCATION PHYSICAL, "
                           "ALLOCATION ECONOMIC or ALLOCATION CAUSAL.")
        self.advance()
        self.expect_newline()
        self.skip_newlines()
        entries = []
        while not self.at_end_of("ALLOCATION"):
            tok = self.peek()
            if tok.type == TokenType.EOF or self.at_keyword("END"):
                raise self._err("ALLOCATION block missing END ALLOCATION",
                                line)
            ln = tok.line
            entry = {"product": self.parse_string_or_expr(), "line": ln}
            if self.peek().type == TokenType.COMMA:
                self.advance()
            if self.match_keyword("FORMULA"):
                entry["formula"] = self.parse_string_or_expr()
            else:
                entry["value"] = self.parse_add_expr()
            if self.match_keyword("FOR"):
                if not self.at_keyword("INPUT", "OUTPUT"):
                    raise self._err(
                        "Expected FOR INPUT \"flow\" or FOR OUTPUT "
                        "\"flow\".", ln)
                ex = {"direction": self.advance().upper(),
                      "name": self.parse_string_or_expr()}
                if self.match_word("INDEX"):
                    ex["index"] = self.parse_int("INDEX")
                entry["exchange"] = ex
            entries.append(entry)
            self.expect_newline()
            self.skip_newlines()
        self.advance()
        self.advance()      # END ALLOCATION
        self.expect_newline()
        blocks = fields.setdefault("allocation", [])
        if any(b["type"] == kind for b in blocks):
            raise self._err(f"There are two ALLOCATION {kind} blocks.", line,
                            hint="Put every factor of a method in one "
                                 "block.")
        blocks.append({"type": kind, "line": line, "entries": entries})

    def _parse_document_block(self, fields: dict, line: int):
        self.expect_newline()
        self.skip_newlines()
        doc = fields.setdefault("document", [])
        while not self.at_end_of("DOCUMENT"):
            tok = self.peek()
            if tok.type == TokenType.EOF or self.at_keyword("END"):
                raise self._err("DOCUMENT block missing END DOCUMENT", line)
            ln = tok.line
            for words, field_name, kind in DOCUMENT_LINES:
                if all(self.peek_at(i).upper() == w
                       and self.peek_at(i).type in (TokenType.KEYWORD,
                                                    TokenType.IDENTIFIER)
                       for i, w in enumerate(words)):
                    for _ in words:
                        self.advance()
                    break
            else:
                raise self._err(
                    f"'{tok.value}' is not a documentation field.", ln,
                    hint="The fields are: " + DOCUMENT_HELP + ".")
            if kind == "bool":
                value = self._yes_no("COPYRIGHT")
            elif kind == "aspect":
                value = (self.parse_string_or_expr(),
                         self.parse_string_or_expr())
            elif kind == "review":
                value = self._parse_review(ln)
            elif kind == "compliance":
                value = self._parse_compliance(ln)
            else:
                if self._end_of_line():
                    raise self._err(
                        f"{' '.join(words)} needs a value in quotes.", ln)
                value = self.parse_string_or_expr()
            doc.append((field_name, kind, value, ln))
            self.expect_newline()
            self.skip_newlines()
        self.advance()
        self.advance()      # END DOCUMENT
        self.expect_newline()

    def _parse_review(self, line: int) -> dict:
        """REVIEW "type" [REVIEWER "actor"]... [DETAILS "text"]
        [REPORT "source"] [SCOPE "name" [METHOD "m"]...]...
        [ASSESSMENT "aspect" "value"]..."""
        review = {"type": self.parse_string_or_expr(), "reviewers": [],
                  "scopes": [], "assessment": []}
        while not self._end_of_line():
            if self.match_word("REVIEWER"):
                review["reviewers"].append(self.parse_string_or_expr())
            elif self.match_word("DETAILS"):
                review["details"] = self.parse_string_or_expr()
            elif self.match_word("REPORT"):
                review["report"] = self.parse_string_or_expr()
            elif self.match_word("SCOPE"):
                scope = {"name": self.parse_string_or_expr(), "methods": []}
                while self.match_word("METHOD"):
                    scope["methods"].append(self.parse_string_or_expr())
                review["scopes"].append(scope)
            elif self.match_word("ASSESSMENT"):
                review["assessment"].append(
                    (self.parse_string_or_expr(), self.parse_string_or_expr()))
            else:
                raise self._err(
                    f"REVIEW does not take '{self.peek().value}'.", line,
                    hint="REVIEW \"type\" [REVIEWER \"actor\"] [DETAILS "
                         "\"text\"] [REPORT \"source\"] [SCOPE \"name\" "
                         "[METHOD \"m\"]] [ASSESSMENT \"aspect\" \"value\"]")
        return review

    def _parse_compliance(self, line: int) -> dict:
        """COMPLIANCE "system (a source)" [COMMENT "text"]
        [ASPECT "name" "value"]..."""
        decl = {"system": self.parse_string_or_expr(), "aspects": []}
        while not self._end_of_line():
            if self.match_keyword("COMMENT"):
                decl["comment"] = self.parse_string_or_expr()
            elif self.match_word("ASPECT"):
                decl["aspects"].append(
                    (self.parse_string_or_expr(), self.parse_string_or_expr()))
            else:
                raise self._err(
                    f"COMPLIANCE does not take '{self.peek().value}'.", line,
                    hint="COMPLIANCE \"source\" [COMMENT \"text\"] [ASPECT "
                         "\"name\" \"value\"]")
        return decl

    def _parse_social(self, line: int) -> dict:
        """SOCIAL "indicator", raw value, risk level [ACTIVITY n]
        [COMMENT "x"] [SOURCE "x"] [QUALITY "x"]"""
        entry = {"indicator": self.parse_string_or_expr(), "line": line}
        if self.peek().type == TokenType.COMMA:
            self.advance()
        if self._end_of_line():
            raise self._err(
                "SOCIAL needs a raw value and a risk level.", line,
                hint="SOCIAL \"indicator\", \"raw value\", LOW RISK")
        entry["raw"] = self.parse_add_expr()
        if self.peek().type == TokenType.COMMA:
            self.advance()
        if self.peek().type == TokenType.STRING:
            entry["risk"] = self.advance().value
        else:
            words = []
            while (self.peek().type in (TokenType.IDENTIFIER,
                                        TokenType.KEYWORD)
                   and self.peek().upper() not in SOCIAL_MODIFIERS):
                words.append(self.advance().upper())
            entry["risk"] = " ".join(words)
        if not entry["risk"]:
            raise self._err(
                "SOCIAL needs a risk level after the raw value.", line,
                hint="For example LOW RISK, HIGH RISK, NO DATA or NOT "
                     "APPLICABLE.")
        while not self._end_of_line():
            if self.match_word("ACTIVITY"):
                entry["activity"] = self.parse_add_expr()
            elif self.match_keyword("COMMENT"):
                entry["comment"] = self.parse_string_or_expr()
            elif self.match_word("SOURCE"):
                entry["source"] = self.parse_string_or_expr()
            elif self.match_keyword("QUALITY"):
                if self.peek().type == TokenType.LPAREN:
                    ped = self.parse_pedigree()
                    entry["quality"] = "(" + ";".join(str(n) for n in ped) + ")"
                else:
                    entry["quality"] = self.parse_string_or_expr()
            else:
                raise self._err(
                    f"SOCIAL does not take '{self.peek().value}'.", line,
                    hint="After the risk level: ACTIVITY n, COMMENT "
                         "\"text\", SOURCE \"name\", QUALITY (scores).")
        return entry

    # ── SYSTEM: parameter sets and analysis groups ───────────

    def at_system_block(self) -> bool:
        return ((self.at_word("PARAMETER")
                 and self.peek_at(1).upper() == "SET")
                or (self.at_word("ANALYSIS")
                    and self.peek_at(1).upper() == "GROUP"))

    def parse_system_block(self, sets: list, groups: list):
        line = self.current_line()
        if self.match_word("PARAMETER"):
            self.advance()      # SET
            spec = {"name": self.parse_string_or_expr(), "line": line,
                    "baseline": False, "values": []}
            while not self._end_of_line():
                if self.match_word("BASELINE"):
                    spec["baseline"] = True
                elif self.match_keyword("DESCRIPTION"):
                    spec["description"] = self.parse_string_or_expr()
                else:
                    raise self._err(
                        f"PARAMETER SET does not take "
                        f"'{self.peek().value}'.", line,
                        hint="PARAMETER SET \"name\" [BASELINE] "
                             "[DESCRIPTION \"text\"]")
            self.expect_newline()
            self.skip_newlines()
            while not self.at_end_of("PARAMETER"):
                tok = self.peek()
                if tok.type == TokenType.EOF or self.at_keyword("END"):
                    raise self._err(
                        "PARAMETER SET block missing END PARAMETER SET", line)
                ln = tok.line
                self.match_keyword("LET")
                if self.peek().type != TokenType.IDENTIFIER:
                    raise self._err(
                        f"Expected a parameter name, got "
                        f"'{self.peek().value}'.", ln,
                        hint="Each line of a PARAMETER SET is name = value "
                             "[IN PROCESS \"name\"].")
                name = self.advance().value
                if self.peek().type != TokenType.EQUALS:
                    raise self._err(f"Expected '=' after '{name}'", ln)
                self.advance()
                value = {"name": name, "value": self.parse_add_expr(),
                         "line": ln}
                if self.match_keyword("IN"):
                    if not self.match_keyword("PROCESS"):
                        raise self._err("Expected IN PROCESS \"name\".", ln)
                    value["process"] = self.parse_string_or_expr()
                spec["values"].append(value)
                self.expect_newline()
                self.skip_newlines()
            self.advance()
            self.advance()      # END PARAMETER
            self.match_keyword("SET")
            self.expect_newline()
            sets.append(spec)
        else:
            self.advance()      # ANALYSIS
            self.advance()      # GROUP
            spec = {"name": self.parse_string_or_expr(), "line": line,
                    "processes": []}
            if self.match_word("COLOR", "COLOUR"):
                spec["color"] = self.parse_string_or_expr()
            self.expect_newline()
            self.skip_newlines()
            while not self.at_end_of("ANALYSIS"):
                tok = self.peek()
                if tok.type == TokenType.EOF or self.at_keyword("END"):
                    raise self._err(
                        "ANALYSIS GROUP block missing END ANALYSIS GROUP",
                        line)
                ln = tok.line
                self.match_keyword("PROCESS")
                entry = {"name": self.parse_string_or_expr(), "line": ln}
                if self.match_keyword("LOCATION"):
                    entry["location"] = self.parse_string_or_expr()
                spec["processes"].append(entry)
                self.expect_newline()
                self.skip_newlines()
            self.advance()
            self.advance()      # END ANALYSIS
            self.match_word("GROUP")
            self.expect_newline()
            groups.append(spec)

    def parse_edit_system(self, line: int) -> EditSystemStmt:
        """EDIT SYSTEM "name" ... END EDIT

        PARAMETER SET "name" [BASELINE] ... END PARAMETER SET
        ANALYSIS GROUP "name" ... END ANALYSIS GROUP
        REMOVE PARAMETER SET "name"
        REMOVE ANALYSIS GROUP "name"
        SET DESCRIPTION "text"
        """
        self.advance()  # EDIT
        self.advance()  # SYSTEM
        stmt = EditSystemStmt(line=line, target=self.parse_string_or_expr())
        self.expect_newline()
        self.skip_newlines()
        while not self.at_keyword("END"):
            tok = self.peek()
            if tok.type == TokenType.EOF:
                raise self._err("EDIT SYSTEM block missing END EDIT", line)
            ln = tok.line
            if self.at_system_block():
                self.parse_system_block(stmt.parameter_sets,
                                        stmt.analysis_groups)
            elif self.match_keyword("REMOVE"):
                if self.match_word("PARAMETER"):
                    self.match_keyword("SET")
                    stmt.remove_parameter_sets.append(
                        (self.parse_string_or_expr(), ln))
                elif self.match_word("ANALYSIS"):
                    self.match_word("GROUP")
                    stmt.remove_analysis_groups.append(
                        (self.parse_string_or_expr(), ln))
                else:
                    raise self._err(
                        "Expected REMOVE PARAMETER SET \"name\" or REMOVE "
                        "ANALYSIS GROUP \"name\".", ln)
                self.expect_newline()
            elif self.match_keyword("SET"):
                if not self.match_keyword("DESCRIPTION"):
                    raise self._err("Expected SET DESCRIPTION \"text\".", ln)
                stmt.set_description = self.parse_string_or_expr()
                self.expect_newline()
            else:
                raise self._err(
                    f"'{tok.value}' is not allowed inside EDIT SYSTEM "
                    f"(expected PARAMETER SET, ANALYSIS GROUP, REMOVE, SET "
                    f"DESCRIPTION or END EDIT)", ln)
            self.skip_newlines()
        self.expect_keyword("END")
        self.match_keyword("EDIT")
        self.expect_newline()
        return stmt
