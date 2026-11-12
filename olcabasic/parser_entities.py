"""
Parsing for every entity type: the generic FIND, SHOW, DELETE, MOVE and
EXPORT, the MAKE and EDIT blocks for actors, sources, currencies,
locations, unit groups, flow properties, social indicators, data
quality systems, impact methods and projects, CALCULATE PROJECT, SAVE
RESULT AS and SHUTDOWN SERVER.

Part of olcabasic.parser.Parser.
"""

from .ast_nodes import (
    CalculateProjectStmt, EntityDeleteStmt, EntityExportStmt, EntityFindStmt,
    EntityMoveStmt, EntityShowStmt, MakeEntityStmt, MethodStmt, ProjectStmt,
    SaveResultAsStmt, ShutdownStmt,
)
from .tokeniser import TokenType

# Type words of two tokens, and other ways of saying a type.
TWO_WORD_TYPES = {
    ("FLOW", "MAP"): "FLOW MAP",
    ("FLOW", "PROPERTY"): "PROPERTY",
    ("UNIT", "GROUP"): "UNITS",
    ("DQ", "SYSTEM"): "DQ SYSTEM",
    ("SOCIAL", "INDICATOR"): "SOCIAL INDICATOR",
    ("IMPACT", "CATEGORY"): "CATEGORY",
    ("IMPACT", "METHOD"): "METHOD",
    ("PRODUCT", "SYSTEM"): "SYSTEM",
    ("STORED", "RESULT"): "RESULT",
}
ONE_WORD_TYPES = ("PROCESS", "SYSTEM", "FLOW", "PROPERTY", "UNITS",
                  "PARAMETER", "METHOD", "CATEGORY", "LOCATION", "ACTOR",
                  "SOURCE", "CURRENCY", "PROJECT", "RESULT", "EPD")
TYPE_LIST = ("PROCESS, SYSTEM, FLOW, PROPERTY, UNITS, PARAMETER, METHOD, "
             "CATEGORY, LOCATION, DQ SYSTEM, ACTOR, SOURCE, CURRENCY, "
             "SOCIAL INDICATOR, PROJECT, RESULT, EPD or FLOW MAP")

# MAKE blocks made of one field per line: type -> {words: (key, kind)}.
# kind: text, number, yesno, word (one of a few words).
SIMPLE_FIELDS = {
    "ACTOR": {
        ("ADDRESS",): ("address", "text"),
        ("CITY",): ("city", "text"),
        ("COUNTRY",): ("country", "text"),
        ("EMAIL",): ("email", "text"),
        ("PHONE",): ("telephone", "text"),
        ("TELEPHONE",): ("telephone", "text"),
        ("FAX",): ("telefax", "text"),
        ("WEBSITE",): ("website", "text"),
        ("POSTCODE",): ("zip_code", "text"),
        ("ZIP",): ("zip_code", "text"),
        ("DESCRIPTION",): ("description", "text"),
    },
    "SOURCE": {
        ("REFERENCE",): ("text_reference", "text"),
        ("URL",): ("url", "text"),
        ("YEAR",): ("year", "number"),
        ("ATTACH",): ("attach", "text"),
        ("DESCRIPTION",): ("description", "text"),
    },
    "CURRENCY": {
        ("CODE",): ("code", "text"),
        ("FACTOR",): ("conversion_factor", "number"),
        ("REFERENCE",): ("reference", "text"),
        ("DESCRIPTION",): ("description", "text"),
    },
    "LOCATION": {
        ("CODE",): ("code", "text"),
        ("LATITUDE",): ("latitude", "number"),
        ("LONGITUDE",): ("longitude", "number"),
        ("GEOMETRY",): ("geometry_file", "text"),
        ("DESCRIPTION",): ("description", "text"),
    },
    "UNITS": {
        ("DESCRIPTION",): ("description", "text"),
    },
    "PROPERTY": {
        ("UNITS",): ("units", "text"),
        ("UNIT", "GROUP"): ("units", "text"),
        ("TYPE",): ("type", "word"),
        ("DESCRIPTION",): ("description", "text"),
    },
    "SOCIAL INDICATOR": {
        ("ACTIVITY", "VARIABLE"): ("activity_variable", "text"),
        ("ACTIVITY", "QUANTITY"): ("activity_quantity", "text"),
        ("ACTIVITY", "UNIT"): ("activity_unit", "text"),
        ("MEASURED", "IN"): ("unit_of_measurement", "text"),
        ("EVALUATION",): ("evaluation_scheme", "text"),
        ("DESCRIPTION",): ("description", "text"),
    },
    "DQ SYSTEM": {
        ("SOURCE",): ("source", "text"),
        ("UNCERTAINTIES",): ("has_uncertainties", "yesno"),
        ("DESCRIPTION",): ("description", "text"),
    },
}
SIMPLE_TYPES = tuple(SIMPLE_FIELDS)

