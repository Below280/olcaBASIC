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


class ParseError(Exception):
    def __init__(self, message: str, line: int = 0):
        self.line = line
        super().__init__(f"Line {line}: {message}" if line else message)


class Parser:
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

        if kw == "EDIT":
            return self.parse_edit(line)

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
            topic = ""
            if self.peek().type in (TokenType.IDENTIFIER,
                                     TokenType.KEYWORD):
                topic = self.advance().value
            self.expect_newline()
            return HelpStmt(line=line, topic=topic)

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
            return self.parse_dir_nav(line)  # undocumented alias

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

        # Known BASIC keywords we don't implement: say so plainly
        if kw in ("GOTO", "GOSUB", "RETURN", "ON", "LOAD",
                  "HISTORY", "INSPECT", "LIST", "NEW"):
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
                f"as a variable name (try {tok.value.lower()}_value)", line)
        if tok.type != TokenType.IDENTIFIER:
            raise ParseError(f"Expected variable name after LET", line)
        name = self.advance().value
        if self.peek().type != TokenType.EQUALS:
            raise ParseError(f"Expected '=' after '{name}'", line)
        self.advance()  # consume =
        expr = self.parse_expr()
        self.expect_newline()
        return LetStmt(line=line, name=name, expr=expr)

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

        # Parse type and modifiers
        while self.peek().type == TokenType.KEYWORD:
            kw = self.peek().upper()
            if kw in ("PRODUCT", "WASTE", "ELEMENTARY"):
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
                         direction=direction, is_new=is_new)

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
            if (self.at_keyword("FOLDER", "PROVIDER")
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
                    elif self.match_keyword("WASTE"):
                        is_waste = True
                    else:
                        raise ParseError(
                            f"'{self.peek().value}' is not allowed inside "
                            f"BRIDGE (expected FOLDER, PROVIDER, WASTE or "
                            f"END BRIDGE)", self.current_line())
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
                           provider=provider, provider_flow=provider_flow)

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

            elif kw in ("INPUT", "OUTPUT"):
                ex = self.parse_exchange()
                exchanges.append(ex)

            elif kw == "LET" or self.at_word("PARAM"):
                stmt = self.parse_let(tok.line)
                local_params.append(stmt)

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
                    f"DESCRIPTION or END PROCESS)", tok.line)

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
            local_params=local_params, read_data=read_data)

    def parse_exchange(self) -> ExchangeDef:
        """Parse an INPUT or OUTPUT line inside a PROCESS block."""
        direction = self.advance().upper()  # INPUT or OUTPUT

        # Check for NEW keyword
        is_new = False
        if self.match_keyword("NEW"):
            is_new = True

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

        # Parse trailing modifiers
        # Allow optional comma before modifiers (e.g. "m3, PRODUCT")
        if self.peek().type == TokenType.COMMA:
            self.advance()
        while self.peek().type == TokenType.KEYWORD:
            kw = self.peek().upper()
            if kw == "PRODUCT":
                is_product = True
                self.advance()
            elif kw == "WASTE":
                is_waste = True
                self.advance()
            elif kw == "TO":
                self.advance()
                if self.at_keyword("AIR"):
                    compartment = "AIR"
                    self.advance()
                elif self.at_keyword("WATER"):
                    compartment = "WATER"
                    self.advance()
                elif self.at_keyword("SOIL"):
                    compartment = "SOIL"
                    self.advance()
            elif kw == "FROM":
                self.advance()
                if self.at_keyword("NATURE"):
                    compartment = "NATURE"
                    self.advance()
            elif kw == "PROVIDER":
                self.advance()
                provider = self.parse_string_or_expr()
            elif kw == "FORMULA":
                self.advance()
                formula = self.parse_string_or_expr()
            elif kw == "LOCATION":
                self.advance()
                location = self.parse_string_or_expr()
            else:
                break
            if self.peek().type == TokenType.COMMA:
                self.advance()

        self.expect_newline()

        return ExchangeDef(
            direction=direction, flow_name=flow_name, amount=amount,
            unit=unit, is_new=is_new, is_product=is_product,
            is_waste=is_waste,
            direction_compartment=compartment, provider=provider,
            formula=formula, location=location)

    def parse_system(self, line: int) -> SystemStmt:
        self.advance()  # consume SYSTEM
        process_ref = self.parse_string_or_expr()

        linking = "PREFER_DEFAULTS"
        target_amount = None
        target_unit = ""
        target_property = None
        folder = None

        self.expect_newline()
        self.skip_newlines()

        # Block form only if the next line is a SYSTEM sub-command
        # or END SYSTEM. A bare END belongs to an enclosing block.
        if (self.at_keyword("LINKING", "TARGET", "FOLDER")
                or self.at_end_of("SYSTEM")):
            while not self.at_keyword("END"):
                if self.peek().type == TokenType.EOF:
                    break
                if self.match_keyword("LINKING"):
                    if not self.at_keyword("PREFER_DEFAULTS", "ONLY_DEFAULTS"):
                        raise ParseError(
                            "LINKING must be PREFER_DEFAULTS or "
                            "ONLY_DEFAULTS", self.current_line())
                    linking = self.advance().upper()
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
                        f"SYSTEM (expected LINKING, TARGET, FOLDER or "
                        f"END SYSTEM)", self.current_line())
                self.expect_newline()
                self.skip_newlines()

            self.expect_keyword("END")
            self.match_keyword("SYSTEM")
            self.expect_newline()

        return SystemStmt(
            line=line, process_ref=process_ref, linking=linking,
            target_amount=target_amount, target_unit=target_unit,
            target_property=target_property, folder=folder)

    def parse_calculate(self, line: int) -> CalculateStmt:
        self.advance()  # consume CALCULATE
        system = self.parse_string_or_expr()
        self.expect_keyword("USING")
        method = self.parse_string_or_expr()
        allocation = ""
        if self.match_keyword("ALLOCATE"):
            if self.peek().type == TokenType.KEYWORD:
                allocation = self.advance().upper()
        self.expect_newline()
        return CalculateStmt(line=line, system=system, method=method,
                              allocation=allocation)

    def parse_contribution(self, line: int) -> ContributionStmt:
        self.advance()  # consume CONTRIBUTION
        system = self.parse_string_or_expr()
        self.expect_keyword("USING")
        method = self.parse_string_or_expr()
        top = 10
        allocation = ""
        categories = []

        if self.match_keyword("TOP"):
            top = self.parse_int("TOP")
        if self.match_keyword("ALLOCATE"):
            if self.peek().type == TokenType.KEYWORD:
                allocation = self.advance().upper()

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
            categories=categories, allocation=allocation)

    def parse_inventory(self, line: int) -> InventoryStmt:
        self.advance()  # consume INVENTORY
        system = self.parse_string_or_expr()
        self.expect_keyword("USING")
        method = self.parse_string_or_expr()
        max_flows = 50
        allocation = ""
        if self.match_keyword("MAX"):
            max_flows = self.parse_int("MAX")
        if self.match_keyword("ALLOCATE"):
            if self.peek().type == TokenType.KEYWORD:
                allocation = self.advance().upper()
        self.expect_newline()
        return InventoryStmt(line=line, system=system, method=method,
                              max_flows=max_flows, allocation=allocation)

    def parse_montecarlo(self, line: int) -> MonteCarloStmt:
        self.advance()  # consume MONTECARLO
        system = self.parse_string_or_expr()
        self.expect_keyword("USING")
        method = self.parse_string_or_expr()
        runs = 1000
        allocation = ""
        if self.match_keyword("RUNS"):
            runs = self.parse_int("RUNS")
        if self.match_keyword("ALLOCATE"):
            if self.peek().type == TokenType.KEYWORD:
                allocation = self.advance().upper()
        self.expect_newline()
        return MonteCarloStmt(line=line, system=system, method=method,
                               runs=runs, allocation=allocation)

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

        variation = 20.0
        allocation = ""
        if self.match_keyword("BY"):
            variation = self.parse_number("BY")
            self.match_keyword("PERCENT")  # optional
            if self.peek().type == TokenType.PERCENT:
                self.advance()

        if self.match_keyword("ALLOCATE"):
            if self.peek().type == TokenType.KEYWORD:
                allocation = self.advance().upper()

        self.expect_newline()
        self.skip_newlines()

        parameters = []
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

        return SensitivityStmt(
            line=line, system=system, method=method,
            variation_pct=variation, parameters=parameters,
            from_csv=from_csv, save_to=save_to, allocation=allocation)

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

            if self.match_keyword("ALLOCATE"):
                if self.peek().type == TokenType.KEYWORD:
                    allocation = self.advance().upper()

            self.expect_newline()
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
                allocation=allocation)

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
        against = None
        if self.match_keyword("TIER"):
            tier = self.parse_int("TIER")
        if self.match_keyword("AGAINST"):
            against = self.parse_string_or_expr()
        self.expect_newline()
        return CheckStmt(line=line, system=system, tier=tier,
                          against=against)

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
        if self.match_keyword("RESULTS"):
            filename = self.parse_string_or_expr()
            self.expect_newline()
            return SaveResultsStmt(line=line, filename=filename)
        # SAVE "filename" (save program — REPL mode)
        filename = self.parse_string_or_expr()
        self.expect_newline()
        return SaveResultsStmt(line=line, filename=filename)

    def parse_export(self, line: int) -> ExportResultsStmt:
        self.advance()  # consume EXPORT
        self.match_keyword("RESULTS")
        self.match_keyword("TO")
        filename = self.parse_string_or_expr()
        self.expect_newline()
        return ExportResultsStmt(line=line, filename=filename)

    def parse_delete(self, line: int) -> DeleteStmt:
        self.advance()  # consume DELETE
        entity_type = ""
        if self.at_keyword("PROCESS", "FLOW", "SYSTEM"):
            entity_type = self.advance().upper()
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
        if self.at_word("PROCESS", "FLOW", "METHOD", "CHEMICAL",
                         "UNIT"):
            entity_type = self.advance().upper()
        else:
            raise ParseError(
                "FIND needs a type: PROCESS, FLOW, METHOD, CHEMICAL "
                "or UNIT", line)
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
        path = self.parse_string_or_expr()
        self.expect_newline()
        return DirStmt(line=line, path=path)

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

    def parse_edit(self, line: int) -> EditProcessStmt:
        self.advance()  # EDIT
        self.expect_keyword("PROCESS")
        target = self.parse_string_or_expr()
        self.expect_newline()
        self.skip_newlines()

        stmt = EditProcessStmt(line=line, target=target)

        while not self.at_keyword("END"):
            if self.peek().type == TokenType.EOF:
                raise ParseError("EDIT block missing END EDIT", line)
            kw = self.peek().upper() if self.peek().type == TokenType.KEYWORD else ""

            if kw == "ADD":
                self.advance()
                if self.at_keyword("INPUT", "OUTPUT"):
                    ex = self.parse_exchange()
                    stmt.add_exchanges.append(ex)
                elif self.at_word("PARAM"):
                    let_stmt = self.parse_let(self.peek().line)
                    stmt.add_params.append(let_stmt)
                else:
                    raise ParseError("Expected INPUT, OUTPUT or PARAM "
                                     "after ADD", self.current_line())
            elif kw == "UPDATE":
                self.advance()
                if self.match_word("EXCHANGE"):
                    flow_ref = self.parse_string_or_expr()
                    upd = {"flow_ref": flow_ref}
                    if self.match_word("AMOUNT"):
                        upd["amount"] = self.parse_expr()
                    if self.match_keyword("FORMULA"):
                        upd["formula"] = self.parse_string_or_expr()
                    if self.match_keyword("PROVIDER"):
                        upd["provider"] = self.parse_string_or_expr()
                    stmt.update_exchanges.append(upd)
                    self.expect_newline()
                elif self.match_word("PARAM"):
                    name = self.advance().value
                    if self.peek().type != TokenType.EQUALS:
                        raise ParseError(f"Expected '=' after {name}",
                                         self.current_line())
                    self.advance()
                    val = self.parse_expr()
                    stmt.update_params[name] = val
                    self.expect_newline()
            elif kw == "REMOVE":
                self.advance()
                self.match_word("EXCHANGE")
                ref = self.parse_string_or_expr()
                if not isinstance(ref, StringLiteral):
                    raise ParseError("REMOVE EXCHANGE needs a quoted "
                                     "flow name", self.current_line())
                stmt.remove_exchanges.append(ref.value)
                self.expect_newline()
            elif kw == "SET":
                self.advance()
                if self.match_keyword("DESCRIPTION"):
                    stmt.set_description = self.parse_string_or_expr()
                elif self.match_word("CATEGORY"):
                    stmt.set_category = self.parse_string_or_expr()
                elif self.match_keyword("LOCATION"):
                    stmt.set_location = self.parse_string_or_expr()
                self.expect_newline()
            elif self.peek().type in (TokenType.COMMENT, TokenType.NEWLINE):
                self.advance()
            else:
                raise ParseError(
                    f"'{self.peek().value}' is not allowed inside EDIT "
                    f"(expected ADD, UPDATE, REMOVE, SET or END EDIT)",
                    self.current_line())
            self.skip_newlines()

        self.expect_keyword("END")
        self.match_keyword("EDIT")
        self.expect_newline()

        return stmt


def parse(source: str) -> List[Statement]:
    """Parse a complete olcaBASIC program and return a list of AST nodes."""
    try:
        tokens = tokenise(source)
    except TokeniseError as e:
        raise ParseError(str(e).split(": ", 1)[-1], e.line)
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
