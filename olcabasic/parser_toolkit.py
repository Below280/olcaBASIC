"""
Parsing for the EPD toolkit: RATING lines, BIOGENIC CONTENT and
BIOGENIC EXPORT in the EPD block, EPD DATA QUALITY per scenario, EPD DQ
SHEET, EPD DQ TABLE, EPD SENSITIVITY and EPD EXPORT MODEL.

Part of olcabasic.parser.Parser.
"""

from .ast_nodes import EpdSensitivityStmt
from .tokeniser import TokenType

RATING_ASPECTS = ("GEOGRAPHY", "TECHNOLOGY", "TIME")
RATING_EXAMPLE = ('RATING GEOGRAPHY "Fair" REASON "Rest-of-World data used '
                  'for a national supply"')


class ToolkitParserMixin:

    # ── RATING GEOGRAPHY|TECHNOLOGY|TIME "level" REASON "why" ──

    def parse_rating(self, ratings: dict):
        """After the word RATING. Adds to ratings {aspect: {"level",
        "reason", "line"}}."""
        ln = self.current_line()
        if not self.at_word(*RATING_ASPECTS):
            raise self._err(
                "RATING needs what is rated: GEOGRAPHY, TECHNOLOGY or TIME.",
                ln, hint=RATING_EXAMPLE)
        aspect = self.advance().upper()
        if aspect in ratings:
            raise self._err(
                f"RATING {aspect} is given twice (also on line "
                f"{ratings[aspect]['line']}).", ln, hint="Keep one.")
        if self._end_of_line():
            raise self._err(f"RATING {aspect} needs a level.", ln,
                            hint=RATING_EXAMPLE)
        level = self.parse_string_or_expr()
        if not self.match_word("REASON") or self._end_of_line():
            raise self._err(
                f"RATING {aspect} needs REASON: why the data earns that "
                f"level.", ln, hint=RATING_EXAMPLE)
        reason = self.parse_string_or_expr()
        ratings[aspect] = {"level": level, "reason": reason, "line": ln}

    # ── BIOGENIC CONTENT / BIOGENIC EXPORT in the EPD block ───

    def _kg_of(self, what: str, ln: int, example: str):
        """A number followed by 'kg <what>' (kg C, kg DRY)."""
        if self._end_of_line():
            raise self._err(f"Expected an amount in kg {what}.", ln,
                            hint=example)
        amount = self.parse_expr()
        if not (self.match_word("KG") and self.match_word(what)):
            raise self._err(
                f"The amount is in kg {what}: write 'kg {what}' after the "
                f"number.", ln, hint=example)
        return amount

    def parse_biogenic_content(self, f: dict, lines: dict, ln: int):
        """After BIOGENIC CONTENT: PRODUCT n kg C | PRODUCT FROM MASS n
        kg DRY, then optionally PACKAGING the same way."""
        example = ("BIOGENIC CONTENT PRODUCT 246.4 kg C PACKAGING 0 kg C, "
                   "or BIOGENIC CONTENT PRODUCT FROM MASS 492.8 kg DRY")
        if "biogenic_content" in f:
            raise self._err("BIOGENIC CONTENT is given twice in the EPD "
                            "block.", ln, hint="Keep one.")
        content = {"line": ln}
        for part in ("PRODUCT", "PACKAGING"):
            if not self.match_word(part):
                if part == "PRODUCT":
                    raise self._err(
                        "BIOGENIC CONTENT starts with PRODUCT.", ln,
                        hint=example)
                continue
            key = part.lower()
            if self.match_keyword("FROM"):
                if not self.match_word("MASS"):
                    raise self._err("Expected FROM MASS n kg DRY.", ln,
                                    hint=example)
                content[key] = {"dry_mass": self._kg_of("DRY", ln, example)}
            else:
                content[key] = {"carbon": self._kg_of("C", ln, example)}
        f["biogenic_content"] = content
        lines["biogenic_content"] = ln

    def parse_biogenic_export(self, f: dict, ln: int):
        """After BIOGENIC EXPORT: module "what", n kg C"""
        example = 'BIOGENIC EXPORT A3 "Sawdust and chips", 12.5 kg C'
        module = self._module_code("BIOGENIC EXPORT")
        if self._end_of_line() or self.peek().type == TokenType.COMMA:
            raise self._err("BIOGENIC EXPORT needs what leaves.", ln,
                            hint=example)
        item = self.parse_string_or_expr()
        if self.peek().type != TokenType.COMMA:
            raise self._err(
                "Expected a comma and the carbon that leaves, in kg C.", ln,
                hint=example)
        self.advance()
        amount = self._kg_of("C", ln, example)
        f.setdefault("biogenic_exports", []).append(
            {"module": module, "item": item, "carbon": amount, "line": ln})

    # ── EPD SENSITIVITY ... END EPD SENSITIVITY ───────────────

    def parse_epd_sensitivity(self, line: int) -> EpdSensitivityStmt:
        """After EPD SENSITIVITY."""
        example = ('EPD SENSITIVITY BY 20%\n  GROUP "Electricity" VARY '
                   'kiln_kwh, saw_kwh\nEND EPD SENSITIVITY')
        if not self.match_keyword("BY"):
            raise self._err("EPD SENSITIVITY needs BY and a percentage.",
                            line, hint=example)
        stmt = EpdSensitivityStmt(line=line,
                                  percent=self._percent("EPD SENSITIVITY BY"))
        if stmt.percent <= 0 or stmt.percent >= 100:
            raise self._err(
                "The percentage is above 0 and below 100.", line,
                hint="For example: EPD SENSITIVITY BY 20%")
        if self.match_keyword("SAVE"):
            stmt.save = self.parse_string_or_expr()
        self.expect_newline()
        while True:
            tok = self.peek()
            ln = tok.line
            if tok.type == TokenType.EOF:
                raise self._err(
                    "The EPD SENSITIVITY block is missing END EPD "
                    "SENSITIVITY.", line)
            if tok.type in (TokenType.COMMENT, TokenType.NEWLINE):
                self.advance()
                continue
            if self.at_keyword("END"):
                if not (self.peek_at(1).upper() == "EPD"
                        and self.peek_at(2).upper() == "SENSITIVITY"):
                    raise self._err(
                        f"Expected END EPD SENSITIVITY, got END "
                        f"{self.peek_at(1).value}.", ln)
                for _ in range(3):
                    self.advance()
                self.expect_newline()
                break
            if self.match_keyword("SAVE"):
                if stmt.save is not None:
                    raise self._err("SAVE is given twice.", ln)
                stmt.save = self.parse_string_or_expr()
                self.expect_newline()
                continue
            if not self.match_word("GROUP"):
                raise self._err(
                    f"'{tok.value}' is not a line of an EPD SENSITIVITY "
                    f"block.", ln,
                    hint='The lines it takes: GROUP "name" VARY parameter, '
                         'parameter ... and SAVE "file.csv".')
            if self._end_of_line():
                raise self._err("GROUP needs a name.", ln, hint=example)
            name = self.parse_string_or_expr()
            if not self.match_keyword("VARY"):
                raise self._err(
                    "GROUP needs VARY and the parameters that move "
                    "together.", ln, hint=example)
            params = []
            while True:
                p = self.peek()
                if p.type != TokenType.IDENTIFIER:
                    raise self._err(
                        "VARY takes parameter names: plain words separated "
                        "by commas.", ln, hint=example)
                params.append(self.advance().value)
                if self.peek().type != TokenType.COMMA:
                    break
                self.advance()
            stmt.groups.append({"name": name, "params": params, "line": ln})
            self.expect_newline()
        if not stmt.groups:
            raise self._err("EPD SENSITIVITY has no GROUP line.", line,
                            hint=example)
        return stmt

    # ── the new EPD commands that take a file ────────────────

    def parse_epd_file_command(self, stmt, what: str, example: str):
        """EPD DQ SHEET "file", EPD DQ TABLE "file", EPD EXPORT MODEL
        "file": the file name."""
        if self._end_of_line():
            raise self._err(f"EPD {what} needs a file name.", stmt.line,
                            hint=f"For example: {example}")
        stmt.argument = self.parse_string_or_expr()