BLOCK_HELP = {
    "ACTOR": "ADDRESS, CITY, POSTCODE, COUNTRY, EMAIL, PHONE, FAX, WEBSITE, "
             "DESCRIPTION",
    "SOURCE": "REFERENCE, URL, YEAR, ATTACH \"file\", DESCRIPTION",
    "CURRENCY": "CODE, FACTOR, REFERENCE \"currency\", DESCRIPTION",
    "LOCATION": "CODE, LATITUDE, LONGITUDE, GEOMETRY \"file.geojson\", "
                "DESCRIPTION",
    "UNITS": "UNIT \"name\", factor [REFERENCE] [SYNONYMS \"a; b\"], "
             "DESCRIPTION",
    "PROPERTY": "UNITS \"unit group\", TYPE PHYSICAL|ECONOMIC, DESCRIPTION",
    "SOCIAL INDICATOR": "ACTIVITY VARIABLE, ACTIVITY QUANTITY, ACTIVITY "
                        "UNIT, MEASURED IN, EVALUATION, DESCRIPTION",
    "DQ SYSTEM": "SOURCE, UNCERTAINTIES YES|NO, DESCRIPTION, INDICATOR "
                 "\"name\" then SCORE n \"label\" lines",
}


class EntitiesParserMixin:

    # ── type words ───────────────────────────────────────────

    def peek_entity_type(self):
        """(type word, number of tokens) at the cursor, or (None, 0).
        Nothing is consumed."""
        tok = self.peek()
        if tok.type not in (TokenType.KEYWORD, TokenType.IDENTIFIER):
            return None, 0
        first = tok.upper()
        nxt = self.peek_at(1)
        if nxt.type in (TokenType.KEYWORD, TokenType.IDENTIFIER):
            word = TWO_WORD_TYPES.get((first, nxt.upper()))
            if word:
                return word, 2
        if first in ONE_WORD_TYPES:
            return first, 1
        return None, 0

    def take_entity_type(self, verb: str, example: str) -> str:
        word, n = self.peek_entity_type()
        if word is None:
            got = self.peek()
            said = (f"'{got.value}' is not a type of entity."
                    if got.type in (TokenType.KEYWORD, TokenType.IDENTIFIER)
                    else f"{verb} needs a type.")
            raise self._err(said, hint=f"Use {TYPE_LIST}. For example: "
                                       f"{example}")
        for _ in range(n):
            self.advance()
        return word

    def _name_after(self, what: str, example: str):
        if self._end_of_line():
            raise self._err(f"{what} needs a name.", hint=example)
        return self.parse_string_or_expr()

    # ── FIND, SHOW, DELETE, MOVE, EXPORT ─────────────────────

    def parse_entity_find(self, line: int) -> EntityFindStmt:
        etype = self.take_entity_type("FIND", 'FIND ACTOR "name"')
        stmt = EntityFindStmt(line=line, entity_type=etype)
        if not self._end_of_line() and not self.at_keyword("IN"):
            stmt.term = self.parse_string_or_expr()
        if self.match_keyword("IN"):
            stmt.folder = self.parse_string_or_expr()
        self.expect_newline()
        return stmt

    def parse_entity_show(self, line: int) -> EntityShowStmt:
        etype = self.take_entity_type("SHOW", 'SHOW ACTOR "name"')
        ref = self._name_after(f"SHOW {etype}", f'SHOW {etype} "name"')
        stmt = EntityShowStmt(line=line, entity_type=etype, ref=ref)
        if self.peek().type in (TokenType.KEYWORD, TokenType.IDENTIFIER):
            if not self.at_word("JSON", "USAGE"):
                raise self._err(
                    f"SHOW {etype} doesn't take '{self.peek().value}'.",
                    hint="Use JSON (the entity as openLCA stores it) or "
                         "USAGE (where it is used), or nothing.")
            stmt.mode = self.advance().upper()
        self.expect_newline()
        return stmt

    def parse_entity_delete(self, line: int) -> EntityDeleteStmt:
        etype = self.take_entity_type("DELETE", 'DELETE ACTOR "name"')
        ref = self._name_after(f"DELETE {etype}", f'DELETE {etype} "name"')
        stmt = EntityDeleteStmt(line=line, entity_type=etype, ref=ref)
        if self.match_keyword("CONFIRM"):
            stmt.confirm = True
        self.expect_newline()
        return stmt

    def parse_entity_move(self, line: int) -> EntityMoveStmt:
        etype = self.take_entity_type("MOVE", 'MOVE ACTOR "name" TO "folder"')
        ref = self._name_after(f"MOVE {etype}",
                               f'MOVE {etype} "name" TO "folder"')
        if not self.match_keyword("TO"):
            raise self._err("MOVE needs TO and a folder.",
                            hint=f'MOVE {etype} "name" TO "folder"')
        self.match_keyword("FOLDER")
        dest = self._name_after("MOVE ... TO",
                                f'MOVE {etype} "name" TO "folder"')
        self.expect_newline()
        return EntityMoveStmt(line=line, entity_type=etype, ref=ref,
                              destination=dest)

    def parse_entity_export(self, line: int) -> EntityExportStmt:
        etype = self.take_entity_type("EXPORT",
                                      'EXPORT PROCESS "name" TO "file.zip"')
        example = f'EXPORT {etype} "name" TO "file.zip"'
        ref = self._name_after(f"EXPORT {etype}", example)
        if not self.match_keyword("TO"):
            raise self._err("EXPORT needs TO and a file name.", hint=example)
        filename = self._name_after("EXPORT ... TO", example)
        self.expect_newline()
        return EntityExportStmt(line=line, entity_type=etype, ref=ref,
                                filename=filename)

    # ── MAKE / EDIT blocks of one field per line ─────────────

    def _block_header(self, etype: str, verb: str):
        example = f'{verb} {etype} "name"'
        name = self._name_after(f"{verb} {etype}", example)
        folder = None
        if self.match_keyword("FOLDER"):
            folder = self.parse_string_or_expr()
        return name, folder

    def _block_end(self, etype: str, editing: bool, opened: int) -> bool:
        """True (and consumed) at the END of the block. EDIT blocks end
        with END EDIT; END <type> is accepted for both."""
        if not self.at_keyword("END"):
            return False
        words = etype.split()
        nxt = [self.peek_at(i + 1).upper() for i in range(len(words))]
        if editing and nxt[0] == "EDIT":
            self.advance()
            self.advance()
            self.expect_newline()
            return True
        if nxt == words or (etype == "UNITS" and nxt[0] == "UNITS"):
            for _ in range(len(words) + 1):
                self.advance()
            self.expect_newline()
            return True
        closing = "END EDIT" if editing else f"END {etype}"
        raise self._err(
            f"Expected {closing}, got END {self.peek_at(1).value}.",
            hint=f"The block opened on line {opened} closes with {closing}.")

    def _skip_blank(self, etype: str, opened: int, editing: bool):
        while True:
            tok = self.peek()
            if tok.type == TokenType.EOF:
                closing = "END EDIT" if editing else f"END {etype}"
                raise self._err(
                    f"The {etype} block is missing {closing}.", opened)
            if tok.type in (TokenType.COMMENT, TokenType.NEWLINE):
                self.advance()
                continue
            return

    def parse_make_entity(self, line: int, etype: str,
                          editing: bool = False) -> MakeEntityStmt:
        verb = "EDIT" if editing else "MAKE"
        name, folder = self._block_header(etype, verb)
        if editing and folder is not None:
            raise self._err(
                "EDIT does not take FOLDER.",
                hint=f'MOVE {etype} "name" TO "folder" moves it.')
        if editing and self.match_keyword("CONFIRM"):
            pass
        self.expect_newline()
        stmt = MakeEntityStmt(line=line, entity_type=etype, name=name,
                              folder=folder, editing=editing)
        table = SIMPLE_FIELDS[etype]
        seen = {}
        while True:
            self._skip_blank(etype, line, editing)
            if self._block_end(etype, editing, line):
                break
            tok = self.peek()
            ln = tok.line
            first = tok.upper() if tok.type in (
                TokenType.KEYWORD, TokenType.IDENTIFIER) else ""
            second = self.peek_at(1).upper()

            if etype == "UNITS" and first == "UNIT":
                self.advance()
                if stmt.items is None:
                    stmt.items = []
                stmt.items.append(self._parse_unit_line(ln))
                continue
            if etype == "DQ SYSTEM" and first == "INDICATOR":
                self.advance()
                if stmt.items is None:
                    stmt.items = []
                ind = {"name": self._name_after("INDICATOR",
                                                'INDICATOR "Reliability"'),
                       "line": ln, "scores": []}
                self.expect_newline()
                stmt.items.append(ind)
                continue
            if etype == "DQ SYSTEM" and first == "SCORE":
                self.advance()
                if not stmt.items:
                    raise self._err(
                        "SCORE comes after an INDICATOR line.", ln,
                        hint='INDICATOR "Reliability" then SCORE 1 '
                             '"Verified data"')
                stmt.items[-1]["scores"].append(self._parse_score_line(ln))
                continue

            key = None
            if (first, second) in table:
                key, kind = table[(first, second)]
                self.advance()
                self.advance()
            elif (first,) in table:
                key, kind = table[(first,)]
                self.advance()
            if key is None:
                raise self._err(
                    f"'{tok.value}' is not a line of a {etype} block.", ln,
                    hint="The lines it takes: " + BLOCK_HELP[etype] + ".")
            if key in seen:
                raise self._err(
                    f"{first} is given twice (also on line {seen[key]}).",
                    ln)
            seen[key] = ln
            if kind == "yesno":
                value = self._yes_no(first)
            elif kind == "word":
                if self.peek().type not in (TokenType.KEYWORD,
                                            TokenType.IDENTIFIER):
                    raise self._err(f"{first} takes a word.", ln,
                                    hint="TYPE PHYSICAL or TYPE ECONOMIC")
                value = self.advance().upper()
            elif kind == "number":
                if self._end_of_line():
                    raise self._err(f"{first} needs a number.", ln)
                value = self.parse_expr()
            else:
                if self._end_of_line():
                    raise self._err(f"{first} needs a value.", ln,
                                    hint=f'{first} "text"')
                value = self.parse_string_or_expr()
            stmt.fields.append((key, value, ln, kind))
            self.expect_newline()
        return stmt

    def _parse_unit_line(self, ln: int) -> dict:
        """UNIT "name", factor [REFERENCE] [SYNONYMS "a; b"]"""
        example = 'UNIT "kg", 1 REFERENCE   or   UNIT "g", 0.001'
        if self._end_of_line():
            raise self._err("UNIT needs a name and a factor.", ln,
                            hint=example)
        if self.peek().type == TokenType.STRING:
            name = self.parse_string_or_expr()
        else:
            from .ast_nodes import StringLiteral
            name = StringLiteral(self.parse_unit())
        if self.peek().type != TokenType.COMMA:
            raise self._err(
                "UNIT needs a conversion factor to the reference unit "
                "after a comma.", ln, hint=example)
        self.advance()
        unit = {"name": name, "factor": self.parse_expr(), "line": ln,
                "reference": False, "synonyms": None}
        while self.peek().type in (TokenType.KEYWORD, TokenType.IDENTIFIER):
            if self.match_word("REFERENCE"):
                unit["reference"] = True
            elif self.match_word("SYNONYMS"):
                unit["synonyms"] = self.parse_string_or_expr()
            elif self.match_keyword("DESCRIPTION"):
                unit["description"] = self.parse_string_or_expr()
            else:
                raise self._err(
                    f"A UNIT line doesn't take '{self.peek().value}'.", ln,
                    hint=example)
        self.expect_newline()
        return unit

    def _parse_score_line(self, ln: int) -> dict:
        """SCORE n "label" [DESCRIPTION "x"] [UNCERTAINTY n]"""
        example = 'SCORE 1 "Verified data" UNCERTAINTY 1.05'
        if self._end_of_line():
            raise self._err("SCORE needs a number and a label.", ln,
                            hint=example)
        score = {"position": self.parse_int("SCORE"), "label": None,
                 "description": None, "uncertainty": None, "line": ln}
        if self.peek().type == TokenType.COMMA:
            self.advance()
        if self.peek().type == TokenType.STRING:
            score["label"] = self.parse_string_or_expr()
        while self.peek().type in (TokenType.KEYWORD, TokenType.IDENTIFIER):
            if self.match_keyword("DESCRIPTION"):
                score["description"] = self.parse_string_or_expr()
            elif self.match_word("UNCERTAINTY"):
                score["uncertainty"] = self.parse_expr()
            else:
                raise self._err(
                    f"A SCORE line doesn't take '{self.peek().value}'.", ln,
                    hint=example)
        self.expect_newline()
        return score

    # ── MAKE METHOD / EDIT METHOD ────────────────────────────

    def parse_method(self, line: int, editing: bool = False) -> MethodStmt:
        verb = "EDIT" if editing else "MAKE"
        name, folder = self._block_header("METHOD", verb)
        stmt = MethodStmt(line=line, name=name, folder=folder,
                          editing=editing)
        if editing and folder is not None:
            raise self._err("EDIT METHOD does not take FOLDER.",
                            hint='MOVE METHOD "name" TO "folder" moves it.')
        if self.match_keyword("CONFIRM"):
            if not editing:
                raise self._err("MAKE METHOD does not take CONFIRM.")
            stmt.confirm = True
        self.expect_newline()
        while True:
            self._skip_blank("METHOD", line, editing)
            if self._block_end("METHOD", editing, line):
                break
            tok = self.peek()
            ln = tok.line
            if self.match_keyword("DESCRIPTION"):
                stmt.description = self.parse_string_or_expr()
                self.expect_newline()
            elif self.match_word("SOURCE"):
                stmt.source = self.parse_string_or_expr()
                self.expect_newline()
            elif self.match_word("CODE"):
                stmt.code = self.parse_string_or_expr()
                self.expect_newline()
            elif self.match_keyword("CATEGORY"):
                stmt.categories.append(self._parse_category(ln, editing))
            elif self.at_word("NW"):
                self.advance()
                if not self.match_keyword("SET"):
                    raise self._err('Expected NW SET "name".', ln)
                stmt.nw_sets.append(self._parse_nw_set(ln))
            elif self.at_keyword("REMOVE"):
                if not editing:
                    raise self._err(
                        "REMOVE belongs in EDIT METHOD: a new method has "
                        "nothing to remove.", ln)
                self.advance()
                if self.match_keyword("CATEGORY"):
                    stmt.remove_categories.append(
                        (self.parse_string_or_expr(), ln))
                elif self.at_word("NW"):
                    self.advance()
                    if not self.match_keyword("SET"):
                        raise self._err('Expected REMOVE NW SET "name".', ln)
                    stmt.remove_nw_sets.append(
                        (self.parse_string_or_expr(), ln))
                else:
                    raise self._err(
                        "Say what to remove.", ln,
                        hint='REMOVE CATEGORY "name" or REMOVE NW SET '
                             '"name". A factor is removed inside its '
                             'CATEGORY block: REMOVE FACTOR "flow".')
                self.expect_newline()
            else:
                raise self._err(
                    f"'{tok.value}' is not a line of a METHOD block.", ln,
                    hint="The lines it takes: DESCRIPTION, SOURCE, CODE, "
                         "CATEGORY \"name\" UNIT \"unit\" ... END CATEGORY, "
                         "NW SET \"name\" ... END NW SET"
                         + (", REMOVE CATEGORY, REMOVE NW SET."
                            if editing else "."))
        return stmt

    def _parse_category(self, ln: int, editing: bool) -> dict:
        example = 'CATEGORY "Climate change" UNIT "kg CO2 eq"'
        cat = {"name": self._name_after("CATEGORY", example), "unit": None,
               "direction": None, "code": None, "description": None,
               "parameters": [], "factors": [], "remove_factors": [],
               "line": ln}
        while self.peek().type in (TokenType.KEYWORD, TokenType.IDENTIFIER):
            if self.match_word("UNIT"):
                cat["unit"] = self.parse_string_or_expr()
            elif self.at_keyword("INPUT", "OUTPUT"):
                cat["direction"] = self.advance().upper()
            elif self.match_word("CODE"):
                cat["code"] = self.parse_string_or_expr()
            else:
                raise self._err(
                    f"A CATEGORY line doesn't take '{self.peek().value}'.",
                    ln, hint=example + " [INPUT|OUTPUT] [CODE \"x\"]")
        self.expect_newline()
        while True:
            self._skip_blank("CATEGORY", ln, False)
            if self.at_end_of("CATEGORY"):
                self.advance()
                self.advance()
                self.expect_newline()
                break
            tok = self.peek()
            fl = tok.line
            if self.at_keyword("END"):
                raise self._err(
                    f"Expected END CATEGORY, got END "
                    f"{self.peek_at(1).value}.", fl,
                    hint=f"The CATEGORY block opened on line {ln} is still "
                         f"open.")
            if self.match_keyword("DESCRIPTION"):
                cat["description"] = self.parse_string_or_expr()
                self.expect_newline()
            elif self.match_word("PARAM"):
                ptok = self.peek()
                if ptok.type != TokenType.IDENTIFIER:
                    raise self._err(
                        "PARAM needs a name: a plain word.", fl,
                        hint="PARAM gwp_ch4 = 29.8")
                pname = self.advance().value
                if self.peek().type != TokenType.EQUALS:
                    raise self._err("Expected = after the parameter name.",
                                    fl, hint="PARAM gwp_ch4 = 29.8")
                self.advance()
                param = {"name": pname, "value": None, "formula": None,
                         "line": fl}
                if self.match_word("FORMULA"):
                    param["formula"] = self.parse_string_or_expr()
                else:
                    param["value"] = self.parse_expr()
                cat["parameters"].append(param)
                self.expect_newline()
            elif self.match_word("FACTOR"):
                cat["factors"].append(self._parse_factor(fl))
            elif self.at_keyword("REMOVE"):
                if not editing:
                    raise self._err(
                        "REMOVE FACTOR belongs in EDIT METHOD.", fl)
                self.advance()
                if not self.match_word("FACTOR"):
                    raise self._err('Expected REMOVE FACTOR "flow".', fl)
                gone = {"flow": self.parse_string_or_expr(),
                        "compartment": None, "line": fl}
                if self.match_keyword("IN"):
                    gone["compartment"] = self.parse_string_or_expr()
                cat["remove_factors"].append(gone)
                self.expect_newline()
            else:
                raise self._err(
                    f"'{tok.value}' is not a line of a CATEGORY block.", fl,
                    hint='The lines it takes: FACTOR "flow" [IN '
                         '"compartment"], value; PARAM name = value; '
                         'DESCRIPTION "text"'
                         + ('; REMOVE FACTOR "flow".' if editing else "."))
        return cat

    def _parse_factor(self, ln: int) -> dict:
        """FACTOR "flow" [IN "compartment"], value [PER unit]
        [FORMULA "x"] [LOCATION "code"] [UNCERTAINTY ...]
        or FACTOR "flow" [IN "compartment"] FORMULA "x" """
        example = 'FACTOR "Methane" IN "air", 29.8'
        if self._end_of_line():
            raise self._err("FACTOR needs a flow and a value.", ln,
                            hint=example)
        factor = {"flow": self.parse_string_or_expr(), "compartment": None,
                  "value": None, "formula": None, "unit": None,
                  "location": None, "uncertainty": None, "line": ln}
        if self.match_keyword("IN"):
            factor["compartment"] = self.parse_string_or_expr()
        if self.peek().type == TokenType.COMMA:
            self.advance()
            factor["value"] = self.parse_expr()
        while self.peek().type in (TokenType.KEYWORD, TokenType.IDENTIFIER):
            if self.match_word("FORMULA"):
                factor["formula"] = self.parse_string_or_expr()
            elif self.match_keyword("LOCATION"):
                factor["location"] = self.parse_string_or_expr()
            elif self.match_word("PER"):
                factor["unit"] = self.parse_unit()
            elif self.match_word("UNCERTAINTY"):
                factor["uncertainty"] = self.parse_uncertainty()
            else:
                raise self._err(
                    f"A FACTOR line doesn't take '{self.peek().value}'.",
                    ln, hint=example + ' [PER unit] [FORMULA "x"] '
                                       '[LOCATION "code"]')
        if factor["value"] is None and factor["formula"] is None:
            raise self._err(
                "FACTOR needs a value after a comma, or a FORMULA.", ln,
                hint=example)
        self.expect_newline()
        return factor

    def _parse_nw_set(self, ln: int) -> dict:
        """NW SET "name" [UNIT "pt"] / "category", norm [, weight] ...
        / END NW SET"""
        nw = {"name": self._name_after("NW SET", 'NW SET "World 2010"'),
              "unit": None, "description": None, "factors": [], "line": ln}
        if self.match_word("UNIT"):
            nw["unit"] = self.parse_string_or_expr()
        self.expect_newline()
        while True:
            self._skip_blank("NW SET", ln, False)
            if (self.at_keyword("END") and self.peek_at(1).upper() == "NW"
                    and self.peek_at(2).upper() == "SET"):
                for _ in range(3):
                    self.advance()
                self.expect_newline()
                break
            tok = self.peek()
            fl = tok.line
            if self.at_keyword("END"):
                raise self._err(
                    f"Expected END NW SET, got END "
                    f"{self.peek_at(1).value}.", fl)
            if self.match_keyword("DESCRIPTION"):
                nw["description"] = self.parse_string_or_expr()
                self.expect_newline()
                continue
            if tok.type != TokenType.STRING:
                raise self._err(
                    f"'{tok.value}' is not a line of an NW SET block.", fl,
                    hint='One line per category: "category", '
                         'normalisation [, weighting]. NONE leaves one '
                         'out.')
            row = {"category": self.parse_string_or_expr(),
                   "normalisation": None, "weighting": None, "line": fl}
            if self.peek().type != TokenType.COMMA:
                raise self._err(
                    "Expected a comma and the normalisation factor.", fl,
                    hint='"category", normalisation [, weighting]')
            self.advance()
            if not self.match_keyword("NONE"):
                row["normalisation"] = self.parse_expr()
            if self.peek().type == TokenType.COMMA:
                self.advance()
                if not self.match_keyword("NONE"):
                    row["weighting"] = self.parse_expr()
            if row["normalisation"] is None and row["weighting"] is None:
                raise self._err(
                    "The line gives neither a normalisation nor a "
                    "weighting factor.", fl)
            nw["factors"].append(row)
            self.expect_newline()
        return nw

    # ── MAKE PROJECT, CALCULATE PROJECT ──────────────────────

    def parse_project(self, line: int) -> ProjectStmt:
        name, folder = self._block_header("PROJECT", "MAKE")
        self.expect_newline()
        stmt = ProjectStmt(line=line, name=name, folder=folder)
        while True:
            self._skip_blank("PROJECT", line, False)
            if self._block_end("PROJECT", False, line):
                break
            tok = self.peek()
            ln = tok.line
            if self.match_word("METHOD"):
                stmt.method = self.parse_string_or_expr()
                self.expect_newline()
            elif self.at_word("NW"):
                self.advance()
                if not self.match_keyword("SET"):
                    raise self._err('Expected NW SET "name".', ln)
                stmt.nw_set = self.parse_string_or_expr()
                self.expect_newline()
            elif self.match_keyword("WITH"):
                if self.match_word("COSTS"):
                    stmt.with_costs = True
                elif self.match_word("REGIONALISATION", "REGIONALIZATION"):
                    stmt.with_regionalisation = True
                else:
                    raise self._err(
                        f"WITH '{self.peek().value}' is not something a "
                        f"project can do.", ln,
                        hint="Use WITH COSTS or WITH REGIONALISATION.")
                self.expect_newline()
            elif self.match_keyword("DESCRIPTION"):
                stmt.description = self.parse_string_or_expr()
                self.expect_newline()
            elif self.match_word("VARIANT"):
                stmt.variants.append(self._parse_variant(ln))
            else:
                raise self._err(
                    f"'{tok.value}' is not a line of a PROJECT block.", ln,
                    hint='The lines it takes: METHOD "name", NW SET '
                         '"name", WITH COSTS, WITH REGIONALISATION, '
                         'DESCRIPTION "text", VARIANT "name" SYSTEM '
                         '"system" ... END VARIANT.')
        if stmt.method is None:
            raise self._err(
                "The project needs a method.", line,
                hint='Add METHOD "method name" to the block: nothing is '
                     'assumed.')
        return stmt

    def _parse_variant(self, ln: int) -> dict:
        example = ('VARIANT "Base" SYSTEM "system name" [AMOUNT 1 kg] '
                   '[ALLOCATE PHYSICAL] [DISABLED]')
        variant = {"name": self._name_after("VARIANT", example),
                   "system": None, "amount": None, "unit": None,
                   "allocation": None, "disabled": False,
                   "description": None, "values": [], "line": ln}
        while self.peek().type in (TokenType.KEYWORD, TokenType.IDENTIFIER):
            if self.match_keyword("SYSTEM"):
                variant["system"] = self.parse_string_or_expr()
            elif self.match_word("AMOUNT"):
                variant["amount"] = self.parse_expr()
                if self.peek().type == TokenType.COMMA:
                    self.advance()
                if self.peek().type not in (TokenType.IDENTIFIER,
                                            TokenType.KEYWORD):
                    raise self._err("AMOUNT needs a unit.", ln,
                                    hint="For example: AMOUNT 2.5 kg")
                variant["unit"] = self.parse_unit()
            elif self.match_keyword("ALLOCATE"):
                variant["allocation"] = self.parse_allocation()
            elif self.match_word("DISABLED"):
                variant["disabled"] = True
            else:
                raise self._err(
                    f"A VARIANT line doesn't take '{self.peek().value}'.",
                    ln, hint=example)
        if variant["system"] is None:
            raise self._err("A variant needs a product system.", ln,
                            hint=example)
        self.expect_newline()
        while True:
            self._skip_blank("VARIANT", ln, False)
            if self.at_keyword("END") and self.peek_at(1).upper() == "VARIANT":
                self.advance()
                self.advance()
                self.expect_newline()
                break
            tok = self.peek()
            fl = tok.line
            if self.at_keyword("END") or self.at_word("VARIANT"):
                raise self._err(
                    f"The VARIANT block opened on line {ln} is missing "
                    f"END VARIANT.", fl)
            if self.match_keyword("DESCRIPTION"):
                variant["description"] = self.parse_string_or_expr()
                self.expect_newline()
                continue
            if (tok.type == TokenType.IDENTIFIER
                    and self.peek_at(1).type == TokenType.EQUALS):
                pname = self.advance().value
                self.advance()
                value = {"name": pname, "value": self.parse_expr(),
                         "process": None, "line": fl}
                if self.match_keyword("IN"):
                    if not self.match_keyword("PROCESS"):
                        raise self._err('Expected IN PROCESS "name".', fl)
                    value["process"] = self.parse_string_or_expr()
                variant["values"].append(value)
                self.expect_newline()
                continue
            raise self._err(
                f"'{tok.value}' is not a line of a VARIANT block.", fl,
                hint='The lines it takes: name = value [IN PROCESS '
                     '"process"], DESCRIPTION "text", then END VARIANT.')
        return variant

    def parse_calculate_project(self, line: int) -> CalculateProjectStmt:
        self.advance()  # PROJECT
        name = self._name_after("CALCULATE PROJECT",
                                'CALCULATE PROJECT "project name"')
        self.expect_newline()
        return CalculateProjectStmt(line=line, name=name)

    # ── SAVE RESULT AS, SHUTDOWN SERVER ──────────────────────

    def parse_save_result_as(self, line: int) -> SaveResultAsStmt:
        """After SAVE RESULT AS."""
        example = 'SAVE RESULT AS "name" [FOLDER "path"] [REPLACE] [IN name]'
        stmt = SaveResultAsStmt(
            line=line, name=self._name_after("SAVE RESULT AS", example))
        while self.peek().type in (TokenType.KEYWORD, TokenType.IDENTIFIER):
            if self.match_keyword("FOLDER"):
                stmt.folder = self.parse_string_or_expr()
            elif self.match_word("REPLACE"):
                stmt.replace = True
            elif self.match_keyword("DESCRIPTION"):
                stmt.description = self.parse_string_or_expr()
            elif self.match_keyword("IN"):
                tok = self.peek()
                if tok.type != TokenType.IDENTIFIER:
                    raise self._err(
                        "IN needs the name of an open result: a plain "
                        "word.", line, hint=example)
                stmt.result_name = self.advance().value
            else:
                raise self._err(
                    f"SAVE RESULT AS doesn't take '{self.peek().value}'.",
                    line, hint=example)
        self.expect_newline()
        return stmt

    def parse_shutdown(self, line: int) -> ShutdownStmt:
        self.advance()  # SHUTDOWN
        self.advance()  # SERVER
        stmt = ShutdownStmt(line=line)
        if self.match_keyword("CONFIRM"):
            stmt.confirm = True
        self.expect_newline()
        return stmt
