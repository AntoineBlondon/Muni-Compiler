from .lexer import tokenize

class Parser:
    # precedence table: higher number = higher priority
    OP_PRECEDENCE = {
        "||":  (1,  "left"),
        "&&":  (2,  "left"),
        "==":  (5,  "left"),
        "!=":  (5,  "left"),
        "<":   (5,  "left"),
        "<=":  (5,  "left"),
        ">":   (5,  "left"),
        ">=":  (5,  "left"),
        "+":   (10, "left"),
        "-":   (10, "left"),
        "*":   (20, "left"),
        "/":   (20, "left"),
        "%":   (20, "left"),
    }

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos].kind

    def peek_token(self):
        return self.tokens[self.pos]

    def next(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind):
        tok = self.next()
        if tok.kind != kind:
            raise SyntaxError(f"{tok.line}:{tok.col}: Expected {kind}, got {tok.kind}")
        return tok

    @property
    def ast(self):
        import muni2wasm.ast as _ast
        return _ast

    def parse(self):
        decls = []
        while self.peek() != "EOF":
            # function or constructor: return‐type could be VOID_KW|INT_KW|BOOL_KW|IDENT
            if (
                (self.peek() in ("VOID_KW","INT_KW","BOOL_KW") or self.peek()=="IDENT")
                and self.tokens[self.pos+1].kind=="IDENT"
                and self.tokens[self.pos+2].kind=="LPAREN"
            ):
                decls.append(self.parse_function_declaration())
            elif self.peek() == "STRUCTURE_KW":
                decls.append(self.parse_structure_declaration())
            else:
                decls.append(self.parse_stmt())
        return self.ast.Program(decls)

    def parse_stmt(self, semi=True):
        tok = self.peek_token()
        kind = tok.kind

        if kind == "RETURN_KW":
            self.expect("RETURN_KW")
            expr = None
            if self.peek() != "SEMI":
                expr = self.parse_expr()
            self.expect("SEMI")
            return self.ast.ReturnStmt(expr, pos=(tok.line, tok.col))

        if self.peek() == "BREAK_KW":
            tok = self.next()
            self.expect("SEMI")
            return self.ast.BreakStmt(pos=(tok.line, tok.col))
        if self.peek() == "CONTINUE_KW":
            tok = self.next()
            self.expect("SEMI")
            return self.ast.ContinueStmt(pos=(tok.line, tok.col))

        if kind == "IF_KW":
            return self.parse_if(tok)
        if self.peek() == "WHILE_KW":
            return self.parse_while()
        if self.peek() == "FOR_KW":
            return self.parse_for()
        if self.peek() == "DO_KW":
            return self.parse_do()
        if self.peek() == "UNTIL_KW":
            return self.parse_until()

        # local declaration: int|boolean|void
        if kind in ["INT_KW", "BOOL_KW", "VOID_KW"]:
            type_tok = self.next()
            name_tok = self.expect("IDENT")
            self.expect("ASSIGN")
            expr = self.parse_expr()
            if semi: self.expect("SEMI")
            return self.ast.VariableDeclaration(
                type_tok.text, name_tok.text, expr,
                pos=(type_tok.line, type_tok.col)
            )

        # struct‐typed declaration: e.g. Point p = Point(...);
        if (kind == "IDENT"
            and self.tokens[self.pos+1].kind == "IDENT"
            and self.tokens[self.pos+2].kind == "ASSIGN"):
            type_tok = self.next()
            struct_type = type_tok.text
            name_tok = self.expect("IDENT")
            self.expect("ASSIGN")
            expr = self.parse_expr()
            if semi: self.expect("SEMI")
            return self.ast.VariableDeclaration(
                struct_type, name_tok.text, expr,
                pos=(type_tok.line, type_tok.col)
            )

        # member‐assignment: p.x = expr;
        if kind == "IDENT" and self.tokens[self.pos+1].kind == "DOT":
            # look ahead for ASSIGN
            j = self.pos + 1
            while j < len(self.tokens) and self.tokens[j].kind == "DOT":
                if self.tokens[j+1].kind != "IDENT":
                    break
                j += 2
            if j < len(self.tokens) and self.tokens[j].kind == "ASSIGN":
                lhs = self.parse_primary()
                self.expect("ASSIGN")
                rhs = self.parse_expr()
                if semi: self.expect("SEMI")
                return self.ast.MemberAssignment(lhs, lhs.field, rhs, # type: ignore
                                                pos=(tok.line, tok.col))

        # plain assignment: x = expr;
        if kind == "IDENT" and self.tokens[self.pos+1].kind == "ASSIGN":
            return self.parse_assignment(tok, semi)

        # fallback: any other expression as statement
        expr = self.parse_expr()
        if semi: self.expect("SEMI")
        return expr

    def parse_structure_declaration(self):
        kw       = self.expect("STRUCTURE_KW")
        name_tok = self.expect("IDENT")
        struct_name = name_tok.text
        self.expect("LBRACE")

        fields, methods = [], []
        while self.peek() != "RBRACE":

            # --- 1) constructor?  IDENT == struct_name + LPAREN ---
            if (self.peek()=="IDENT"
                and self.tokens[self.pos].text == struct_name
                and self.tokens[self.pos+1].kind == "LPAREN"):
                ctor_tok = self.next()   # consume struct name
                # parse params
                self.expect("LPAREN")
                params = []
                if self.peek() != "RPAREN":
                    while True:
                        pk = self.peek()
                        if pk == "INT_KW":
                            self.next(); p_ty="int"
                        elif pk == "BOOL_KW":
                            self.next(); p_ty="boolean"
                        elif pk == "IDENT":
                            p_tok = self.next(); p_ty = p_tok.text
                        else:
                            t = self.peek_token()
                            raise SyntaxError(f"{t.line}:{t.col}: Unexpected parameter type {pk}")
                        p_name = self.expect("IDENT").text
                        params.append((p_name, p_ty))
                        if self.peek()=="COMMA":
                            self.next(); continue
                        break
                self.expect("RPAREN")

                # body
                self.expect("LBRACE")
                body = []
                while self.peek() != "RBRACE":
                    body.append(self.parse_stmt())
                self.expect("RBRACE")

                # record as _static_ constructor returning its own struct
                methods.append(self.ast.MethodDeclaration(
                    struct_name,        # name == struct
                    params,
                    struct_name,        # return type == struct
                    body,
                    True,               # is_static
                    pos=(ctor_tok.line, ctor_tok.col)
                ))
                continue

            # --- 2) ordinary field? type can be int, boolean or any struct IDENT ---
            if (self.peek() in ("INT_KW","BOOL_KW","IDENT")
                and self.tokens[self.pos+2].kind == "SEMI"):
                tok_type = self.next()
                if tok_type.kind == "INT_KW":
                    type_name = "int"
                elif tok_type.kind == "BOOL_KW":
                    type_name = "boolean"
                else:
                    # user‐defined struct
                    type_name = tok_type.text
                idt = self.expect("IDENT")
                self.expect("SEMI")
                fields.append(self.ast.FieldDeclaration(
                    idt.text, type_name,
                    pos=(tok_type.line, tok_type.col)
                ))
                continue


            # --- 3) method (static or instance) ---
            is_static = False
            if self.peek() == "STATIC_KW":
                self.next()
                is_static = True

            # parse return type: void|int|boolean or a user‐defined struct name
            tok = self.peek()
            if tok in ("VOID_KW","INT_KW","BOOL_KW"):
                rt_tok = self.next()
                rt = {"VOID_KW":"void","INT_KW":"int","BOOL_KW":"boolean"}[rt_tok.kind]
            elif tok == "IDENT":
                rt_tok = self.next()
                rt = rt_tok.text
            else:
                t = self.peek_token()
                raise SyntaxError(f"{t.line}:{t.col}: Expected return type, got {tok}")

            # method name
            idt = self.expect("IDENT")

            # params
            self.expect("LPAREN")
            params = []
            if self.peek() != "RPAREN":
                while True:
                    kind = self.peek()
                    # built-in types
                    if kind in ("INT_KW","BOOL_KW","VOID_KW"):
                        p_tok = self.next()
                        ptype = {"INT_KW":"int","BOOL_KW":"boolean","VOID_KW":"void"}[p_tok.kind]
                    # struct type
                    elif kind == "IDENT":
                        p_tok = self.next()
                        ptype = p_tok.text
                    else:
                        t = self.peek_token()
                        raise SyntaxError(f"{t.line}:{t.col}: Unexpected parameter type {kind}")

                    pn = self.expect("IDENT")
                    params.append((pn.text, ptype))

                    if self.peek() == "COMMA":
                        self.next()
                        continue
                    break
            self.expect("RPAREN")

            # body
            self.expect("LBRACE")
            body = []
            while self.peek() != "RBRACE":
                body.append(self.parse_stmt())
            self.expect("RBRACE")

            methods.append(self.ast.MethodDeclaration(
                idt.text, params, rt, body, is_static,
                pos=(rt_tok.line, rt_tok.col)
            ))


        self.expect("RBRACE")
        return self.ast.StructureDeclaration(
            struct_name, fields, methods,
            pos=(kw.line, kw.col)
        )

    def parse_function_declaration(self):
        # return type: VOID_KW|INT_KW|BOOL_KW|IDENT
        tok = self.peek()
        if tok in ("INT_KW","BOOL_KW","VOID_KW"):
            tok_ret = self.next()
            rt = {"INT_KW":"int","BOOL_KW":"boolean","VOID_KW":"void"}[tok_ret.kind]
        else:
            tok_ret = self.next()
            rt = tok_ret.text

        name_tok = self.expect("IDENT")
        name = name_tok.text

        # params
        self.expect("LPAREN")
        params = []
        if self.peek() != "RPAREN":
            while True:
                kind = self.peek()
                if kind in ("INT_KW","BOOL_KW","VOID_KW"):
                    p_tok = self.next()
                    p_ty = {"INT_KW":"int","BOOL_KW":"boolean","VOID_KW":"void"}[p_tok.kind]
                elif kind == "IDENT":
                    p_tok = self.next()
                    p_ty = p_tok.text
                else:
                    t = self.peek_token()
                    raise SyntaxError(f"{t.line}:{t.col}: Unexpected parameter type {kind}")
                id_tok = self.expect("IDENT")
                params.append((id_tok.text, p_ty))
                if self.peek()=="COMMA":
                    self.next(); continue
                break
        self.expect("RPAREN")

        # body
        self.expect("LBRACE")
        body=[]
        while self.peek()!="RBRACE":
            body.append(self.parse_stmt())
        self.expect("RBRACE")

        return self.ast.FunctionDeclaration(
            name, params, rt, body, pos=(tok_ret.line, tok_ret.col)
        )

    # (rest of your parse_if, parse_while, parse_for, etc. unchanged)
    # …
    # make sure your parse_if, parse_while, parse_until, parse_for, parse_do,
    # parse_assignment, parse_expr, parse_unary, parse_primary all remain exactly
    # as they were.


    def parse_if(self, tok_kw):
        
        self.expect("IF_KW")
        self.expect("LPAREN")
        cond = self.parse_expr()
        self.expect("RPAREN")
        self.expect("LBRACE")
        then_stmts = []
        while self.peek() != "RBRACE":
            then_stmts.append(self.parse_stmt())
        self.expect("RBRACE")

        else_stmts = []
        if self.peek() == "ELSE_KW":
            self.expect("ELSE_KW")
            self.expect("LBRACE")
            while self.peek() != "RBRACE":
                else_stmts.append(self.parse_stmt())
            self.expect("RBRACE")

        return self.ast.IfStmt(cond, then_stmts, else_stmts, pos=(tok_kw.line, tok_kw.col))
    
    def parse_while(self):
        tok = self.expect("WHILE_KW")
        self.expect("LPAREN")
        cond = self.parse_expr()
        self.expect("RPAREN")
        self.expect("LBRACE")
        body = []
        while self.peek() != "RBRACE":
            body.append(self.parse_stmt())
        self.expect("RBRACE")

        else_body = []
        if self.peek() == "ELSE_KW":
            self.next()
            self.expect("LBRACE")
            while self.peek() != "RBRACE":
                else_body.append(self.parse_stmt())
            self.expect("RBRACE")

        return self.ast.WhileStmt(cond, body, else_body, pos=(tok.line, tok.col))
    def parse_until(self):
        tok = self.expect("UNTIL_KW")
        self.expect("LPAREN")
        cond = self.parse_expr()
        self.expect("RPAREN")
        self.expect("LBRACE")
        body = []
        while self.peek() != "RBRACE":
            body.append(self.parse_stmt())
        self.expect("RBRACE")

        else_body = []
        if self.peek() == "ELSE_KW":
            self.next()
            self.expect("LBRACE")
            while self.peek() != "RBRACE":
                else_body.append(self.parse_stmt())
            self.expect("RBRACE")

        return self.ast.UntilStmt(cond, body, else_body, pos=(tok.line, tok.col))

    def parse_for(self):
        tok = self.expect("FOR_KW")
        self.expect("LPAREN")

        # init
        init = None
        if self.peek() != "SEMI":
            init = self.parse_stmt(semi=False)
        self.expect("SEMI")

        # condition
        cond = None
        if self.peek() != "SEMI":
            cond = self.parse_expr()
        self.expect("SEMI")

        # post
        post = None
        if self.peek() != "RPAREN":
            post = self.parse_stmt(semi=False)
        self.expect("RPAREN")

        # body
        self.expect("LBRACE")
        body = []
        while self.peek() != "RBRACE":
            body.append(self.parse_stmt())
        self.expect("RBRACE")

        else_body = []
        if self.peek() == "ELSE_KW":
            self.next()
            self.expect("LBRACE")
            while self.peek() != "RBRACE":
                else_body.append(self.parse_stmt())
            self.expect("RBRACE")

        return self.ast.ForStmt(init, cond, post, body, else_body, pos=(tok.line, tok.col))

    def parse_do(self):
        tok = self.expect("DO_KW")

        # optional count
        count = None
        if self.peek() != "LBRACE":
            count = self.parse_expr()

        # body
        self.expect("LBRACE")
        body = []
        while self.peek() != "RBRACE":
            body.append(self.parse_stmt())
        self.expect("RBRACE")

        # optional while-condition
        cond = None
        if self.peek() == "WHILE_KW":
            self.next()
            self.expect("LPAREN")
            cond = self.parse_expr()
            self.expect("RPAREN")

        # optional else
        else_body = []
        if self.peek() == "ELSE_KW":
            self.next()
            self.expect("LBRACE")
            while self.peek() != "RBRACE":
                else_body.append(self.parse_stmt())
            self.expect("RBRACE")

        return self.ast.DoStmt(count, cond, body, else_body, pos=(tok.line, tok.col))

    
    def parse_call(self):
        name_tok = self.expect("IDENT")
        self.expect("LPAREN")
        args=[]
        if self.peek()!="RPAREN":
            while True:
                args.append(self.parse_expr())
                if self.peek()=="COMMA":
                    self.expect("COMMA"); continue
                break
        self.expect("RPAREN")
        return self.ast.FunctionCall(name_tok.text, args, pos=(name_tok.line,name_tok.col))


    def parse_assignment(self, tok_ident, semi=True):
        # tok_ident is the IDENT token
        self.expect("IDENT")
        self.expect("ASSIGN")
        expr = self.parse_expr()
        if semi: self.expect("SEMI")
        return self.ast.VariableAssignment(
            tok_ident.text, expr,
            pos=(tok_ident.line, tok_ident.col)
        )

    def parse_expr(self, min_prec=0):
        lhs = self.parse_unary()

        while (
            self.peek() == "OP" and 
            (op := self.tokens[self.pos].text) in self.OP_PRECEDENCE
        ):
            prec, assoc = self.OP_PRECEDENCE[op]
            if prec < min_prec:
                break
            # consume operator
            self.next()
            # for left‐assoc, RHS must be strictly higher
            next_min = prec + (1 if assoc == "left" else 0)
            rhs = self.parse_expr(next_min)
            lhs = self.ast.BinOp(op, lhs, rhs)

        return lhs
    
    def parse_unary(self):
        tok = self.peek_token()
        # logical not
        if tok.kind == "OP" and tok.text == "!":
            self.next()
            expr = self.parse_unary()
            return self.ast.UnaryOp("!", expr, pos=(tok.line, tok.col))

        # arithmetic negation
        if tok.kind == "OP" and tok.text == "-":
            self.next()
            expr = self.parse_unary()
            return self.ast.UnaryOp("-", expr, pos=(tok.line, tok.col))

        # otherwise fall back to primary
        return self.parse_primary()


    def parse_primary(self):
        tok = self.peek_token()
        kind, text, line, col = tok.kind, tok.text, tok.line, tok.col

        # literal number
        if kind == "NUMBER":
            self.next()
            return self.ast.Number(text, pos=(line,col))

        # boolean literal
        if kind == "TRUE":
            self.next()
            return self.ast.BooleanLiteral(True, pos=(line,col))
        if kind == "FALSE":
            self.next()
            return self.ast.BooleanLiteral(False, pos=(line,col))

        if kind == "NULL_KW":
            self.next()
            return self.ast.NullLiteral(pos=(line,col))

        # identifier or function‐call
        if kind == "IDENT":
            name = text
            self.next()
            # call‐lookahead
            if self.peek() == "LPAREN":
                # it's a FuncCall expression
                self.next()  # consume "("
                args = []
                if self.peek() != "RPAREN":
                    while True:
                        args.append(self.parse_expr())
                        if self.peek() == "COMMA":
                            self.next(); continue
                        break
                self.expect("RPAREN")
                node = self.ast.FunctionCall(name, args, pos=(line,col))
            else:
                node = self.ast.Ident(name, pos=(line,col))
            # 1) any number of “.field” or “.method(...)”
            while self.peek() == "DOT":
                self.next()  # consume '.'
                name = self.expect("IDENT").text

                # 1a) method call?
                if self.peek() == "LPAREN":
                    self.next()
                    args = []
                    if self.peek() != "RPAREN":
                        while True:
                            args.append(self.parse_expr())
                            if self.peek() == "COMMA":
                                self.next(); continue
                            break
                    self.expect("RPAREN")
                    node = self.ast.MethodCall(node, name, args, pos=(line,col))
                else:
                    # simple field access
                    node = self.ast.MemberAccess(node, name, pos=(line,col))

            return node

        # parenthesized sub‐expr
        if kind == "LPAREN":
            self.next()
            expr = self.parse_expr()
            self.expect("RPAREN")
            return expr

        raise SyntaxError(f"{line}:{col}: Unexpected token in primary: {kind}")

