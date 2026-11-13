"""
Parser for olcaBASIC.

Consumes a token list and produces a list of AST nodes.
Handles block structures (PROCESS/END PROCESS, IF/END IF, etc.)
by recursive descent.
"""

from typing import List, Optional, Tuple
from .tokeniser import (Token, TokenType, TokeniseError,
                        tokenise, tokenise_line)
from .ast_nodes import *
from .parser_results import ResultsParserMixin, RESULT_HEADS
from .parser_fields import FieldsParserMixin
from .parser_entities import EntitiesParserMixin, SIMPLE_TYPES
from .parser_toolkit import ToolkitParserMixin


class ParseError(Exception):
    """A program that does not parse. Carries the line and, where the
    message does not already say it, a hint on what to type instead."""

    def __init__(self, message: str, line: int = 0, hint: str = ""):
        self.line = line
        self.message = message
        self.hint = hint
        full = f"{message} {hint}".strip() if hint else message
        super().__init__(f"Line {line}: {full}" if line else full)


class Parser(ResultsParserMixin, FieldsParserMixin, EntitiesParserMixin,
             ToolkitParserMixin):
    """Recursive descent parser for olcaBASIC."""

    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    # ── Token navigation ─────────────────────────────────

    def peek(self) -> Token:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return Token(TokenType.EOF, "")

    def advance(self) -> Token:
        tok = self.peek()
        self.pos += 1
        return tok

    def expect_keyword(self, *keywords: str) -> Token:
        tok = self.peek()
        if tok.type == TokenType.KEYWORD and tok.upper() in keywords:
            return self.advance()
        expected = " or ".join(keywords)
        raise ParseError(
            f"Expected {expected}, got '{tok.value}'", tok.line)

    def match_keyword(self, *keywords: str) -> Optional[Token]:
        tok = self.peek()
        if tok.type == TokenType.KEYWORD and tok.upper() in keywords:
            return self.advance()
        return None

    def at_keyword(self, *keywords: str) -> bool:
        tok = self.peek()
        return (tok.type == TokenType.KEYWORD
                and tok.upper() in keywords)

    def at_word(self, *words: str) -> bool:
        """Like at_keyword, but also accepts a plain identifier.
        Used for sub-keywords (OFF, METHOD, AT, PARAM...) so they
        don't become reserved words everywhere."""
        tok = self.peek()
        return (tok.type in (TokenType.KEYWORD, TokenType.IDENTIFIER)
                and tok.upper() in words)

    def match_word(self, *words: str) -> Optional[Token]:
        if self.at_word(*words):
            return self.advance()
        return None

    def parse_int(self, what: str) -> int:
        tok = self.peek()
        if tok.type != TokenType.NUMBER:
            raise ParseError(f"Expected a number after {what}, "
                             f"got '{tok.value}'", tok.line)
        self.advance()
        return int(float(tok.value))

    def parse_number(self, what: str) -> float:
        tok = self.peek()
        if tok.type != TokenType.NUMBER:
            raise ParseError(f"Expected a number after {what}, "
                             f"got '{tok.value}'", tok.line)
        self.advance()
        return float(tok.value)

    ALLOCATIONS = ("AS_DEFINED", "PHYSICAL", "ECONOMIC", "CAUSAL", "NONE")
    LINKINGS = ("PREFER_DEFAULTS", "ONLY_DEFAULTS", "ONLY_LINK_PROVIDERS",
                "IGNORE_DEFAULTS")

    def parse_allocation(self) -> str:
        """The word after ALLOCATE: one of ALLOCATIONS."""
        tok = self.peek()
        if (tok.type in (TokenType.KEYWORD, TokenType.IDENTIFIER)
                and tok.upper() in self.ALLOCATIONS):
            return self.advance().upper()
        shown = tok.value if tok.type not in (TokenType.NEWLINE,
                                              TokenType.EOF) else ""
        raise ParseError(
            f"Unknown allocation method '{shown}'." if shown
            else "ALLOCATE needs a method.",
            tok.line,
            hint="Use one of: " + ", ".join(self.ALLOCATIONS) + ".")

    @staticmethod
    def _defaulted(**given) -> tuple:
        """Names of the optional arguments that were left out."""
        return tuple(name for name, value in given.items() if not value)

    def peek_at(self, offset: int) -> Token:
        i = self.pos + offset
        if i < len(self.tokens):
            return self.tokens[i]
        return Token(TokenType.EOF, "")

    def at_end_of(self, block: str) -> bool:
        """True if the next tokens are END <block>."""
        return (self.at_keyword("END")
                and self.peek_at(1).upper() == block)

    def skip_newlines(self):
        while self.peek().type in (TokenType.NEWLINE, TokenType.COMMENT):
            self.advance()

    def expect_newline(self):
        tok = self.peek()
        if tok.type in (TokenType.NEWLINE, TokenType.EOF,
                        TokenType.COMMENT):
            if tok.type == TokenType.COMMENT:
                self.advance()
            if self.peek().type == TokenType.NEWLINE:
                self.advance()
            return
        # Anything left on the line was not understood. Refuse it
        # rather than silently dropping part of the statement.
        raise ParseError(
            f"Unexpected '{tok.value}' at end of statement", tok.line)

    def current_line(self) -> int:
        return self.peek().line

    # ── Expression parsing ───────────────────────────────

    def parse_expr(self) -> Expr:
        """Parse an expression with operator precedence."""
        return self.parse_or_expr()

    def parse_or_expr(self) -> Expr:
        left = self.parse_and_expr()
        while self.match_keyword("OR"):
            right = self.parse_and_expr()
            left = LogicalOp(left, "OR", right)
        return left

    def parse_and_expr(self) -> Expr:
        left = self.parse_comparison()
        while self.match_keyword("AND"):
            right = self.parse_comparison()
            left = LogicalOp(left, "AND", right)
        return left

    def parse_comparison(self) -> Expr:
        left = self.parse_add_expr()
        tok = self.peek()
        if tok.type in (TokenType.EQUALS, TokenType.NOT_EQ,
                        TokenType.LESS, TokenType.GREATER,
                        TokenType.LESS_EQ, TokenType.GREATER_EQ):
            op = self.advance().value
            right = self.parse_add_expr()
            return Comparison(left, op, right)
        return left

    def parse_add_expr(self) -> Expr:
        left = self.parse_mul_expr()
        while True:
            tok = self.peek()
            if tok.type == TokenType.PLUS:
                self.advance()
                right = self.parse_mul_expr()
                # String concatenation if either side is a string
                if isinstance(left, StringLiteral) or isinstance(right, StringLiteral):
                    left = StringConcat(left, right)
                else:
                    left = BinOp(left, "+", right)
            elif tok.type == TokenType.MINUS:
                self.advance()
                right = self.parse_mul_expr()
                left = BinOp(left, "-", right)
            else:
                break
        return left

    def parse_mul_expr(self) -> Expr:
        left = self.parse_unary()
        while True:
            tok = self.peek()
            if tok.type == TokenType.STAR:
                self.advance()
                right = self.parse_unary()
                left = BinOp(left, "*", right)
            elif tok.type == TokenType.SLASH:
                self.advance()
                right = self.parse_unary()
                left = BinOp(left, "/", right)
            else:
                break
        return left

    def parse_unary(self) -> Expr:
        tok = self.peek()
        if tok.type == TokenType.MINUS:
            self.advance()
            operand = self.parse_power()
            return UnaryOp("-", operand)
        if tok.type == TokenType.KEYWORD and tok.upper() == "NOT":
            self.advance()
            operand = self.parse_comparison()
            return UnaryOp("NOT", operand)
        return self.parse_power()

    def parse_power(self) -> Expr:
        base = self.parse_primary()
        if self.peek().type == TokenType.CARET:
            self.advance()
            exponent = self.parse_unary()   # right-associative
            return BinOp(base, "^", exponent)
        return base

    def parse_primary(self) -> Expr:
        tok = self.peek()

        if tok.type == TokenType.NUMBER:
            self.advance()
            return NumberLiteral(float(tok.value))

        if tok.type == TokenType.STRING:
            self.advance()
            return StringLiteral(tok.value)

        if tok.type == TokenType.LPAREN:
            self.advance()
            expr = self.parse_expr()
            if self.peek().type != TokenType.RPAREN:
                raise ParseError("Missing closing ')'", tok.line)
            self.advance()
            return expr

        if tok.type == TokenType.IDENTIFIER:
            name = tok.value
            self.advance()
            # Check for function call: name(args)
            if self.peek().type == TokenType.LPAREN:
                self.advance()
                args = []
                while self.peek().type != TokenType.RPAREN:
                    args.append(self.parse_expr())
                    if self.peek().type == TokenType.COMMA:
                        self.advance()
                if self.peek().type == TokenType.RPAREN:
                    self.advance()
                return FuncCall(name, args)
            return Identifier(name)

        # A keyword that is also a built-in function: MAX(a, b)
        if (tok.type == TokenType.KEYWORD and tok.upper() in ("MAX",)
                and self.peek_at(1).type == TokenType.LPAREN):
            self.advance()
            self.advance()
            args = []
            while self.peek().type != TokenType.RPAREN:
                args.append(self.parse_expr())
                if self.peek().type == TokenType.COMMA:
                    self.advance()
            self.advance()
            return FuncCall(tok.value, args)

        # Allow keywords to be used as identifiers in expressions
        # (e.g. unit names like "kg" which might also be keywords)
        if tok.type == TokenType.KEYWORD:
            self.advance()
            return Identifier(tok.value)

        raise ParseError(f"Unexpected token: '{tok.value}'", tok.line)

    def parse_string_or_expr(self) -> Expr:
        """Parse something that is expected to be a string
        (but could be an expression like project$ + '/Bridges')."""
        return self.parse_expr()

    # ── Unit parsing ─────────────────────────────────────

    def parse_unit(self) -> str:
        """Parse a unit name. Units can be identifiers, keywords,
        or compound forms like t*km or Item(s)."""
        tok = self.peek()
        if tok.type in (TokenType.IDENTIFIER, TokenType.KEYWORD):
            unit = self.advance().value
            # Handle compound units like t*km
            if self.peek().type == TokenType.STAR:
                self.advance()
                tok2 = self.peek()
                if tok2.type in (TokenType.IDENTIFIER, TokenType.KEYWORD):
                    unit += "*" + self.advance().value
            # Handle Item(s)
            if self.peek().type == TokenType.LPAREN:
                self.advance()
                if self.peek().type in (TokenType.IDENTIFIER,
                                         TokenType.KEYWORD):
                    unit += "(" + self.advance().value + ")"
                    if self.peek().type == TokenType.RPAREN:
                        self.advance()
            return unit
        raise ParseError(f"Expected unit, got '{tok.value}'", tok.line)

    # ── Statement parsing ────────────────────────────────

    def parse_program(self) -> List[Statement]:
        """Parse a complete program."""
        statements = []
        while self.peek().type != TokenType.EOF:
            self.skip_newlines()
            if self.peek().type == TokenType.EOF:
                break
            stmt = self.parse_statement()
            if stmt is not None:
                statements.append(stmt)
        return statements

    def parse_statement(self) -> Optional[Statement]:
        """Parse a single statement."""
        tok = self.peek()
        line = tok.line

        if tok.type == TokenType.COMMENT:
            self.advance()
            self.expect_newline()
            return CommentStmt(line=line, text=tok.value)

        if tok.type == TokenType.NEWLINE:
            self.advance()
            return None

        if tok.type == TokenType.NUMBER:
            raise ParseError(
                "Line numbers are not supported (and neither is GOTO); "
                "remove the number at the start of the line", line)

        if tok.type != TokenType.KEYWORD and tok.type != TokenType.IDENTIFIER:
            raise ParseError(f"Unexpected '{tok.value}'", line)

        # Implicit LET: name = expr
        if (tok.type == TokenType.IDENTIFIER
                and self.peek_at(1).type == TokenType.EQUALS):
            return self.parse_let(line, implicit=True)

        if (tok.type == TokenType.IDENTIFIER
                and tok.upper() in ("PARAMETERISE", "PARAMETERIZE")
                and self.peek_at(1).upper() == "PROCESS"):
            return self.parse_parameterise(line)

        # EPD workflow. EPD and MODULE are not reserved words (so they
        # stay usable as variable names); they are recognised here.
        if tok.type == TokenType.IDENTIFIER and tok.upper() == "EPD":
            return self.parse_epd(line)
        if (tok.type == TokenType.IDENTIFIER and tok.upper() == "MODULE"
                and self.peek_at(1).type == TokenType.IDENTIFIER):
            return self.parse_module(line)

        # Results that stay open. RESULT and CLOSE are not reserved
        # words either.
        if (tok.type == TokenType.IDENTIFIER and tok.upper() == "RESULT"
                and self.peek_at(1).upper() in RESULT_HEADS):
            return self.parse_result_query(line)
        if (tok.type == TokenType.IDENTIFIER and tok.upper() == "CLOSE"
                and self.peek_at(1).upper() == "RESULT"):
            return self.parse_close_result(line)
        if (tok.type == TokenType.IDENTIFIER and tok.upper() == "SHUTDOWN"
                and self.peek_at(1).upper() == "SERVER"):
            return self.parse_shutdown(line)

        kw = tok.upper() if tok.type == TokenType.KEYWORD else ""

        # ── Core BASIC ───────────────────────────────
        if kw == "REM":
            self.advance()
            self.expect_newline()
            return CommentStmt(line=line, text=tok.value)

        if kw == "LET":
            return self.parse_let(line)

        if kw == "PRINT":
            return self.parse_print(line)

        if kw == "INPUT" and not self._inside_process:
            return self.parse_input_prompt(line)

        if kw == "DATA":
            return self.parse_data(line)

        if kw == "IF":
            return self.parse_if(line)

        if kw == "FOR":
            return self.parse_for(line)

        if kw == "WHILE":
            return self.parse_while(line)

        if kw == "SUB":
            return self.parse_sub_def(line)

        if kw == "FUNCTION":
            return self.parse_function_def(line)

        # ── LCA entities ─────────────────────────────
        if kw == "FLOW":
            return self.parse_flow(line)

        if kw == "BRIDGE":
            return self.parse_bridge(line)

        if kw == "PROCESS":
            return self.parse_process(line)

        if kw == "MAKE":
            return self.parse_make(line)

        if kw == "SHOW":
            return self.parse_show(line)

        if kw == "LINK":
            return self.parse_link(line)

        if kw == "EDIT":
            if self.peek_at(1).upper() == "FLOW":
                return self.parse_edit_flow(line)
            if self.peek_at(1).upper() == "SYSTEM":
                return self.parse_edit_system(line)
            if self.peek_at(1).upper() != "PROCESS":
                self.advance()  # EDIT
                etype, n = self.peek_entity_type()
                if etype == "METHOD":
                    for _ in range(n):
                        self.advance()
                    return self.parse_method(line, editing=True)
                if etype in SIMPLE_TYPES:
                    for _ in range(n):
                        self.advance()
                    return self.parse_make_entity(line, etype, editing=True)
                raise ParseError(
                    f"EDIT cannot change '{self.peek().value}'.", line,
                    hint="EDIT takes PROCESS, FLOW, SYSTEM, METHOD, ACTOR, "
                         "SOURCE, CURRENCY, LOCATION, UNITS, PROPERTY, "
                         "SOCIAL INDICATOR or DQ SYSTEM.")
            return self.parse_edit(line)

        if kw == "UPDATE":
            return self.parse_update_param(line)

        if kw == "SYSTEM":
            return self.parse_system(line)

        # ── Calculations ─────────────────────────────
        if kw == "CALCULATE":
            return self.parse_calculate(line)

        if kw == "CONTRIBUTION":
            return self.parse_contribution(line)

        if kw == "INVENTORY":
            return self.parse_inventory(line)

        if kw == "MONTECARLO":
            return self.parse_montecarlo(line)

        if kw == "SENSITIVITY":
            return self.parse_sensitivity(line)

        if kw == "SCENARIO":
            return self.parse_scenario(line)

        if kw == "RUN":
            return self.parse_run(line)

        # ── Audit ────────────────────────────────────
        if kw == "VALIDATE":
            return self.parse_validate(line)

        if kw == "CHECK":
            return self.parse_check(line)

        if kw == "EXTRACT":
            return self.parse_extract(line)

        if kw == "AUDIT":
            return self.parse_audit(line)

        # ── Output ───────────────────────────────────
        if kw == "SAVE":
            return self.parse_save(line)

        if kw == "EXPORT":
            return self.parse_export(line)

        # ── Navigation and tree ──────────────────────
        if kw == "TREE":
            return self.parse_tree(line)

        if kw == "NAVIGATE":
            return self.parse_navigate(line)

        if kw == "MOVE":
            return self.parse_move(line)

        # ── Delete ───────────────────────────────────
        if kw == "DELETE":
            return self.parse_delete(line)

        if kw == "CONFIRM":
            return self.parse_confirm(line)

        # ── File ops ─────────────────────────────────
        if kw == "INCLUDE":
            return self.parse_include(line)

        # ── REPL commands ────────────────────────────
        if kw == "HELP":
            self.advance()
            # HELP, HELP topic, HELP MAKE PROCESS, HELP "CD .."
            words = []
            while self.peek().type not in (TokenType.NEWLINE, TokenType.EOF,
                                           TokenType.COMMENT):
                words.append(self.advance().value)
            self.expect_newline()
            return HelpStmt(line=line, topic=" ".join(words))

        if kw == "CLEAR":
            self.advance()
            self.expect_newline()
            return ClearStmt(line=line)

        if kw == "REFRESH":
            self.advance()
            self.expect_newline()
            return RefreshStmt(line=line)

        if kw in ("EXIT", "QUIT"):
            self.advance()
            self.expect_newline()
            return ExitStmt(line=line)

        if kw == "FIND":
            return self.parse_find(line)

        if kw == "SET":
            return self.parse_set(line)

        if kw == "CAT":
            return self.parse_cat(line)

        if kw == "LS":
            return self.parse_cat(line)  # Linux alias

        if kw == "DIR":
            return self.parse_dir_nav(line)

        if kw == "CD":
            return self.parse_dir_nav(line)  # Linux form of DIR

        if kw == "MKDIR":
            self.advance()
            if self.peek().type in (TokenType.NEWLINE, TokenType.EOF,
                                    TokenType.COMMENT):
                raise ParseError("MKDIR needs a folder name.", line,
                                 hint='For example: MKDIR "00: My model"')
            name = self.parse_string_or_expr()
            self.expect_newline()
            return MkdirStmt(line=line, name=name)

        if kw == "PWD":
            self.advance()
            self.expect_newline()
            return PwdStmt(line=line)

        if kw == "UP":
            self.advance()
            self.expect_newline()
            return UpStmt(line=line)

        if kw == "BACK":
            self.advance()
            self.expect_newline()
            return BackStmt(line=line)

        if kw == "CDIR":
            self.advance()
            name = self.parse_string_or_expr()
            self.expect_newline()
            return CdirStmt(line=line, name=name)

        if kw == "DATABASE":
            return self.parse_database_cmd(line)

        # ── Identifier as SUB call ───────────────────
        if tok.type == TokenType.IDENTIFIER:
            return self.parse_sub_call(line)

        if kw == "NEW" and self.peek_at(1).upper() == "FROM":
            return self.parse_new_from_template(line)

        if kw == "LOAD":
            self.advance()
            filename = self.parse_string_or_expr()
            self.expect_newline()
            return LoadStmt(line=line, filename=filename)

        if kw == "LIST":
            self.advance()
            self.expect_newline()
            return ListStmt(line=line)

        # Known BASIC keywords we don't implement: say so plainly
        if kw in ("GOTO", "GOSUB", "RETURN", "ON",
                  "HISTORY", "INSPECT", "NEW"):
            raise ParseError(f"{kw} is not supported in olcaBASIC", line)

        raise ParseError(f"'{tok.value}' cannot start a statement", line)

    # ── Flags ────────────────────────────────────────────

    _inside_process = False

    # ── Individual statement parsers ─────────────────────

    def parse_let(self, line: int, implicit: bool = False) -> LetStmt:
        if not implicit:
            self.advance()  # consume LET (or PARAM / SET)
        tok = self.peek()
        if tok.type == TokenType.KEYWORD:
            raise ParseError(
                f"'{tok.value}' is a reserved word and can't be used "
                f"as a variable name (try my_{tok.value.lower()})", line)
        if tok.type != TokenType.IDENTIFIER:
            raise ParseError(f"Expected variable name after LET", line)
        name = self.advance().value
        if self.peek().type != TokenType.EQUALS:
            raise ParseError(f"Expected '=' after '{name}'", line)
        self.advance()  # consume =
        expr = self.parse_expr()
        stmt = LetStmt(line=line, name=name, expr=expr)
        if self.match_word("UNCERTAINTY"):
            stmt.uncertainty = self.parse_uncertainty()
        self.expect_newline()
        return stmt

    def parse_print(self, line: int) -> Statement:
        self.advance()  # consume PRINT
        tok = self.peek()

        # PRINT RESULTS
        if tok.type == TokenType.KEYWORD and tok.upper() == "RESULTS":
            self.advance()
            self.expect_newline()
            return PrintResultsStmt(line=line)

        # PRINT sub-commands: DATABASE, PROCESSES, METHODS, etc.
        sub_cmds = {
            "DATABASE", "PROCESSES", "METHODS", "SYSTEMS",
            "FLOWS", "PARAMS", "DETAILS", "QUALITY",
            "LINKS", "UNITS", "GLOBAL", "DQ",
        }
        if tok.type == TokenType.KEYWORD and tok.upper() in sub_cmds:
            sub = self.advance().upper()

            # Handle PRINT GLOBAL PARAMS
            if sub == "GLOBAL" and self.at_keyword("PARAMS"):
                self.advance()
                sub = "GLOBAL_PARAMS"

            # Handle PRINT DQ SYSTEMS
            if sub == "DQ" and self.at_keyword("SYSTEMS"):
                self.advance()
                sub = "DQ_SYSTEMS"

            # Parse optional arguments in parentheses
            args = []
            if self.peek().type == TokenType.LPAREN:
                self.advance()
                while self.peek().type != TokenType.RPAREN:
                    args.append(self.parse_expr())
                    if self.peek().type == TokenType.COMMA:
                        self.advance()
                if self.peek().type == TokenType.RPAREN:
                    self.advance()

            self.expect_newline()
            return PrintStmt(line=line, sub_command=sub, args=args)

        # PRINT expression
        expr = self.parse_expr()
        more = []
        while self.peek().type == TokenType.COMMA:
            self.advance()
            more.append(self.parse_expr())

        self.expect_newline()
        if more:
            # Multiple expressions — store as first expr + args in PrintStmt
            return PrintStmt(line=line, sub_command="EXPR",
                             args=[expr] + more)
        return PrintExprStmt(line=line, expr=expr)

    def parse_input_prompt(self, line: int) -> InputStmt:
        self.advance()  # consume INPUT
        prompt = self.parse_string_or_expr()
        prompt_val = prompt.value if isinstance(prompt, StringLiteral) else str(prompt)
        if self.peek().type == TokenType.COMMA:
            self.advance()
        var_tok = self.peek()
        if var_tok.type != TokenType.IDENTIFIER:
            raise ParseError("Expected variable name after INPUT prompt", line)
        var_name = self.advance().value
        self.expect_newline()
        return InputStmt(line=line, prompt=prompt_val, variable=var_name)

    def parse_data(self, line: int) -> DataStmt:
        self.advance()  # consume DATA
        values = []
        while self.peek().type not in (TokenType.NEWLINE, TokenType.EOF,
                                        TokenType.COMMENT):
            val = self.parse_expr()
            values.append(val)
            if self.peek().type == TokenType.COMMA:
                self.advance()
        self.expect_newline()
        return DataStmt(line=line, values=values)

    def parse_flow(self, line: int) -> FlowStmt:
        self.advance()  # consume FLOW

        # Check for NEW keyword
        is_new = False
        if self.match_keyword("NEW"):
            is_new = True

        name = self.parse_string_or_expr()
        if self.peek().type == TokenType.COMMA:
            self.advance()
        unit = self.parse_unit()
        if self.peek().type == TokenType.COMMA:
            self.advance()

        flow_type = "PRODUCT"
        folder = None
        direction = ""
        fields = {}

        # Parse type and modifiers
        while (self.peek().type == TokenType.KEYWORD
               or self.at_word("CAS", "SYNONYMS", "INFRASTRUCTURE")):
            kw = self.peek().upper()
            if kw in ("CAS", "FORMULA", "SYNONYMS", "DESCRIPTION",
                      "LOCATION"):
                self.advance()
                fields[kw.lower()] = self.parse_string_or_expr()
            elif kw == "INFRASTRUCTURE":
                self.advance()
                fields["infrastructure"] = True
            elif kw in ("PRODUCT", "WASTE", "ELEMENTARY"):
                flow_type = self.advance().upper()
            elif kw == "TO":
                self.advance()
                flow_type = "ELEMENTARY"
                if self.at_keyword("AIR"):
                    direction = "AIR"
                    self.advance()
                elif self.at_keyword("WATER"):
                    direction = "WATER"
                    self.advance()
                elif self.at_keyword("SOIL"):
                    direction = "SOIL"
                    self.advance()
            elif kw == "FROM":
                self.advance()
                if self.at_keyword("NATURE"):
                    self.advance()
                    flow_type = "ELEMENTARY"
                    direction = "NATURE"
            elif kw == "FOLDER":
                self.advance()
                folder = self.parse_string_or_expr()
            elif kw == "AS":
                self.advance()
                if self.at_keyword("PRODUCT", "WASTE", "ELEMENTARY"):
                    flow_type = self.advance().upper()
            else:
                break
            if self.peek().type == TokenType.COMMA:
                self.advance()

        self.expect_newline()
        return FlowStmt(line=line, name=name, unit=unit,
                         flow_type=flow_type, folder=folder,
                         direction=direction, is_new=is_new, fields=fields)

    def parse_bridge(self, line: int) -> BridgeStmt:
        self.advance()  # consume BRIDGE
        name = self.parse_string_or_expr()
        if self.peek().type == TokenType.COMMA:
            self.advance()
        unit = self.parse_unit()

        is_waste = False
        folder = None
        provider = None
        provider_flow = None
        extra = {}

        # Check for WASTE on same line
        if self.match_keyword("WASTE"):
            is_waste = True

        # Check if this is a block (next meaningful token is FOLDER/PROVIDER/END)
        # or a single-line bridge
        if self.peek().type in (TokenType.NEWLINE, TokenType.COMMENT,
                                TokenType.EOF):
            self.expect_newline()
            # Check for block continuation
            self.skip_newlines()
            if (self.at_keyword("FOLDER", "PROVIDER", "WASTE", "DATA",
                                "LOCATION")
                    or self.at_word("ELECTRICITY", "COUNTRY", "REGION",
                                    "ENERGY", "RATING")
                    or self.at_end_of("BRIDGE")):
                # Block form
                while not self.at_keyword("END"):
                    if self.peek().type == TokenType.EOF:
                        break
                    if self.match_keyword("FOLDER"):
                        folder = self.parse_string_or_expr()
                    elif self.match_keyword("PROVIDER"):
                        if self.match_keyword("FLOW"):
                            provider_flow = self.parse_string_or_expr()
                        else:
                            provider = self.parse_string_or_expr()
                            if (self.at_keyword("LOCATION")
                                    and self.peek_at(1).upper() != "BASED"):
                                self.advance()
                                extra["provider_location"] = \
                                    self.parse_string_or_expr()
                    elif self.match_keyword("WASTE"):
                        is_waste = True
                    elif self.at_keyword("DATA"):
                        extra["provenance"] = self.parse_provenance()
                    elif self.match_word("RATING"):
                        self.parse_rating(extra.setdefault("ratings", {}))
                    elif self.match_word("ELECTRICITY"):
                        if not self.at_word("CONTRACT", "RESIDUAL",
                                            "CONSUMPTION"):
                            raise ParseError(
                                "ELECTRICITY needs the modelling approach.",
                                self.current_line(),
                                hint="ELECTRICITY CONTRACT (a contractual "
                                     "instrument), ELECTRICITY RESIDUAL "
                                     "(the residual mix) or ELECTRICITY "
                                     "CONSUMPTION (the consumption mix).")
                        extra["electricity"] = self.advance().upper()
                    elif self.match_word("COUNTRY"):
                        extra["country"] = self.parse_string_or_expr()
                    elif self.match_word("REGION"):
                        extra["region"] = self.parse_string_or_expr()
                    elif self.match_word("ENERGY"):
                        if not self.match_word("SOURCE"):
                            raise ParseError(
                                "Expected ENERGY SOURCE \"text\".",
                                self.current_line())
                        extra["energy_source"] = self.parse_string_or_expr()
                    elif self.match_keyword("LOCATION"):
                        if not (self.match_word("BASED")
                                and self.match_keyword("PROVIDER")):
                            raise ParseError(
                                "Expected LOCATION BASED PROVIDER \"process "
                                "name or uuid\".", self.current_line())
                        extra["location_based_provider"] = \
                            self.parse_string_or_expr()
                    else:
                        raise ParseError(
                            f"'{self.peek().value}' is not allowed inside "
                            f"BRIDGE (expected FOLDER, PROVIDER, WASTE, DATA, "
                            f"RATING, ELECTRICITY, COUNTRY, REGION, ENERGY "
                            f"SOURCE, LOCATION BASED PROVIDER or END BRIDGE)",
                            self.current_line())
                    self.expect_newline()
                    self.skip_newlines()

                # Consume END BRIDGE
                if self.match_keyword("END"):
                    self.match_keyword("BRIDGE")
                self.expect_newline()
        else:
            self.expect_newline()

        return BridgeStmt(line=line, name=name, unit=unit,
                           is_waste=is_waste, folder=folder,
                           provider=provider, provider_flow=provider_flow,
                           **extra)

    def parse_process(self, line: int) -> ProcessStmt:
        self.advance()  # consume PROCESS
        name = self.parse_string_or_expr()

        location = None
        folder = None
        description = None
        flow_schema = None
        process_schema = None

        # Same-line modifiers
        if self.match_keyword("LOCATION"):
            location = self.parse_string_or_expr()

        self.expect_newline()
        self.skip_newlines()

        exchanges = []
        local_params = []
        read_data = False
        provenance = None
        ratings = {}
        control = ""
        fields = {}

        self._inside_process = True

        while not self.at_keyword("END"):
            if self.peek().type == TokenType.EOF:
                raise ParseError("PROCESS block missing END PROCESS", line)

            tok = self.peek()
            kw = tok.upper() if tok.type == TokenType.KEYWORD else ""

            if kw == "FOLDER":
                self.advance()
                folder = self.parse_string_or_expr()
                self.expect_newline()

            elif kw == "LOCATION":
                self.advance()
                location = self.parse_string_or_expr()
                self.expect_newline()

            elif kw == "DESCRIPTION":
                self.advance()
                description = self.parse_string_or_expr()
                self.expect_newline()

            elif kw == "FLOW" and self.peek_at(1).upper() == "SCHEMA":
                self.advance()  # FLOW
                self.advance()  # SCHEMA
                flow_schema = self.parse_string_or_expr()
                self.expect_newline()

            elif kw == "PROCESS" and self.peek_at(1).upper() == "SCHEMA":
                self.advance()  # PROCESS
                self.advance()  # SCHEMA
                process_schema = self.parse_string_or_expr()
                self.expect_newline()

            elif self.at_process_field():
                self.parse_process_field(fields)

            elif kw in ("INPUT", "OUTPUT"):
                ex = self.parse_exchange()
                exchanges.append(ex)

            elif kw == "LET" or self.at_word("PARAM"):
                stmt = self.parse_let(tok.line)
                local_params.append(stmt)

            elif kw == "DATA":
                provenance = self.parse_provenance()
                self.expect_newline()

            elif self.at_word("RATING"):
                self.advance()
                self.parse_rating(ratings)
                self.expect_newline()

            elif self.at_word("CONTROL"):
                control = self.parse_control()
                self.expect_newline()

            elif kw == "READ":
                self.advance()
                self.match_keyword("INPUTS")
                self.match_keyword("FROM")
                self.match_keyword("DATA")
                read_data = True
                self.expect_newline()

            elif tok.type in (TokenType.COMMENT, TokenType.NEWLINE):
                self.advance()

            else:
                self._inside_process = False
                raise ParseError(
                    f"'{tok.value}' is not allowed inside PROCESS "
                    f"(expected INPUT, OUTPUT, LET, FOLDER, LOCATION, "
                    f"DESCRIPTION, DATA, CONTROL, ALLOCATION, DEFAULT "
                    f"ALLOCATION, DOCUMENT, SOCIAL, TYPE, INFRASTRUCTURE or "
                    f"END PROCESS)", tok.line)

            self.skip_newlines()

        self._inside_process = False

        # Consume END PROCESS
        self.expect_keyword("END")
        self.match_keyword("PROCESS")
        self.expect_newline()

        return ProcessStmt(
            line=line, name=name, location=location, folder=folder,
            description=description, flow_schema=flow_schema,
            process_schema=process_schema, exchanges=exchanges,
            local_params=local_params, read_data=read_data,
            provenance=provenance, control=control, fields=fields,
            ratings=ratings)

    def parse_pedigree(self):
        """PEDIGREE (1,2,1,1,3) or PEDIGREE "(1;2;1;1;3)" """
        if self.peek().type == TokenType.STRING:
            return self.advance().value
        if self.peek().type != TokenType.LPAREN:
            raise ParseError("PEDIGREE needs scores in brackets, e.g. "
                             "PEDIGREE (1,2,1,1,3)", self.current_line())
        self.advance()
        scores = []
        while True:
            tok = self.peek()
            if tok.type != TokenType.NUMBER:
                raise ParseError(f"Expected a pedigree score, got "
                                 f"'{tok.value}'", self.current_line())
            self.advance()
            scores.append(int(float(tok.value)))
            if self.peek().type == TokenType.COMMA:
                self.advance()
                continue
            break
        if self.peek().type != TokenType.RPAREN:
            raise ParseError("Missing ')' after pedigree scores",
                             self.current_line())
        self.advance()
        for n in scores:
            if not 1 <= n <= 5:
                raise ParseError(f"Pedigree scores run from 1 to 5, got {n}",
                                 self.current_line())
        return scores

    def parse_exchange(self) -> ExchangeDef:
        """Parse an INPUT or OUTPUT line inside a PROCESS block.
        Supports: INPUT USE PROCESS "name", INPUT USE FLOW "name",
        INPUT MAKE FLOW "name", and legacy INPUT NEW "name",
        INPUT "name" (defaults to USE PROCESS)."""
        ex_line = self.peek().line
        direction = self.advance().upper()  # INPUT or OUTPUT

        # Check for MAKE/USE/NEW keywords
        is_new = False
        legacy_new = False
        use_type = ""  # PROCESS or FLOW

        if self.match_keyword("MAKE"):
            is_new = True
            self.match_keyword("FLOW")  # optional but expected
        elif self.match_keyword("USE"):
            if self.at_keyword("PROCESS"):
                use_type = self.advance().upper()
            elif self.at_keyword("FLOW"):
                use_type = self.advance().upper()
            else:
                use_type = "PROCESS"  # USE alone defaults to USE PROCESS
        elif self.match_keyword("NEW"):
            is_new = True  # deprecated alias for MAKE FLOW
            legacy_new = True

        flow_name = self.parse_string_or_expr()
        if self.peek().type == TokenType.COMMA:
            self.advance()

        # Amount or expression
        amount = self.parse_expr()
        if self.peek().type == TokenType.COMMA:
            self.advance()

        # Unit
        unit = self.parse_unit()

        is_product = False
        is_waste = False
        compartment = ""
        provider = None
        formula = None
        location = None
        flow_folder = None
        pedigree = None
        comment = None
        extras = {}

        # Parse trailing modifiers
        # Allow optional comma before modifiers (e.g. "m3, PRODUCT")
        if self.peek().type == TokenType.COMMA:
            self.advance()
        while (self.peek().type == TokenType.KEYWORD
               or self.at_exchange_extra()):
            kw = self.peek().upper()
            if self.at_exchange_extra():
                self.parse_exchange_extra(extras)
            elif kw == "PROPERTY":
                self.advance()
                extras["property"] = self.parse_string_or_expr()
            elif kw == "PRODUCT":
                is_product = True
                self.advance()
            elif kw == "WASTE":
                is_waste = True
                self.advance()
            elif kw == "TO":
                self.advance()
                if not self.at_keyword("AIR", "WATER", "SOIL"):
                    raise ParseError(
                        f"Expected AIR, WATER or SOIL after TO, got "
                        f"'{self.peek().value}'", self.current_line())
                compartment = self.advance().upper()
            elif kw == "FROM":
                self.advance()
                if not self.at_keyword("NATURE"):
                    raise ParseError(
                        f"Expected NATURE after FROM, got "
                        f"'{self.peek().value}'", self.current_line())
                compartment = self.advance().upper()
            elif kw == "PROVIDER":
                self.advance()
                provider = self.parse_string_or_expr()
            elif kw == "FORMULA":
                self.advance()
                formula = self.parse_string_or_expr()
            elif kw == "LOCATION":
                self.advance()
                location = self.parse_string_or_expr()
            elif kw == "FOLDER":
                self.advance()
                flow_folder = self.parse_string_or_expr()
            elif kw == "PEDIGREE":
                self.advance()
                pedigree = self.parse_pedigree()
            elif kw == "COMMENT":
                self.advance()
                comment = self.parse_string_or_expr()
            else:
                break
            if self.peek().type == TokenType.COMMA:
                self.advance()

        self.expect_newline()

        return ExchangeDef(
            direction=direction, flow_name=flow_name, amount=amount,
            unit=unit, is_new=is_new, is_product=is_product,
            is_waste=is_waste, use_type=use_type, legacy_new=legacy_new,
            pedigree=pedigree, comment=comment,
            direction_compartment=compartment, provider=provider,
            formula=formula, location=location, flow_folder=flow_folder,
            line=ex_line, extras=extras)

    def parse_system(self, line: int) -> SystemStmt:
        self.advance()  # consume SYSTEM
        process_ref = self.parse_string_or_expr()

        linking = "PREFER_DEFAULTS"
        linking_given = False
        target_amount = None
        target_unit = ""
        target_property = None
        folder = None
        sets, groups = [], []
        prefer = ""
        cutoff = None

        self.expect_newline()
        self.skip_newlines()

        # Block form only if the next line is a SYSTEM sub-command
        # or END SYSTEM. A bare END belongs to an enclosing block.
        if (self.at_keyword("LINKING", "TARGET", "FOLDER")
                or self.at_word("PREFER", "CUTOFF")
                or self.at_system_block()
                or self.at_end_of("SYSTEM")):
            while not self.at_keyword("END"):
                if self.peek().type == TokenType.EOF:
                    break
                if self.at_system_block():
                    self.parse_system_block(sets, groups)
                    self.skip_newlines()
                    continue
                if self.match_keyword("LINKING"):
                    if not self.at_word(*self.LINKINGS):
                        raise ParseError(
                            "LINKING must be PREFER_DEFAULTS, "
                            "ONLY_DEFAULTS (also written "
                            "ONLY_LINK_PROVIDERS) or IGNORE_DEFAULTS",
                            self.current_line())
                    linking = self.advance().upper()
                    linking_given = True
                elif self.match_word("PREFER"):
                    if not self.at_word("UNIT", "SYSTEM"):
                        raise ParseError(
                            "Expected PREFER UNIT PROCESSES or PREFER "
                            "SYSTEM PROCESSES", self.current_line())
                    prefer = self.advance().upper()
                    self.match_keyword("PROCESSES")
                elif self.match_word("CUTOFF"):
                    cutoff = self.parse_add_expr()
                elif self.match_keyword("TARGET"):
                    target_amount = self.parse_expr()
                    if self.peek().type == TokenType.COMMA:
                        self.advance()
                    target_unit = self.parse_unit()
                    if self.match_keyword("PROPERTY"):
                        target_property = self.parse_string_or_expr()
                elif self.match_keyword("FOLDER"):
                    folder = self.parse_string_or_expr()
                else:
                    raise ParseError(
                        f"'{self.peek().value}' is not allowed inside "
                        f"SYSTEM (expected LINKING, PREFER, CUTOFF, TARGET, "
                        f"FOLDER, PARAMETER SET, ANALYSIS GROUP or "
                        f"END SYSTEM)", self.current_line())
                self.expect_newline()
                self.skip_newlines()

            self.expect_keyword("END")
            self.match_keyword("SYSTEM")
            self.expect_newline()

        return SystemStmt(
            line=line, process_ref=process_ref, linking=linking,
            target_amount=target_amount, target_unit=target_unit,
            target_property=target_property, folder=folder,
            parameter_sets=sets, analysis_groups=groups, prefer=prefer,
            cutoff=cutoff,
            defaulted=self._defaulted(LINKING=linking_given,
                                      TARGET=target_amount is not None))

    def parse_contribution(self, line: int) -> ContributionStmt:
        self.advance()  # consume CONTRIBUTION
        system = self.parse_string_or_expr()
        self.expect_keyword("USING")
        method = self.parse_string_or_expr()
        top = 10
        top_given = False
        allocation = ""
        categories = []

        if self.match_keyword("TOP"):
            top = self.parse_int("TOP")
            top_given = True
        if self.match_keyword("ALLOCATE"):
            allocation = self.parse_allocation()

        self.expect_newline()
        self.skip_newlines()

        # Check for block with CATEGORIES
        if self.at_keyword("CATEGORIES"):
            self.advance()
            while self.peek().type not in (TokenType.NEWLINE,
                                            TokenType.EOF,
                                            TokenType.COMMENT):
                categories.append(self.parse_string_or_expr())
                if self.peek().type == TokenType.COMMA:
                    self.advance()
            self.expect_newline()
            self.skip_newlines()
            if self.match_keyword("END"):
                self.match_keyword("CONTRIBUTION")
                self.expect_newline()

        return ContributionStmt(
            line=line, system=system, method=method, top=top,
            categories=categories, allocation=allocation,
            defaulted=self._defaulted(TOP=top_given, ALLOCATE=allocation))

    def parse_inventory(self, line: int) -> InventoryStmt:
        self.advance()  # consume INVENTORY
        system = self.parse_string_or_expr()
        self.expect_keyword("USING")
        method = self.parse_string_or_expr()
        max_flows = 50
        max_given = False
        allocation = ""
        if self.match_keyword("MAX"):
            max_flows = self.parse_int("MAX")
            max_given = True
        if self.match_keyword("ALLOCATE"):
            allocation = self.parse_allocation()
        self.expect_newline()
        return InventoryStmt(line=line, system=system, method=method,
                              max_flows=max_flows, allocation=allocation,
                              defaulted=self._defaulted(MAX=max_given,
                                                        ALLOCATE=allocation))

    def parse_montecarlo(self, line: int) -> MonteCarloStmt:
        self.advance()  # consume MONTECARLO
        system = self.parse_string_or_expr()
        self.expect_keyword("USING")
        method = self.parse_string_or_expr()
        runs = 1000
        runs_given = False
        allocation = ""
        if self.match_keyword("RUNS"):
            runs = self.parse_int("RUNS")
            runs_given = True
        if self.match_keyword("ALLOCATE"):
            allocation = self.parse_allocation()
        self.expect_newline()
        return MonteCarloStmt(line=line, system=system, method=method,
                               runs=runs, allocation=allocation,
                               defaulted=self._defaulted(RUNS=runs_given,
                                                         ALLOCATE=allocation))

    def parse_scenario(self, line: int) -> ScenarioStmt:
        self.advance()  # consume SCENARIO
        name_expr = self.parse_string_or_expr()
        name = name_expr.value if isinstance(name_expr, StringLiteral) else str(name_expr)
        self.expect_newline()
        self.skip_newlines()

        overrides = []
        while not self.at_keyword("END"):
            if self.peek().type == TokenType.EOF:
                raise ParseError("SCENARIO block missing END SCENARIO", line)
            tok = self.peek()
            kw = tok.upper() if tok.type == TokenType.KEYWORD else ""

            if kw == "LET" or kw == "SET":
                stmt = self.parse_let(tok.line)
                overrides.append(stmt)
            elif tok.type in (TokenType.COMMENT, TokenType.NEWLINE):
                self.advance()
            else:
                raise ParseError(
                    f"'{tok.value}' is not allowed inside SCENARIO "
                    f"(expected LET or END SCENARIO)", tok.line)
            self.skip_newlines()

        self.expect_keyword("END")
        self.match_keyword("SCENARIO")
        self.expect_newline()

        return ScenarioStmt(line=line, name=name, overrides=overrides)

    def parse_sensitivity(self, line: int) -> SensitivityStmt:
        self.advance()  # consume SENSITIVITY
        self.expect_keyword("ON")
        system = self.parse_string_or_expr()
        self.expect_keyword("USING")
        method = self.parse_string_or_expr()

        allocation = ""
        if not self.match_keyword("BY"):
            raise ParseError(
                "SENSITIVITY needs BY: how far to vary each parameter.",
                line, hint='For example: SENSITIVITY ON "system" USING '
                           '"method" BY 10%')
        variation = self.parse_number("BY")
        self.match_keyword("PERCENT")  # optional
        if self.peek().type == TokenType.PERCENT:
            self.advance()

        if self.match_keyword("ALLOCATE"):
            allocation = self.parse_allocation()

        self.expect_newline()
        self.skip_newlines()

        parameters = []
        parameter_lines = []
        from_csv = None
        save_to = None

        while not self.at_keyword("END"):
            if self.peek().type == TokenType.EOF:
                raise ParseError(
                    "SENSITIVITY block missing END SENSITIVITY", line)
            kw = self.peek().upper() if self.peek().type == TokenType.KEYWORD else ""

            if kw == "VARY":
                self.advance()
                while True:
                    if self.peek().type in (TokenType.IDENTIFIER,
                                            TokenType.STRING):
                        parameter_lines.append(self.peek().line)
                        parameters.append(self.advance().value)
                    else:
                        raise ParseError(
                            f"Expected a parameter name after VARY, "
                            f"got '{self.peek().value}'",
                            self.current_line())
                    if self.peek().type == TokenType.COMMA:
                        self.advance()
                        continue
                    break
            elif kw == "FROM":
                self.advance()
                from_csv = self.parse_string_or_expr()
            elif kw == "SAVE":
                self.advance()
                save_to = self.parse_string_or_expr()
            elif self.peek().type in (TokenType.COMMENT, TokenType.NEWLINE):
                self.advance()
                continue
            else:
                raise ParseError(
                    f"'{self.peek().value}' is not allowed inside "
                    f"SENSITIVITY (expected VARY, FROM, SAVE or "
                    f"END SENSITIVITY)", self.current_line())
            self.expect_newline()
            self.skip_newlines()

        self.expect_keyword("END")
        self.match_keyword("SENSITIVITY")
        self.expect_newline()

        if not parameters and from_csv is None:
            raise ParseError(
                "SENSITIVITY has nothing to vary.", line,
                hint='Add a VARY line inside the block, for example: '
                     'VARY cement_mass (or FROM "parameters.csv")')

        return SensitivityStmt(
            line=line, system=system, method=method,
            variation_pct=variation, parameters=parameters,
            from_csv=from_csv, save_to=save_to, allocation=allocation,
            parameter_lines=parameter_lines,
            defaulted=self._defaulted(ALLOCATE=allocation))

    def parse_run(self, line: int) -> Statement:
        self.advance()  # consume RUN

        # RUN SCENARIOS ON ...
        if self.at_keyword("SCENARIOS"):
            self.advance()
            self.expect_keyword("ON")
            system = self.parse_string_or_expr()
            self.expect_keyword("USING")
            method = self.parse_string_or_expr()
            allocation = ""
            from_csv = None
            save_to = None
            from_system = False

            while True:
                if self.match_keyword("ALLOCATE"):
                    allocation = self.parse_allocation()
                elif (self.at_keyword("FROM")
                      and self.peek_at(1).upper() == "SYSTEM"):
                    self.advance()
                    self.advance()
                    from_system = True
                else:
                    break

            self.expect_newline()
            if from_system:
                return RunScenariosStmt(
                    line=line, system=system, method=method,
                    allocation=allocation, from_system=True,
                    defaulted=self._defaulted(ALLOCATE=allocation))
            self.skip_newlines()

            # Block form only for FROM / SAVE "file" / END RUN.
            # SAVE RESULTS on the next line is a separate statement,
            # and a bare END belongs to an enclosing block.
            if (self.at_keyword("FROM")
                    or (self.at_keyword("SAVE")
                        and self.peek_at(1).type == TokenType.STRING)
                    or self.at_end_of("RUN")):
                while not self.at_keyword("END"):
                    if self.peek().type == TokenType.EOF:
                        break
                    if self.match_keyword("FROM"):
                        self.match_keyword("CSV")
                        from_csv = self.parse_string_or_expr()
                    elif self.match_keyword("SAVE"):
                        save_to = self.parse_string_or_expr()
                    else:
                        raise ParseError(
                            f"'{self.peek().value}' is not allowed inside "
                            f"RUN SCENARIOS (expected FROM, SAVE or "
                            f"END RUN)", self.current_line())
                    self.expect_newline()
                    self.skip_newlines()

                self.expect_keyword("END")
                self.expect_keyword("RUN")
                self.expect_newline()

            return RunScenariosStmt(
                line=line, system=system, method=method,
                from_csv=from_csv, save_to=save_to,
                allocation=allocation,
                defaulted=self._defaulted(ALLOCATE=allocation))

        # RUN on its own: the program in memory (LOAD puts one there)
        if self.peek().type in (TokenType.NEWLINE, TokenType.EOF,
                                TokenType.COMMENT):
            self.expect_newline()
            return RunMemoryStmt(line=line)

        # RUN "filename.baslca"
        filename = self.parse_string_or_expr()
        self.expect_newline()
        return RunFileStmt(line=line, filename=filename)

    def parse_validate(self, line: int) -> ValidateStmt:
        self.advance()  # consume VALIDATE
        system = self.parse_string_or_expr()
        with_calc = False
        if self.match_keyword("WITH"):
            if not self.match_word("CALCULATION", "CALCULATE"):
                raise ParseError("Expected CALCULATION after WITH", line)
            with_calc = True
        self.expect_newline()
        return ValidateStmt(line=line, system=system, with_calc=with_calc)

    def parse_check(self, line: int) -> CheckStmt:
        self.advance()  # consume CHECK
        system = self.parse_string_or_expr()
        tier = 1
        tier_given = False
        against = None
        if self.match_keyword("TIER"):
            tier = self.parse_int("TIER")
            tier_given = True
        if self.match_keyword("AGAINST"):
            against = self.parse_string_or_expr()
        self.expect_newline()
        return CheckStmt(line=line, system=system, tier=tier,
                          against=against,
                          defaulted=self._defaulted(TIER=tier_given))

    def parse_extract(self, line: int) -> ExtractStmt:
        self.advance()  # consume EXTRACT
        self.match_keyword("FOLDER")
        folder = self.parse_string_or_expr()
        self.expect_newline()
        return ExtractStmt(line=line, folder=folder)

    def parse_audit(self, line: int) -> AuditStmt:
        self.advance()  # consume AUDIT
        self.match_keyword("FOLDER")
        folder = self.parse_string_or_expr()
        self.expect_newline()
        return AuditStmt(line=line, folder=folder)

    def parse_save(self, line: int) -> Statement:
        self.advance()  # consume SAVE
        if self.at_word("RESULT") and self.peek_at(1).upper() == "AS":
            self.advance()
            self.advance()
            return self.parse_save_result_as(line)
        if self.match_keyword("RESULTS"):
            filename = self.parse_string_or_expr()
            self.expect_newline()
            return SaveResultsStmt(line=line, filename=filename)
        # SAVE PROGRAM "file" or SAVE "file.baslca": the program so far
        if self.match_word("PROGRAM"):
            filename = self.parse_string_or_expr()
            self.expect_newline()
            return SaveProgramStmt(line=line, filename=filename)
        filename = self.parse_string_or_expr()
        self.expect_newline()
        if (isinstance(filename, StringLiteral)
                and filename.value.lower().endswith((".baslca", ".bas"))):
            return SaveProgramStmt(line=line, filename=filename)
        # SAVE "file.csv": the latest results, as before
        return SaveResultsStmt(line=line, filename=filename)

    def parse_export(self, line: int) -> ExportResultsStmt:
        self.advance()  # consume EXPORT
        if self.peek_entity_type()[0] is not None:
            return self.parse_entity_export(line)
        self.match_keyword("RESULTS")
        self.match_keyword("TO")
        filename = self.parse_string_or_expr()
        self.expect_newline()
        return ExportResultsStmt(line=line, filename=filename)

    def parse_delete(self, line: int) -> DeleteStmt:
        self.advance()  # consume DELETE
        entity_type = ""
        etype, _n = self.peek_entity_type()
        if etype is not None and etype not in ("PROCESS", "SYSTEM", "FLOW"):
            return self.parse_entity_delete(line)
        if self.at_keyword("PROCESS", "SYSTEM", "FLOW"):
            entity_type = self.advance().upper()
        else:
            raise ParseError("Say what to delete.", line,
                             hint='DELETE PROCESS "name", DELETE SYSTEM '
                                  '"name", DELETE FLOW "name", or another '
                                  'type: DELETE ACTOR "name" (HELP DELETE '
                                  'lists the types)')
        ref = self.parse_string_or_expr()
        self.expect_newline()
        return DeleteStmt(line=line, entity_type=entity_type, ref=ref)

    def parse_confirm(self, line: int) -> ConfirmDeleteStmt:
        self.advance()  # CONFIRM
        self.match_keyword("DELETE")
        enabled = True
        if self.at_keyword("ON"):
            self.advance()
            enabled = True
        elif self.match_word("OFF"):
            enabled = False
        self.expect_newline()
        return ConfirmDeleteStmt(line=line, enabled=enabled)

    def parse_include(self, line: int) -> IncludeStmt:
        self.advance()  # INCLUDE
        filename = self.parse_string_or_expr()
        self.expect_newline()
        return IncludeStmt(line=line, filename=filename)

    def parse_find(self, line: int) -> FindStmt:
        self.advance()  # FIND
        entity_type = ""
        etype, _n = self.peek_entity_type()
        if etype is not None and etype not in ("PROCESS", "FLOW", "METHOD",
                                               "SYSTEM"):
            return self.parse_entity_find(line)
        if self.at_word("PROCESS", "FLOW", "METHOD", "CHEMICAL",
                         "UNIT", "SYSTEM"):
            entity_type = self.advance().upper()
        else:
            raise ParseError(
                "FIND needs a type: PROCESS, FLOW, SYSTEM, METHOD, "
                "CHEMICAL or UNIT", line,
                hint='For example: FIND PROCESS "cement". Every other '
                     'type of entity can be found too: FIND ACTOR, FIND '
                     'SOURCE, FIND LOCATION and so on (HELP FIND).')
        search_term = self.parse_string_or_expr()
        location = None
        category = None
        if self.match_word("AT"):
            location = self.parse_string_or_expr()
        if self.match_keyword("IN"):
            category = self.parse_string_or_expr()
        self.expect_newline()
        return FindStmt(line=line, entity_type=entity_type,
                         search_term=search_term, location=location,
                         category=category)

    def parse_set(self, line: int) -> Statement:
        self.advance()  # SET
        # SET FLOW FOLDER "path"
        if self.at_keyword("FLOW"):
            self.advance()
            if self.match_keyword("FOLDER"):
                folder = self.parse_string_or_expr()
                self.expect_newline()
                return SetFolderStmt(line=line, folder=folder,
                                     target="FLOW")
        # SET PROCESS FOLDER "path"
        elif self.at_keyword("PROCESS"):
            self.advance()
            if self.match_keyword("FOLDER"):
                folder = self.parse_string_or_expr()
                self.expect_newline()
                return SetFolderStmt(line=line, folder=folder,
                                     target="PROCESS")
        # SET FOLDER "path" (default: process folder)
        elif self.match_keyword("FOLDER"):
            folder = self.parse_string_or_expr()
            self.expect_newline()
            return SetFolderStmt(line=line, folder=folder,
                                 target="PROCESS")
        # Fallback: treat SET as LET (for scenario overrides at top level)
        tok = self.peek()
        if tok.type == TokenType.IDENTIFIER:
            name = self.advance().value
            if self.peek().type == TokenType.EQUALS:
                self.advance()
            expr = self.parse_expr()
            self.expect_newline()
            return LetStmt(line=line, name=name, expr=expr)
        raise ParseError(
            "Expected SET PROCESS FOLDER, SET FLOW FOLDER, SET FOLDER "
            "or SET name = value", line)

    def parse_cat(self, line: int) -> CatStmt:
        """CAT/LS [FLOWS|PROCESSES|SYSTEMS] ["path"] [*pattern*]"""
        self.advance()  # CAT or LS
        entity_type = ""
        path = None
        filter_pattern = ""

        if self.at_keyword("FLOWS"):
            entity_type = self.advance().upper()
        elif self.at_keyword("PROCESSES"):
            entity_type = self.advance().upper()
        elif self.at_keyword("SYSTEMS"):
            entity_type = self.advance().upper()

        # Check for wildcard pattern: *term* or *term
        # Tokenises as STAR IDENTIFIER [STAR]
        if self.peek().type == TokenType.STAR:
            self.advance()  # consume first *
            if self.peek().type in (TokenType.IDENTIFIER,
                                     TokenType.KEYWORD):
                term = self.advance().value
                filter_pattern = "*" + term
                if self.peek().type == TokenType.STAR:
                    self.advance()  # consume trailing *
                    filter_pattern += "*"
        elif self.peek().type == TokenType.STRING:
            val = self.peek().value
            if "*" in val:
                # Quoted wildcard: "*concrete*"
                filter_pattern = self.advance().value
            else:
                path = self.parse_string_or_expr()

        self.expect_newline()
        return CatStmt(line=line, path=path,
                        entity_type=entity_type,
                        filter_pattern=filter_pattern)

    def parse_dir_nav(self, line: int) -> Statement:
        """DIR "path" or DIR (show current) or CD "path" or CD .."""
        self.advance()  # DIR or CD
        # No args = show current directory
        if self.peek().type in (TokenType.NEWLINE, TokenType.EOF,
                                 TokenType.COMMENT):
            self.expect_newline()
            return DirStmt(line=line, path=None)
        # .. goes up
        tok = self.peek()
        if tok.type == TokenType.IDENTIFIER and tok.value == "..":
            self.advance()
            self.expect_newline()
            return UpStmt(line=line)
        # CD - goes back to the previous folder, as in bash
        if (tok.type == TokenType.MINUS and self.peek_at(1).type in (
                TokenType.NEWLINE, TokenType.EOF, TokenType.COMMENT)):
            self.advance()
            self.expect_newline()
            return BackStmt(line=line)
        # CD / goes to the top level
        if (tok.type == TokenType.SLASH and self.peek_at(1).type in (
                TokenType.NEWLINE, TokenType.EOF, TokenType.COMMENT)):
            self.advance()
            self.expect_newline()
            return DirStmt(line=line, path=StringLiteral("/"))
        path = self.parse_string_or_expr()
        self.expect_newline()
        return DirStmt(line=line, path=path)

    def parse_make(self, line: int) -> Statement:
        """MAKE PROCESS/FLOW/BRIDGE — dispatches to existing parsers
        with is_new flag set."""
        self.advance()  # MAKE
        two_words = self.peek_entity_type()[1] == 2
        if self.at_keyword("PROCESS"):
            return self.parse_process(line)
        elif self.at_keyword("FLOW") and not two_words:
            stmt = self.parse_flow(line)
            stmt.is_new = True
            return stmt
        elif self.at_keyword("BRIDGE"):
            return self.parse_bridge(line)
        elif self.at_keyword("SYSTEM") and not two_words:
            return self.parse_system(line)
        etype, n = self.peek_entity_type()
        if etype is not None:
            for _ in range(n):
                self.advance()
            if etype in SIMPLE_TYPES:
                return self.parse_make_entity(line, etype)
            if etype == "METHOD":
                return self.parse_method(line)
            if etype == "PROJECT":
                return self.parse_project(line)
            if etype == "FLOW MAP":
                self._name_after("MAKE FLOW MAP", 'MAKE FLOW MAP "name"')
                raise ParseError(
                    "olcaBASIC cannot make a flow map: openLCA's IPC "
                    "server has no way to store one.", line,
                    hint="Flow maps are made in openLCA's import "
                         "dialogues.")
            hints = {
                "PARAMETER": "A global parameter is made with LET name = "
                             "value.",
                "CATEGORY": "An impact category is made inside MAKE "
                            "METHOD ... END METHOD.",
                "RESULT": "A stored result is made with SAVE RESULT AS "
                          "\"name\" after CALCULATE.",
                "EPD": "An EPD is made with the EPD block and EPD SAVE.",
            }
            raise ParseError(f"MAKE {etype} is not a command.", line,
                             hint=hints.get(etype, ""))
        raise ParseError(
            f"MAKE cannot make '{self.peek().value}'.", line,
            hint="MAKE takes PROCESS, FLOW, BRIDGE, SYSTEM, ACTOR, SOURCE, "
                 "CURRENCY, LOCATION, UNITS, PROPERTY, SOCIAL INDICATOR, "
                 "DQ SYSTEM, METHOD or PROJECT.")

    def parse_show(self, line: int) -> ShowStmt:
        """SHOW PROCESS|FLOW|SYSTEM|PARAMETER "name" [sub-command]
        SHOW GLOBAL PARAMS ["text"]"""
        self.advance()  # SHOW
        entity_type = ""
        if self.at_word("GLOBAL") and self.peek_at(1).upper() == "PARAMS":
            self.advance()
            self.advance()
            flt = None
            if self.peek().type not in (TokenType.NEWLINE, TokenType.EOF,
                                        TokenType.COMMENT):
                flt = self.parse_string_or_expr()
            self.expect_newline()
            return ShowStmt(line=line, entity_type="GLOBAL_PARAMS",
                            ref=flt, filter=flt)
        etype, _n = self.peek_entity_type()
        if etype is not None and etype not in ("PROCESS", "FLOW", "SYSTEM",
                                               "PARAMETER"):
            return self.parse_entity_show(line)
        if self.at_keyword("PROCESS"):
            entity_type = self.advance().upper()
        elif self.at_keyword("FLOW"):
            entity_type = self.advance().upper()
        elif self.at_keyword("SYSTEM"):
            entity_type = self.advance().upper()
        elif self.at_word("PARAMETER", "PARAMS", "GLOBAL"):
            entity_type = "PARAMETER"
            self.advance()
        else:
            raise ParseError(
                "Expected PROCESS, FLOW, SYSTEM or PARAMETER after SHOW.",
                line, hint='For example: SHOW PROCESS "name". Every other '
                           'type of entity can be shown too: SHOW ACTOR '
                           '"name", SHOW METHOD "name" (HELP SHOW).')

        ref = self.parse_string_or_expr()
        sub_command = ""
        flt = None
        limit = 0
        allowed = {
            "PROCESS": ("INPUTS", "OUTPUTS", "LOCATION", "DESCRIPTION",
                        "PARAMS", "QUALITY", "DOCUMENT", "ALLOCATION",
                        "SOCIAL", "FIELDS", "JSON", "USAGE"),
            "FLOW": ("UNITS", "DESCRIPTION", "USAGE", "FIELDS", "JSON"),
            "SYSTEM": ("PARAMS", "LINKS", "SETS", "GROUPS", "JSON",
                       "USAGE"),
            "PARAMETER": ("VALUE", "DESCRIPTION", "JSON", "USAGE"),
        }[entity_type]
        if self.peek().type in (TokenType.KEYWORD, TokenType.IDENTIFIER):
            if not self.at_word(*allowed):
                raise ParseError(
                    f"SHOW {entity_type} doesn't take "
                    f"'{self.peek().value}'.", line,
                    hint="Use one of: " + ", ".join(allowed) + ".")
            sub_command = self.advance().upper()
        if sub_command in ("LINKS", "PARAMS") and entity_type == "SYSTEM":
            if self.peek().type == TokenType.STRING:
                flt = self.parse_string_or_expr()
        if sub_command == "USAGE" and self.match_keyword("LIMIT"):
            limit = self.parse_int("LIMIT")

        self.expect_newline()
        return ShowStmt(line=line, entity_type=entity_type,
                         ref=ref, sub_command=sub_command,
                         filter=flt, limit=limit)

    def parse_link(self, line: int) -> LinkStmt:
        """LINK PROCESS "source" TO PROCESS "target" WITH amount, unit"""
        self.advance()  # LINK
        source_type = ""
        if self.at_keyword("PROCESS"):
            source_type = self.advance().upper()
        elif self.at_keyword("FLOW"):
            source_type = self.advance().upper()
        source = self.parse_string_or_expr()

        self.expect_keyword("TO")
        target_type = ""
        if self.at_keyword("PROCESS"):
            target_type = self.advance().upper()
        elif self.at_keyword("FLOW"):
            target_type = self.advance().upper()
        target = self.parse_string_or_expr()

        amount = None
        unit = ""
        if self.match_keyword("WITH"):
            amount = self.parse_expr()
            if self.peek().type == TokenType.COMMA:
                self.advance()
            unit = self.parse_unit()

        self.expect_newline()
        return LinkStmt(line=line, source_type=source_type,
                         source=source, target_type=target_type,
                         target=target, amount=amount, unit=unit)

    def parse_navigate(self, line: int) -> NavigateStmt:
        """NAVIGATE [PROCESSES|FLOWS|METHODS|SYSTEMS]"""
        self.advance()  # NAVIGATE
        target = ""
        if self.at_keyword("PROCESSES"):
            target = self.advance().upper()
        elif self.at_keyword("FLOWS"):
            target = self.advance().upper()
        elif self.at_keyword("METHODS"):
            target = self.advance().upper()
        elif self.at_keyword("SYSTEMS"):
            target = self.advance().upper()
        elif self.at_keyword("PROCESS"):
            self.advance()
            target = "PROCESSES"
        elif self.at_keyword("FLOW"):
            self.advance()
            target = "FLOWS"
        self.expect_newline()
        return NavigateStmt(line=line, target=target)

    def parse_tree(self, line: int) -> TreeStmt:
        """TREE "system" USING "method" [CATEGORY "cat"] [LEVELS n] [TOP n]"""
        self.advance()  # TREE
        system = self.parse_string_or_expr()
        self.expect_keyword("USING")
        method = self.parse_string_or_expr()

        category = None
        levels = 3
        top = 5
        allocation = ""
        with_quality = True

        given = set()
        while self.at_word("CATEGORY", "LEVELS", "TOP", "ALLOCATE",
                           "NOQUALITY"):
            kw = self.advance().upper()
            given.add(kw)
            if kw == "CATEGORY":
                category = self.parse_string_or_expr()
            elif kw == "LEVELS":
                levels = self.parse_int("LEVELS")
            elif kw == "TOP":
                top = self.parse_int("TOP")
            elif kw == "ALLOCATE":
                allocation = self.parse_allocation()
            else:
                with_quality = False

        self.expect_newline()
        return TreeStmt(line=line, system=system, method=method,
                         category=category, levels=levels, top=top,
                         allocation=allocation, with_quality=with_quality,
                         defaulted=self._defaulted(
                             LEVELS="LEVELS" in given, TOP="TOP" in given,
                             ALLOCATE=allocation))

    def parse_move(self, line: int) -> MoveStmt:
        """MOVE PROCESS/FLOW/SYSTEM "ref" TO "folder" """
        self.advance()  # MOVE
        entity_type = ""
        etype, _n = self.peek_entity_type()
        if etype is not None and etype not in ("PROCESS", "FLOW", "SYSTEM"):
            return self.parse_entity_move(line)
        if self.at_keyword("PROCESS"):
            entity_type = self.advance().upper()
        elif self.at_keyword("FLOW"):
            entity_type = self.advance().upper()
        elif self.at_keyword("SYSTEM"):
            entity_type = self.advance().upper()

        ref = self.parse_string_or_expr()
        self.expect_keyword("TO")

        destination = None
        if self.match_keyword("FOLDER"):
            # MOVE ... TO FOLDER (use current SET folder)
            destination = None
        else:
            destination = self.parse_string_or_expr()

        self.expect_newline()
        return MoveStmt(line=line, entity_type=entity_type,
                         ref=ref, destination=destination)

    def parse_database_cmd(self, line: int) -> Statement:
        self.advance()  # DATABASE
        if self.match_keyword("INFO"):
            self.expect_newline()
            return PrintStmt(line=line, sub_command="DATABASE")
        if self.match_keyword("FAMILY"):
            family = self.parse_string_or_expr()
            self.expect_newline()
            return PrintStmt(line=line, sub_command="FAMILY",
                             args=[family])
        self.expect_newline()
        return PrintStmt(line=line, sub_command="DATABASE")

    def parse_if(self, line: int) -> IfStmt:
        self.advance()  # IF
        condition = self.parse_expr()
        self.expect_keyword("THEN")

        # Single-line form: IF cond THEN stmt [ELSE stmt]
        if self.peek().type not in (TokenType.NEWLINE, TokenType.EOF,
                                    TokenType.COMMENT):
            return self._parse_single_line_if(line, condition)

        self.expect_newline()
        self.skip_newlines()

        then_body = []
        else_body = []

        while not self.at_keyword("END", "ELSE"):
            if self.peek().type == TokenType.EOF:
                raise ParseError("IF block missing END IF", line)
            stmt = self.parse_statement()
            if stmt:
                then_body.append(stmt)
            self.skip_newlines()

        if self.match_keyword("ELSE"):
            self.expect_newline()
            self.skip_newlines()
            while not self.at_keyword("END"):
                if self.peek().type == TokenType.EOF:
                    raise ParseError("IF block missing END IF", line)
                stmt = self.parse_statement()
                if stmt:
                    else_body.append(stmt)
                self.skip_newlines()

        self.expect_keyword("END")
        self.match_keyword("IF")
        self.expect_newline()

        return IfStmt(line=line, condition=condition,
                       then_body=then_body, else_body=else_body)

    def _parse_single_line_if(self, line: int, condition: Expr) -> IfStmt:
        """IF cond THEN stmt [ELSE stmt] on one line. Parses the
        branch statements from sub-lists of the remaining tokens."""
        # Collect the rest of the line
        rest = []
        while self.peek().type not in (TokenType.NEWLINE, TokenType.EOF,
                                       TokenType.COMMENT):
            rest.append(self.advance())
        self.expect_newline()
        # Split on a top-level ELSE
        split = None
        for i, t in enumerate(rest):
            if t.type == TokenType.KEYWORD and t.upper() == "ELSE":
                split = i
                break
        then_toks = rest if split is None else rest[:split]
        else_toks = [] if split is None else rest[split + 1:]

        def one(toks):
            if not toks:
                return []
            sub = Parser(toks + [Token(TokenType.NEWLINE, "\\n", line),
                                 Token(TokenType.EOF, "", line)])
            stmt = sub.parse_statement()
            if sub.peek().type != TokenType.EOF:
                raise ParseError("Only one statement is allowed in each "
                                 "branch of a single-line IF", line)
            return [stmt] if stmt else []

        return IfStmt(line=line, condition=condition,
                      then_body=one(then_toks), else_body=one(else_toks))

    def parse_for(self, line: int) -> Statement:
        self.advance()  # FOR

        # FOR EACH
        if self.match_keyword("EACH"):
            var_tok = self.peek()
            variable = self.advance().value
            self.expect_keyword("IN")
            values = []
            while self.peek().type not in (TokenType.NEWLINE,
                                            TokenType.EOF,
                                            TokenType.COMMENT):
                values.append(self.parse_expr())
                if self.peek().type == TokenType.COMMA:
                    self.advance()
            self.expect_newline()
            self.skip_newlines()

            body = []
            while not self.at_keyword("NEXT"):
                if self.peek().type == TokenType.EOF:
                    raise ParseError("FOR EACH missing NEXT", line)
                stmt = self.parse_statement()
                if stmt:
                    body.append(stmt)
                self.skip_newlines()

            self.expect_keyword("NEXT")
            if (self.peek().type == TokenType.IDENTIFIER
                    and self.peek().value == variable):
                self.advance()  # optional variable after NEXT
            self.expect_newline()

            return ForEachStmt(line=line, variable=variable,
                                values=values, body=body)

        # FOR var = start TO end [STEP n]
        var_tok = self.advance()
        if var_tok.type != TokenType.IDENTIFIER:
            raise ParseError("Expected a variable name after FOR", line)
        variable = var_tok.value
        if self.peek().type != TokenType.EQUALS:
            raise ParseError(f"Expected '=' after FOR {variable}", line)
        self.advance()
        start = self.parse_expr()
        self.expect_keyword("TO")
        end = self.parse_expr()
        step = None
        if self.match_keyword("STEP"):
            step = self.parse_expr()
        self.expect_newline()
        self.skip_newlines()

        body = []
        while not self.at_keyword("NEXT"):
            if self.peek().type == TokenType.EOF:
                raise ParseError("FOR missing NEXT", line)
            stmt = self.parse_statement()
            if stmt:
                body.append(stmt)
            self.skip_newlines()

        self.expect_keyword("NEXT")
        if (self.peek().type == TokenType.IDENTIFIER
                and self.peek().value == variable):
            self.advance()  # optional variable name
        self.expect_newline()

        return ForStmt(line=line, variable=variable, start=start,
                        end=end, step=step, body=body)

    def parse_while(self, line: int) -> WhileStmt:
        self.advance()  # WHILE
        condition = self.parse_expr()
        self.expect_newline()
        self.skip_newlines()

        body = []
        while not self.at_keyword("WEND"):
            if self.peek().type == TokenType.EOF:
                raise ParseError("WHILE missing WEND", line)
            stmt = self.parse_statement()
            if stmt:
                body.append(stmt)
            self.skip_newlines()

        self.expect_keyword("WEND")
        self.expect_newline()

        return WhileStmt(line=line, condition=condition, body=body)

    def parse_sub_def(self, line: int) -> SubDef:
        self.advance()  # SUB
        name = self.advance().value
        params = []
        if self.peek().type == TokenType.LPAREN:
            self.advance()
            while self.peek().type != TokenType.RPAREN:
                if self.peek().type in (TokenType.IDENTIFIER,
                                         TokenType.KEYWORD):
                    params.append(self.advance().value)
                if self.peek().type == TokenType.COMMA:
                    self.advance()
            self.advance()  # consume )
        self.expect_newline()
        self.skip_newlines()

        body = []
        while not self.at_keyword("END"):
            if self.peek().type == TokenType.EOF:
                raise ParseError("SUB missing END SUB", line)
            stmt = self.parse_statement()
            if stmt:
                body.append(stmt)
            self.skip_newlines()

        self.expect_keyword("END")
        self.match_keyword("SUB")
        self.expect_newline()

        return SubDef(line=line, name=name, params=params, body=body)

    def parse_function_def(self, line: int) -> FunctionDef:
        self.advance()  # FUNCTION
        name = self.advance().value
        params = []
        if self.peek().type == TokenType.LPAREN:
            self.advance()
            while self.peek().type != TokenType.RPAREN:
                if self.peek().type in (TokenType.IDENTIFIER,
                                         TokenType.KEYWORD):
                    params.append(self.advance().value)
                if self.peek().type == TokenType.COMMA:
                    self.advance()
            self.advance()
        # Optional AS type
        if self.match_keyword("AS"):
            self.advance()  # skip type name
        self.expect_newline()
        self.skip_newlines()

        body = []
        while not self.at_keyword("END"):
            if self.peek().type == TokenType.EOF:
                raise ParseError("FUNCTION missing END FUNCTION", line)
            stmt = self.parse_statement()
            if stmt:
                body.append(stmt)
            self.skip_newlines()

        self.expect_keyword("END")
        self.match_keyword("FUNCTION")
        self.expect_newline()

        return FunctionDef(line=line, name=name, params=params,
                            body=body)

    def parse_sub_call(self, line: int) -> SubCall:
        name = self.advance().value
        args = []
        while self.peek().type not in (TokenType.NEWLINE,
                                        TokenType.EOF,
                                        TokenType.COMMENT):
            args.append(self.parse_expr())
            if self.peek().type == TokenType.COMMA:
                self.advance()
        self.expect_newline()
        return SubCall(line=line, name=name, args=args)

    def parse_update_param(self, line: int) -> UpdateParamStmt:
        """UPDATE PARAMETER name = expr"""
        self.advance()  # UPDATE
        if not self.match_word("PARAMETER"):
            raise ParseError("Expected UPDATE PARAMETER name = value "
                             "(exchanges are updated inside EDIT PROCESS)",
                             line)
        tok = self.peek()
        if tok.type != TokenType.IDENTIFIER:
            raise ParseError("Expected a parameter name after UPDATE "
                             "PARAMETER", line)
        name = self.advance().value
        if self.peek().type != TokenType.EQUALS:
            raise ParseError(f"Expected '=' after {name}", line)
        self.advance()
        expr = self.parse_expr()
        self.expect_newline()
        return UpdateParamStmt(line=line, name=name, expr=expr)

    def parse_edit_flow(self, line: int) -> EditFlowStmt:
        """EDIT FLOW "name" ... END EDIT

        ADD PROPERTY "Mass" AS 2400 kg PER m3
        UPDATE PROPERTY "Mass" AS 2350 kg PER m3
        SET REFERENCE "Mass"
        """
        self.advance()  # EDIT
        self.expect_keyword("FLOW")
        target = self.parse_string_or_expr()
        self.expect_newline()
        self.skip_newlines()
        stmt = EditFlowStmt(line=line, target=target)

        def relation(ln):
            if not self.match_keyword("AS"):
                raise ParseError("Expected AS, e.g. ADD PROPERTY \"Mass\" "
                                 "AS 2400 kg PER m3", ln)
            amount = self.parse_expr()
            unit = self.parse_unit()
            if not self.match_word("PER"):
                raise ParseError("Expected PER, e.g. AS 2400 kg PER m3", ln)
            # Optional amount after PER: AS 1 m3 PER 2400 kg
            if self.peek().type == TokenType.NUMBER:
                per_amount = NumberLiteral(float(self.advance().value))
                if per_amount.value <= 0:
                    raise ParseError("The amount after PER must be positive", ln)
                amount = BinOp(amount, "/", per_amount)
            per_unit = self.parse_unit()
            return amount, unit, per_unit

        while not self.at_keyword("END"):
            tok = self.peek()
            if tok.type == TokenType.EOF:
                raise ParseError("EDIT FLOW block missing END EDIT", line)
            if tok.type in (TokenType.COMMENT, TokenType.NEWLINE):
                self.advance()
                self.skip_newlines()
                continue
            ln = tok.line
            if self.at_keyword("ADD", "UPDATE"):
                op = self.advance().upper().lower()
                if not self.match_keyword("PROPERTY"):
                    raise ParseError(f"Expected PROPERTY after "
                                     f"{op.upper()}", ln)
                prop = self.parse_string_or_expr()
                amount, unit, per_unit = relation(ln)
                stmt.operations.append({"op": op, "property": prop,
                                        "amount": amount, "unit": unit,
                                        "per_unit": per_unit, "line": ln})
            elif self.at_keyword("REMOVE"):
                raise ParseError(
                    "Removing a flow property isn't available in olcaBASIC: "
                    "exchanges that use it would break, and openLCA's IPC "
                    "interface can't tell where a flow is used. Remove it "
                    "in openLCA's flow editor, which checks first.", ln)
            elif self.at_keyword("SET") and self.peek_at(1).upper() in (
                    "CAS", "FORMULA", "SYNONYMS", "DESCRIPTION", "LOCATION",
                    "INFRASTRUCTURE"):
                self.advance()
                what = self.advance().upper().lower()
                if what == "infrastructure":
                    value = self._yes_no("SET INFRASTRUCTURE")
                elif self.at_keyword("NONE"):
                    self.advance()
                    value = None
                else:
                    value = self.parse_string_or_expr()
                stmt.operations.append({"op": "set", "field": what,
                                        "value": value, "line": ln})
            elif self.at_keyword("SET"):
                self.advance()
                if not self.match_word("REFERENCE"):
                    raise ParseError(
                        "Expected SET REFERENCE \"property\", or SET CAS, "
                        "FORMULA, SYNONYMS, DESCRIPTION, LOCATION or "
                        "INFRASTRUCTURE", ln)
                prop = self.parse_string_or_expr()
                stmt.operations.append({"op": "reference", "property": prop,
                                        "line": ln})
            else:
                raise ParseError(
                    f"'{tok.value}' is not allowed inside EDIT FLOW "
                    f"(expected ADD PROPERTY, UPDATE PROPERTY, SET REFERENCE, "
                    f"SET CAS, SET FORMULA, SET SYNONYMS, SET DESCRIPTION, "
                    f"SET LOCATION, SET INFRASTRUCTURE or END EDIT)", ln)
            self.expect_newline()
            self.skip_newlines()

        self.expect_keyword("END")
        self.match_keyword("EDIT")
        self.expect_newline()
        return stmt

    def parse_edit(self, line: int) -> EditProcessStmt:
        """EDIT PROCESS "name" ... END EDIT

        ADD INPUT|OUTPUT <exchange>        same syntax as in PROCESS
        ADD PARAM name = value
        REMOVE INPUT|OUTPUT "name"         flow or provider name
        UPDATE INPUT|OUTPUT "name", amount [, unit] [LOCATION|PROVIDER x]
        UPDATE PARAM name = value
        SET DESCRIPTION|FOLDER|LOCATION "value"
        """
        self.advance()  # EDIT
        self.expect_keyword("PROCESS")
        target = self.parse_string_or_expr()
        self.expect_newline()
        self.skip_newlines()

        stmt = EditProcessStmt(line=line, target=target)

        def direction():
            if self.at_keyword("INPUT", "OUTPUT"):
                return self.advance().upper()
            if self.match_word("EXCHANGE"):
                return ""          # legacy: either direction
            raise ParseError("Expected INPUT or OUTPUT",
                             self.current_line())

        while not self.at_keyword("END"):
            tok = self.peek()
            if tok.type == TokenType.EOF:
                raise ParseError("EDIT block missing END EDIT", line)
            if tok.type in (TokenType.COMMENT, TokenType.NEWLINE):
                self.advance()
                self.skip_newlines()
                continue
            kw = tok.upper() if tok.type == TokenType.KEYWORD else ""
            ln = tok.line

            if kw == "ADD":
                self.advance()
                if self.at_keyword("INPUT", "OUTPUT"):
                    stmt.add_exchanges.append(self.parse_exchange())
                elif self.at_word("PARAM"):
                    stmt.add_params.append(self.parse_let(ln))
                else:
                    raise ParseError("Expected INPUT, OUTPUT or PARAM "
                                     "after ADD", ln)

            elif kw == "REMOVE" and self.peek_at(1).upper() == "ALLOCATION":
                self.advance()
                self.advance()
                which = ""
                if self.at_word("PHYSICAL", "ECONOMIC", "CAUSAL"):
                    which = self.advance().upper()
                stmt.remove_allocation.append((which, ln))
                self.expect_newline()

            elif kw == "REMOVE" and self.peek_at(1).upper() == "SOCIAL":
                self.advance()
                self.advance()
                stmt.remove_social.append((self.parse_string_or_expr(), ln))
                self.expect_newline()

            elif self.at_process_field():
                self.parse_process_field(stmt.fields)

            elif kw == "REMOVE":
                self.advance()
                d = direction()
                ref = self.parse_string_or_expr()
                spec = {"direction": d, "name": ref, "line": ln}
                # Which one, when the flow appears more than once
                while True:
                    if self.match_keyword("PROVIDER"):
                        spec["provider"] = self.parse_string_or_expr()
                    elif self.match_keyword("LOCATION"):
                        spec["location"] = self.parse_string_or_expr()
                    elif self.match_word("AMOUNT"):
                        spec["amount"] = self.parse_expr()
                    elif self.match_word("INDEX"):
                        spec["index"] = self.parse_int("INDEX")
                    else:
                        break
                stmt.remove_exchanges.append(spec)
                self.expect_newline()

            elif kw == "UPDATE":
                self.advance()
                if self.match_word("PARAM"):
                    name = self.advance().value
                    if self.match_word("UNCERTAINTY"):
                        # UPDATE PARAM name UNCERTAINTY ...: only that
                        stmt.param_uncertainty[name] = (
                            self.parse_uncertainty(), ln)
                        self.expect_newline()
                        self.skip_newlines()
                        continue
                    if self.peek().type != TokenType.EQUALS:
                        raise ParseError(f"Expected '=' after {name}", ln)
                    self.advance()
                    stmt.update_params[name] = self.parse_expr()
                    stmt.update_param_lines[name] = ln
                    if self.match_word("UNCERTAINTY"):
                        stmt.param_uncertainty[name] = (
                            self.parse_uncertainty(), ln)
                    self.expect_newline()
                else:
                    d = direction()
                    upd = {"direction": d, "name": self.parse_string_or_expr(),
                           "line": ln}
                    if self.match_word("INDEX"):
                        upd["index"] = self.parse_int("INDEX")
                    if self.peek().type == TokenType.COMMA:
                        self.advance()
                        upd["amount"] = self.parse_expr()
                        if self.peek().type == TokenType.COMMA:
                            self.advance()
                        if self.peek().type == TokenType.IDENTIFIER:
                            upd["unit"] = self.parse_unit()
                    while True:
                        if self.match_word("INDEX"):
                            upd["index"] = self.parse_int("INDEX")
                        elif self.match_word("AMOUNT"):       # legacy form
                            upd["amount"] = self.parse_expr()
                        elif self.match_keyword("FORMULA"):
                            upd["formula"] = self.parse_string_or_expr()
                        elif self.match_keyword("PROVIDER"):
                            upd["provider"] = self.parse_string_or_expr()
                        elif self.match_keyword("LOCATION"):
                            upd["location"] = self.parse_string_or_expr()
                        elif self.match_keyword("PEDIGREE"):
                            upd["pedigree"] = self.parse_pedigree()
                        elif self.match_keyword("COMMENT"):
                            upd["comment"] = self.parse_string_or_expr()
                        elif self.at_exchange_extra():
                            self.parse_exchange_extra(
                                upd.setdefault("extras", {}))
                        elif self.match_keyword("PROPERTY"):
                            upd.setdefault("extras", {})["property"] = \
                                self.parse_string_or_expr()
                        else:
                            break
                    if len(upd) - ("index" in upd) == 3:
                        raise ParseError(
                            "UPDATE needs an amount, PROVIDER, LOCATION, "
                            "PEDIGREE, COMMENT, UNCERTAINTY, AVOIDED, COST "
                            "or SITE", ln)
                    stmt.update_exchanges.append(upd)
                    self.expect_newline()

            elif kw == "DATA" or (kw == "SET"
                                  and self.peek_at(1).upper() == "DATA"):
                if kw == "SET":
                    self.advance()
                stmt.provenance = self.parse_provenance()
                self.expect_newline()

            elif self.at_word("RATING") or (
                    kw == "SET" and self.peek_at(1).upper() == "RATING"):
                if kw == "SET":
                    self.advance()
                self.advance()
                self.parse_rating(stmt.ratings)
                self.expect_newline()

            elif self.at_word("CONTROL") or (
                    kw == "SET" and self.peek_at(1).upper() == "CONTROL"):
                if kw == "SET":
                    self.advance()
                stmt.control = self.parse_control()
                self.expect_newline()

            elif kw == "SET":
                self.advance()
                if self.match_keyword("DESCRIPTION"):
                    stmt.set_description = self.parse_string_or_expr()
                elif self.match_word("CATEGORY", "FOLDER"):
                    stmt.set_category = self.parse_string_or_expr()
                elif self.match_keyword("LOCATION"):
                    stmt.set_location = self.parse_string_or_expr()
                else:
                    raise ParseError("Expected DESCRIPTION, FOLDER or "
                                     "LOCATION after SET", ln)
                self.expect_newline()

            else:
                raise ParseError(
                    f"'{tok.value}' is not allowed inside EDIT "
                    f"(expected ADD, REMOVE, UPDATE, SET, DATA, CONTROL, "
                    f"ALLOCATION, DEFAULT ALLOCATION, DOCUMENT, SOCIAL, "
                    f"TYPE, INFRASTRUCTURE or END EDIT)", ln)
            self.skip_newlines()

        self.expect_keyword("END")
        self.match_keyword("EDIT")
        self.expect_newline()
        return stmt

    # ── EPD workflow ─────────────────────────────────────

    DATA_CATEGORIES = ("PRIMARY", "SECONDARY", "PROXY")
    EPD_COMMANDS = ("SYSTEMS", "CHECK", "CALCULATE", "REPORT", "DATA",
                    "STATUS", "CLOSE", "SAVE", "DQ", "SENSITIVITY",
                    "EXPORT", "DOCUMENT")

    # EPD SAVE: word(s) -> (key, kind)
    EPD_SAVE_OPTIONS = {
        ("MANUFACTURER",): ("manufacturer", "actor"),
        ("VERIFIER",): ("verifier", "actor"),
        ("OPERATOR",): ("program_operator", "actor"),
        ("GENERATOR",): ("data_generator", "actor"),
        ("PCR",): ("pcr", "source"),
        ("REGISTRATION",): ("registration_id", "text"),
        ("URN",): ("urn", "text"),
        ("VALID", "FROM"): ("valid_from", "date"),
        ("VALID", "UNTIL"): ("valid_until", "date"),
        ("DESCRIPTION",): ("description", "text"),
    }

    def _percent(self, what: str) -> float:
        """A number followed by an optional % sign."""
        value = self.parse_number(what)
        if self.peek().type == TokenType.PERCENT:
            self.advance()
        return value

    def parse_provenance(self) -> dict:
        """DATA PRIMARY|SECONDARY|PROXY SOURCE "type" PROVIDER "who"
        YEAR n [REASON "why"] [SHARE n%]"""
        ln = self.current_line()
        self.advance()                                    # DATA
        if not self.at_word(*self.DATA_CATEGORIES):
            raise ParseError(
                "DATA needs a data category.", ln,
                hint='For example: DATA PRIMARY SOURCE "Collected" PROVIDER '
                     '"EPD owner" YEAR 2025 (or SECONDARY, or PROXY with '
                     'REASON "why").')
        prov = {"category": self.advance().upper(), "line": ln}
        while True:
            if self.match_word("SOURCE"):
                prov["source"] = self.parse_string_or_expr()
            elif self.match_keyword("PROVIDER"):
                prov["provider"] = self.parse_string_or_expr()
            elif self.match_word("YEAR"):
                prov["year"] = self.parse_int("YEAR")
            elif self.match_word("REASON"):
                prov["reason"] = self.parse_string_or_expr()
            elif self.match_word("SHARE"):
                prov["share"] = self._percent("SHARE")
            else:
                break
        missing = [w for w, k in (("SOURCE", "source"), ("PROVIDER", "provider"),
                                  ("YEAR", "year")) if k not in prov]
        if missing:
            raise ParseError(
                f"DATA {prov['category']} is missing {', '.join(missing)}.", ln,
                hint=f'For example: DATA {prov["category"]} SOURCE "Database" '
                     f'PROVIDER "ecoinvent 3.11" YEAR 2024')
        if prov["category"] == "PROXY" and "reason" not in prov:
            raise ParseError(
                "DATA PROXY needs REASON: why the data is a proxy.", ln,
                hint='For example: ... YEAR 2019 REASON "Different country"')
        if "share" in prov and not 0 <= prov["share"] <= 100:
            raise ParseError("SHARE is a percentage between 0 and 100.", ln)
        return prov

    def parse_control(self) -> str:
        """CONTROL DIRECT|NONE"""
        ln = self.current_line()
        self.advance()                                    # CONTROL
        if self.at_word("DIRECT"):
            self.advance()
            return "DIRECT"
        if self.at_keyword("NONE"):
            self.advance()
            return "NONE"
        raise ParseError(
            "CONTROL needs DIRECT or NONE.", ln,
            hint="CONTROL DIRECT: the process is under the manufacturer's "
                 "direct control. CONTROL NONE: it is not.")

    def _module_code(self, what: str) -> str:
        tok = self.peek()
        if tok.type != TokenType.IDENTIFIER:
            raise ParseError(
                f"Expected a module code after {what}, got '{tok.value}'.",
                tok.line, hint="Modules are A1 to A5, B1 to B7, C1 to C4 and D.")
        return self.advance().value.upper()

    def parse_epd(self, line: int) -> Statement:
        """EPD "name" ... END EPD, or an EPD command."""
        self.advance()                                    # EPD
        if self.at_word(*self.EPD_COMMANDS):
            return self.parse_epd_command(line)
        if self.peek().type in (TokenType.NEWLINE, TokenType.EOF,
                                TokenType.COMMENT):
            raise ParseError(
                "EPD needs a name, or a command.", line,
                hint='EPD "Product name" starts a definition (HELP EPD). '
                     'The commands are EPD SYSTEMS, EPD CHECK, EPD '
                     'CALCULATE, EPD DATA QUALITY, EPD REPORT "file.csv", '
                     'EPD SAVE, EPD STATUS and EPD CLOSE.')
        stmt = EpdStmt(line=line, name=self.parse_string_or_expr())
        self.expect_newline()
        self.skip_newlines()
        f, lines = stmt.fields, stmt.lines

        def once(key, ln, label):
            if key in f:
                raise ParseError(f"{label} is given twice in the EPD block.",
                                 ln, hint="Keep one.")
            lines[key] = ln

        def optional(word, key):
            if self.match_word(word):
                f[key] = self.parse_string_or_expr()

        while not self.at_end_of("EPD"):
            tok = self.peek()
            ln = tok.line
            if tok.type == TokenType.EOF:
                raise ParseError("EPD block missing END EPD", line)
            if tok.type in (TokenType.COMMENT, TokenType.NEWLINE):
                self.advance()
                continue
            if self.match_word("PROGRAMME", "PROGRAM"):
                once("programme", ln, "PROGRAMME")
                f["programme"] = self.parse_string_or_expr()
                optional("GPI", "gpi")
            elif self.match_word("PCR"):
                once("pcr", ln, "PCR")
                f["pcr"] = self.parse_string_or_expr()
                optional("VERSION", "pcr_version")
            elif self.match_keyword("DATABASE"):
                once("database", ln, "DATABASE")
                f["database"] = self.parse_string_or_expr()
                optional("VERSION", "database_version")
            elif self.at_word("DECLARED", "FUNCTIONAL"):
                kind = self.advance().upper()
                if not self.match_word("UNIT"):
                    raise ParseError(f"Expected {kind} UNIT amount, unit.", ln,
                                     hint=f"For example: {kind} UNIT 1, m3")
                once("unit_kind", ln, "The declared or functional unit")
                f["unit_kind"] = kind
                f["unit_amount"] = self.parse_expr()
                if self.peek().type == TokenType.COMMA:
                    self.advance()
                f["unit"] = self.parse_unit()
            elif self.match_word("METHOD"):
                once("method", ln, "METHOD")
                f["method"] = self.parse_string_or_expr()
                if self.match_keyword("CATEGORIES"):
                    f["expected_categories"] = self.parse_int("CATEGORIES")
            elif self.match_keyword("FOLDER"):
                once("folder", ln, "FOLDER")
                f["folder"] = self.parse_string_or_expr()
            elif self.match_word("MODULES"):
                once("modules", ln, "MODULES")
                codes = [self._module_code("MODULES")]
                while self.peek().type == TokenType.COMMA:
                    self.advance()
                    codes.append(self._module_code("MODULES"))
                f["modules"] = codes
            elif self.at_word("BIOGENIC") and self.peek_at(1).upper() in (
                    "CONTENT", "EXPORT"):
                self.advance()
                if self.advance().upper() == "CONTENT":
                    self.parse_biogenic_content(f, lines, ln)
                else:
                    self.parse_biogenic_export(f, ln)
            elif self.match_word("BIOGENIC"):
                if not self.match_word("CARBON"):
                    raise ParseError(
                        "Expected BIOGENIC CARBON YES or NO, BIOGENIC "
                        "CONTENT or BIOGENIC EXPORT.", ln)
                once("biogenic", ln, "BIOGENIC CARBON")
                if self.match_word("YES"):
                    f["biogenic"] = True
                elif self.match_word("NO"):
                    f["biogenic"] = False
                else:
                    raise ParseError(
                        "BIOGENIC CARBON needs YES or NO.", ln,
                        hint="BIOGENIC CARBON YES if the product contains "
                             "biogenic carbon, BIOGENIC CARBON NO if not.")
            elif self.match_word("EXEMPT"):
                once("exempt", ln, "EXEMPT")
                if not (self.match_word("C") and self.match_keyword("AND")
                        and self.match_word("D")):
                    raise ParseError(
                        "The exemption covers C1 to C4 and D together: "
                        "write EXEMPT C AND D.", ln)
                self.expect_newline()
                self.skip_newlines()
                exempt = {"line": ln}
                while not self.at_end_of("EXEMPT"):
                    t = self.peek()
                    if t.type == TokenType.EOF:
                        raise ParseError("EXEMPT block missing END EXEMPT", ln)
                    if t.type in (TokenType.COMMENT, TokenType.NEWLINE):
                        self.advance()
                        continue
                    if self.match_word("INTEGRATED"):
                        exempt["integrated"] = self.parse_string_or_expr()
                    elif (self.at_keyword("NOT")
                          and self.peek_at(1).upper() == "IDENTIFIABLE"):
                        self.advance()
                        self.advance()
                        exempt["not_identifiable"] = self.parse_string_or_expr()
                    elif (self.at_keyword("END")
                          and self.peek_at(1).upper() == "OF"):
                        self.advance()
                        if not (self.match_word("OF") and self.match_word("LIFE")
                                and self.match_word("SCENARIOS")):
                            raise ParseError(
                                "Expected END OF LIFE SCENARIOS \"where they "
                                "can be found\".", t.line)
                        exempt["eol_scenarios"] = self.parse_string_or_expr()
                    else:
                        raise ParseError(
                            f"'{t.value}' is not allowed inside EXEMPT "
                            f"(expected INTEGRATED, NOT IDENTIFIABLE, END OF "
                            f"LIFE SCENARIOS or END EXEMPT)", t.line)
                    self.expect_newline()
                    self.skip_newlines()
                self.advance()
                self.advance()                            # END EXEMPT
                f["exempt"] = exempt
            elif self.match_word("CUTOFF"):
                module = self._module_code("CUTOFF")
                item = self.parse_string_or_expr()
                if self.peek().type == TokenType.COMMA:
                    self.advance()
                pct = self._percent("the item")
                f.setdefault("cutoffs", []).append(
                    {"module": module, "item": item, "percent": pct,
                     "line": ln})
            elif self.match_word("GWP"):
                if not self.match_word("INDICATOR"):
                    raise ParseError("Expected GWP INDICATOR \"category name\".",
                                     ln)
                once("gwp_indicator", ln, "GWP INDICATOR")
                f["gwp_indicator"] = self.parse_string_or_expr()
            else:
                raise ParseError(
                    f"'{tok.value}' is not allowed inside EPD (expected "
                    f"PROGRAMME, PCR, DATABASE, DECLARED UNIT, FUNCTIONAL "
                    f"UNIT, METHOD, FOLDER, MODULES, BIOGENIC CARBON, "
                    f"BIOGENIC CONTENT, BIOGENIC EXPORT, EXEMPT C AND D, "
                    f"CUTOFF, GWP INDICATOR or END EPD)", ln)
            self.expect_newline()
            self.skip_newlines()

        self.advance()
        self.advance()                                    # END EPD
        self.expect_newline()
        return stmt

    def parse_epd_command(self, line: int) -> EpdCommandStmt:
        command = self.advance().upper()
        if command == "SENSITIVITY":
            return self.parse_epd_sensitivity(line)
        if command == "DOCUMENT":
            return self.parse_epd_document(line)
        stmt = EpdCommandStmt(line=line, command=command)
        if command == "DATA":
            if not self.match_keyword("QUALITY"):
                raise ParseError("Expected EPD DATA QUALITY.", line)
            stmt.command = "DATA QUALITY"
            if (self.at_word("PARAMETER")
                    and self.peek_at(1).upper() == "SET"):
                self.advance()
                self.advance()
                if self._end_of_line():
                    raise ParseError(
                        "PARAMETER SET needs the name of a parameter set.",
                        line, hint='EPD DATA QUALITY PARAMETER SET "name"')
                stmt.parameter_set = self.parse_string_or_expr()
            elif self.match_keyword("FROM"):
                if self._end_of_line():
                    raise ParseError(
                        "FROM needs a CSV file of scenarios.", line,
                        hint='EPD DATA QUALITY FROM "scenarios.csv"')
                stmt.from_file = self.parse_string_or_expr()
        elif command == "DQ":
            if self.match_word("SHEET"):
                stmt.command = "DQ SHEET"
                self.parse_epd_file_command(
                    stmt, "DQ SHEET", 'EPD DQ SHEET "dq_register.csv"')
            elif self.match_word("TABLE"):
                stmt.command = "DQ TABLE"
                self.parse_epd_file_command(
                    stmt, "DQ TABLE", 'EPD DQ TABLE "data_quality.md"')
            else:
                raise ParseError(
                    "Expected EPD DQ SHEET \"file.csv\" or EPD DQ TABLE "
                    "\"file.md\".", line)
        elif command == "EXPORT":
            if not self.match_word("MODEL"):
                raise ParseError(
                    "Expected EPD EXPORT MODEL \"file.json\".", line)
            stmt.command = "EXPORT MODEL"
            self.parse_epd_file_command(
                stmt, "EXPORT MODEL", 'EPD EXPORT MODEL "model.json"')
        elif command == "CHECK":
            if self.match_word("SKIP"):
                stmt.skip = True
                if self.peek().type in (TokenType.NEWLINE, TokenType.EOF,
                                        TokenType.COMMENT):
                    raise ParseError(
                        "EPD CHECK SKIP needs a reason.", line,
                        hint='For example: EPD CHECK SKIP "Checked on '
                             '12/11/2026, nothing has changed since"')
                stmt.argument = self.parse_string_or_expr()
        elif command == "REPORT":
            if self.peek().type in (TokenType.NEWLINE, TokenType.EOF,
                                    TokenType.COMMENT):
                raise ParseError("EPD REPORT needs a file name.", line,
                                 hint='For example: EPD REPORT "results.csv"')
            stmt.argument = self.parse_string_or_expr()
            if self.match_keyword("LOCATION"):
                if not self.match_word("BASED"):
                    raise ParseError("Expected LOCATION BASED.", line)
                stmt.location_based = True
        elif command == "SAVE":
            example = ('EPD SAVE [REPLACE] [MANUFACTURER "actor"] [VERIFIER '
                       '"actor"] [OPERATOR "actor"] [PCR "source"] [VALID '
                       'FROM "DD/MM/YYYY"] [VALID UNTIL "DD/MM/YYYY"]')
            while self.peek().type in (TokenType.KEYWORD,
                                       TokenType.IDENTIFIER):
                if self.match_word("REPLACE"):
                    stmt.replace = True
                    continue
                first = self.peek().upper()
                second = self.peek_at(1).upper()
                if (first, second) in self.EPD_SAVE_OPTIONS:
                    key, _kind = self.EPD_SAVE_OPTIONS[(first, second)]
                    self.advance()
                    self.advance()
                elif (first,) in self.EPD_SAVE_OPTIONS:
                    key, _kind = self.EPD_SAVE_OPTIONS[(first,)]
                    self.advance()
                else:
                    raise ParseError(
                        f"EPD SAVE doesn't take '{self.peek().value}'.",
                        line, hint=example)
                if key in stmt.options:
                    raise ParseError(f"{first} is given twice.", line)
                if self.peek().type in (TokenType.NEWLINE, TokenType.EOF,
                                        TokenType.COMMENT):
                    raise ParseError(f"{first} needs a value.", line,
                                     hint=example)
                stmt.options[key] = self.parse_string_or_expr()
        self.expect_newline()
        return stmt

    def parse_module(self, line: int) -> ModuleStmt:
        """MODULE A1 ... [TOTAL "name"] ... END MODULE"""
        self.advance()                                    # MODULE
        stmt = ModuleStmt(line=line, code=self._module_code("MODULE"))
        self.expect_newline()
        self.skip_newlines()
        while not self.at_end_of("MODULE"):
            tok = self.peek()
            ln = tok.line
            if tok.type == TokenType.EOF:
                raise ParseError("MODULE block missing END MODULE", line)
            if tok.type == TokenType.IDENTIFIER and tok.upper() == "TOTAL":
                if stmt.total is not None:
                    raise ParseError(
                        f"MODULE {stmt.code} has two TOTAL lines.", ln,
                        hint="A module has one total process.")
                self.advance()
                total = {"name": self.parse_string_or_expr(), "line": ln}
                if self.match_keyword("AS"):
                    total["flow"] = self.parse_string_or_expr()
                    if self.peek().type == TokenType.COMMA:
                        self.advance()
                    total["amount"] = self.parse_expr()
                    if self.peek().type == TokenType.COMMA:
                        self.advance()
                    total["unit"] = self.parse_unit()
                stmt.total = total
                self.expect_newline()
            elif (tok.type == TokenType.IDENTIFIER and tok.upper() == "NET"
                  and self.peek_at(1).upper() == "FLOW"):
                self.advance()
                self.advance()
                net = {"flow": self.parse_string_or_expr(), "line": ln}
                if self.peek().type == TokenType.COMMA:
                    self.advance()
                net["amount"] = self.parse_expr()
                if self.peek().type == TokenType.COMMA:
                    self.advance()
                net["unit"] = self.parse_unit()
                if self.match_keyword("QUALITY"):
                    net["quality"] = self._percent("QUALITY")
                stmt.net_flows.append(net)
                self.expect_newline()
            else:
                inner = self.parse_statement()
                if inner is not None:
                    if isinstance(inner, (EpdStmt, ModuleStmt)):
                        raise ParseError(
                            "EPD and MODULE blocks cannot sit inside a "
                            "MODULE block.", ln,
                            hint=f"Close MODULE {stmt.code} with END MODULE "
                                 f"first.")
                    stmt.body.append(inner)
            self.skip_newlines()
        self.advance()
        self.advance()                                    # END MODULE
        self.expect_newline()
        return stmt

    def parse_parameterise(self, line: int) -> ParameteriseStmt:
        """PARAMETERISE PROCESS "name" [LOCATION "code"] [ALL] CONFIRM"""
        self.advance()                                    # PARAMETERISE
        self.advance()                                    # PROCESS
        if self.peek().type in (TokenType.NEWLINE, TokenType.EOF,
                                TokenType.COMMENT):
            raise ParseError(
                "PARAMETERISE PROCESS needs the name or UUID of a process.",
                line, hint='PARAMETERISE PROCESS "process name" CONFIRM')
        stmt = ParameteriseStmt(line=line, target=self.parse_string_or_expr())
        if self.match_keyword("LOCATION"):
            stmt.location = self.parse_string_or_expr()
        if self.match_word("ALL"):
            stmt.all_flows = True
        if self.match_word("CONFIRM"):
            stmt.confirm = True
        self.expect_newline()
        return stmt

    def parse_new_from_template(self, line: int) -> NewFromTemplateStmt:
        """NEW FROM TEMPLATE "name" AS "file.baslca" """
        self.advance()                                    # NEW
        self.advance()                                    # FROM
        if not self.match_word("TEMPLATE"):
            raise ParseError("Expected NEW FROM TEMPLATE \"name\" AS \"file\".",
                             line)
        template = self.parse_string_or_expr()
        if not self.match_keyword("AS"):
            raise ParseError(
                "NEW FROM TEMPLATE needs AS \"file name\".", line,
                hint='For example: NEW FROM TEMPLATE "epd_skeleton" AS '
                     '"my_epd.baslca"')
        filename = self.parse_string_or_expr()
        self.expect_newline()
        return NewFromTemplateStmt(line=line, template=template,
                                   filename=filename)


def parse(source: str) -> List[Statement]:
    """Parse a complete olcaBASIC program and return a list of AST nodes."""
    try:
        tokens = tokenise(source)
    except TokeniseError as e:
        message = str(e)
        if e.line and message.startswith(f"Line {e.line}: "):
            message = message[len(f"Line {e.line}: "):]
        raise ParseError(message, e.line)
    parser = Parser(tokens)
    return parser.parse_program()


def parse_line(text: str) -> Optional[Statement]:
    """Parse a single line of olcaBASIC (for REPL mode)."""
    tokens, continuation = tokenise_line(text, 1)
    tokens.append(Token(TokenType.EOF, ""))
    parser = Parser(tokens)
    try:
        return parser.parse_statement()
    except (ParseError, IndexError):
        return None
