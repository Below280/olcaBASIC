"""
Parsing for the EPD toolkit: RATING lines, BIOGENIC CONTENT and
BIOGENIC EXPORT in the EPD block, EPD DATA QUALITY per scenario, EPD DQ
SHEET, EPD DQ TABLE, EPD SENSITIVITY and EPD EXPORT MODEL.

Part of olcabasic.parser.Parser.
"""

from .ast_nodes import EpdDocumentStmt, EpdSensitivityStmt
from .tokeniser import TokenType

RATING_ASPECTS = ("GEOGRAPHY", "TECHNOLOGY", "TIME")
RATING_EXAMPLE = ('RATING GEOGRAPHY "Fair" REASON "Rest-of-World data used '
                  'for a national supply"')


# EPD DOCUMENT lines: the words of the key, then what follows.
#   text    a string (or string expression)
#   number  a number expression
#   mass    a number and a unit of mass (kg, g, t)
#   pct     a number with an optional %
#   modules module codes separated by commas, then a text
#   yesno   YES or NO
#   svhc    NONE, or name, EC number, CAS number, share %
# Options (word followed by a percentage) are allowed on CONTENT.
DOCUMENT_LINES = {
    ("STATEMENTS",): ("text",),
    ("OWNER", "ADDRESS"): ("text",),
    ("OWNER", "CONTACT"): ("text",),
    ("OWNER", "DESCRIPTION"): ("text",),
    ("OWNER",): ("text",),
    ("PRACTITIONER",): ("text",),
    ("PRODUCT", "DESCRIPTION"): ("text",),
    ("PRODUCT", "IDENTIFICATION"): ("text",),
    ("PRODUCT", "CODE"): ("text", "text", "text"),
    ("MANUFACTURING",): ("text",),
    ("LIFESPAN",): ("text",),
    ("SITE",): ("text",),
    ("WEBSITE",): ("text",),
    ("CONTENT",): ("text", "mass"),
    ("PACKAGING",): ("text", "mass"),
    ("SVHC",): ("svhc",),
    ("GEOGRAPHY",): ("modules",),
    ("SCENARIO",): ("modules",),
    ("OMITTED",): ("modules",),
    ("MASS", "PER", "UNIT"): ("number",),
    ("AREA", "DENSITY"): ("number",),
    ("THICKNESS",): ("number",),
    ("LINEAR", "DENSITY"): ("number",),
    ("DENSITY",): ("number",),
    ("RSL",): ("text",),
    ("DIAGRAM",): ("text",),
    ("IMAGE",): ("text",),
    ("LOGO",): ("text",),
    ("SOFTWARE",): ("text",),
    ("METHOD", "VERSION"): ("text",),
    ("INFRASTRUCTURE",): ("text",),
    ("VERIFICATION",): ("text",),
    ("VERIFIER",): ("text",),
    ("APPROVED", "BY"): ("text",),
    ("TOOL",): ("text",),
    ("FOLLOW", "UP"): ("yesno",),
    ("REGISTRATION",): ("text",),
    ("VERSION", "DATE"): ("text",),
    ("VALID", "UNTIL"): ("text",),
    ("LICENSEE",): ("text",),
    ("HISTORY",): ("text", "text"),
    ("REFERENCE",): ("text",),
    ("ABBREVIATION",): ("text", "text"),
    ("ADDITIONAL",): ("text",),
}
CONTENT_OPTIONS = ("RECYCLED", "PRECONSUMER", "BIOGENIC")
DOCUMENT_EXAMPLE = ('EPD DOCUMENT "epd.md"\n  OWNER "Example Ltd"\n  '
                    'SITE "Hexham, United Kingdom"\n  CONTENT "Timber", 450 '
                    'kg BIOGENIC 100%\n  SVHC NONE\nEND EPD DOCUMENT')


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

    # ── EPD DOCUMENT ... END EPD DOCUMENT ────────────────────

    def _document_key(self):
        """The longest key of DOCUMENT_LINES the line starts with."""
        for key in sorted(DOCUMENT_LINES, key=len, reverse=True):
            if all(self.peek_at(i).type in (TokenType.KEYWORD,
                                            TokenType.IDENTIFIER)
                   and self.peek_at(i).upper() == w
                   for i, w in enumerate(key)):
                for _ in key:
                    self.advance()
                return key
        return None

    def _comma(self, ln: int, what: str):
        if self.peek().type != TokenType.COMMA:
            raise self._err(f"Expected a comma before {what}.", ln,
                            hint=DOCUMENT_EXAMPLE)
        self.advance()

    def parse_epd_document(self, line: int) -> EpdDocumentStmt:
        """After EPD DOCUMENT."""
        if self._end_of_line():
            raise self._err("EPD DOCUMENT needs a file name.", line,
                            hint=DOCUMENT_EXAMPLE)
        stmt = EpdDocumentStmt(line=line,
                               filename=self.parse_string_or_expr())
        self.expect_newline()
        while True:
            tok = self.peek()
            ln = tok.line
            if tok.type == TokenType.EOF:
                raise self._err("The EPD DOCUMENT block is missing END EPD "
                                "DOCUMENT.", line)
            if tok.type in (TokenType.COMMENT, TokenType.NEWLINE):
                self.advance()
                continue
            if self.at_keyword("END"):
                if not (self.peek_at(1).upper() == "EPD"
                        and self.peek_at(2).upper() == "DOCUMENT"):
                    raise self._err(
                        f"Expected END EPD DOCUMENT, got END "
                        f"{self.peek_at(1).value}.", ln)
                for _ in range(3):
                    self.advance()
                self.expect_newline()
                return stmt
            key = self._document_key()
            if key is None:
                raise self._err(
                    f"'{tok.value}' is not a line of an EPD DOCUMENT block.",
                    ln, hint="HELP EPD DOCUMENT lists the lines it takes.")
            name = " ".join(key)
            entry = {"key": name, "args": [], "options": {}, "modules": [],
                     "unit": "", "line": ln}
            for n, kind in enumerate(DOCUMENT_LINES[key]):
                if n:
                    self._comma(ln, f"the next part of {name}")
                if self._end_of_line():
                    raise self._err(f"{name} is missing a value.", ln,
                                    hint=f"HELP EPD DOCUMENT shows {name}.")
                if kind in ("text", "number"):
                    entry["args"].append(self.parse_string_or_expr())
                elif kind == "mass":
                    entry["args"].append(self.parse_expr())
                    unit = self.match_word("KG", "G", "T")
                    if unit is None:
                        raise self._err(
                            f"The mass on {name} needs a unit: kg, g or t.",
                            ln, hint=DOCUMENT_EXAMPLE)
                    entry["unit"] = unit.upper().lower()
                elif kind == "yesno":
                    word = self.match_word("YES", "NO")
                    if word is None:
                        raise self._err(f"{name} is YES or NO.", ln)
                    entry["args"].append(word.upper() == "YES")
                elif kind == "svhc":
                    if self.match_word("NONE"):
                        entry["args"] = ["NONE"]
                    else:
                        entry["args"].append(self.parse_string_or_expr())
                        for what in ("the EC number", "the CAS number"):
                            self._comma(ln, what)
                            entry["args"].append(self.parse_string_or_expr())
                        self._comma(ln, "the share of the product's mass")
                        entry["args"].append(self._percent("SVHC"))
                elif kind == "modules":
                    while True:
                        entry["modules"].append(self._module_code(name))
                        if self.peek().type != TokenType.COMMA:
                            break
                        self.advance()
                        if self.peek().type != TokenType.IDENTIFIER:
                            break
                    if self._end_of_line():
                        raise self._err(
                            f"{name} needs the text after the modules.", ln,
                            hint=f'For example: {name} A1, A2, A3 "..."')
                    entry["args"].append(self.parse_string_or_expr())
            while key == ("CONTENT",) and self.at_word(*CONTENT_OPTIONS):
                word = self.advance().upper()
                if word in entry["options"]:
                    raise self._err(f"{word} is given twice.", ln)
                entry["options"][word] = self._percent(f"CONTENT {word}")
            stmt.lines.append(entry)
            self.expect_newline()
