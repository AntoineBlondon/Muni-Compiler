from .lexer import tokenize

class Parser:
    # precedence table: higher number = higher priority
    OP_PRECEDENCE = {
        # logical OR/AND
        "||":  (1,  "left"),
        "&&":  (2,  "left"),

        # comparisons
        "==":  (5,  "left"),
        "!=":  (5,  "left"),
        "<":   (5,  "left"),
        "<=":  (5,  "left"),
        ">":   (5,  "left"),
        ">=":  (5,  "left"),

        # add/sub
        "+":   (10, "left"),
        "-":   (10, "left"),

        # mul/div/rem
        "*":   (20, "left"),
        "/":   (20, "left"),
        "%":   (20, "left"),
    }

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        # peek_kind
        return self.tokens[self.pos].kind

    def peek_token(self):
        # full token
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
            if self.peek() in ("VOID_KW","INT_KW","BOOL_KW") \
               and self.tokens[self.pos+1].kind=="IDENT" \
               and self.tokens[self.pos+2].kind=="LPAREN":
                decls.append(self.parse_function_declaration())
            elif self.peek() =="STRUCTURE_KW":
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
            if self.peek()!="SEMI":
                expr = self.parse_expr()
            self.expect("SEMI")
            return self.ast.ReturnStmt(expr, pos=(tok.line,tok.col))
        
        
        if self.peek()=="BREAK_KW":
            tok=self.next()
            self.expect("SEMI")
            return self.ast.BreakStmt(pos=(tok.line,tok.col))
        if self.peek()=="CONTINUE_KW":
            tok=self.next()
            self.expect("SEMI")
            return self.ast.ContinueStmt(pos=(tok.line,tok.col))

        if kind == "IF_KW":
            return self.parse_if(tok)
        if self.peek()=="WHILE_KW":
            return self.parse_while()
        if self.peek()=="FOR_KW":
            return self.parse_for()
        if self.peek()=="DO_KW":
            return self.parse_do()
        if self.peek()=="UNTIL_KW":
            return self.parse_until()

    
        


        if kind in ["INT_KW", "BOOL_KW", "VOID_KW"]:
            type_tok = self.next()
            name_tok = self.expect("IDENT")
            self.expect("ASSIGN")
            expr = self.parse_expr()
            if semi: self.expect("SEMI")
            return self.ast.VariableDeclaration(
                type_tok.text,
                name_tok.text,
                expr,
                pos=(type_tok.line, type_tok.col)
            )

        # 1) struct-typed declaration?  e.g. Point p = Point(…);
        if kind == "IDENT" \
            and self.tokens[self.pos+1].kind == "IDENT" \
            and self.tokens[self.pos+2].kind == "ASSIGN":
            # consume the type name
            type_tok = self.next()
            struct_type = type_tok.text
            # consume the var name
            name_tok = self.expect("IDENT")
            # the “= expr;” part
            self.expect("ASSIGN")
            expr = self.parse_expr()
            if semi: self.expect("SEMI")
            return self.ast.VariableDeclaration(
                struct_type,
                name_tok.text,
                expr,
                pos=(type_tok.line, type_tok.col)
            )
        # member‐assignment?   e.g.  p.x = expr;
        # lookahead for IDENT DOT IDENT [(.IDENT)*] ASSIGN
        if kind == "IDENT" and self.tokens[self.pos+1].kind == "DOT":
            # scan ahead to see if ends in ASSIGN
            j = self.pos + 1
            while j < len(self.tokens) and self.tokens[j].kind == "DOT":
                # must be ". IDENT"
                if self.tokens[j+1].kind != "IDENT":
                    break
                j += 2
            if j < len(self.tokens) and self.tokens[j].kind == "ASSIGN":
                # parse the MemberAccess first
                lhs = self.parse_primary()   # this will consume IDENT and all .field
                # now we are at ASSIGN
                self.expect("ASSIGN")
                rhs = self.parse_expr()
                if semi: self.expect("SEMI")
                return self.ast.MemberAssignment(
                    lhs, lhs.field, rhs,    # type: ignore
                    pos=(tok.line, tok.col)
                ) 
        # 2) plain assignment: x = expr;
        if kind == "IDENT" and self.tokens[self.pos+1].kind == "ASSIGN":
            return self.parse_assignment(tok, semi)

       
        # fallback — any other expression (e.g. struct-ctor call) can be a statement
        expr = self.parse_expr()
        if semi: self.expect("SEMI")
        return expr
    
    def parse_structure_declaration(self):
        kw = self.expect("STRUCTURE_KW")
        name_tok = self.expect("IDENT")
        self.expect("LBRACE")

        fields, methods = [], []
        while self.peek() != "RBRACE":
            # lookahead: is this a field or method?
            # Fields:  (INT_KW|BOOL_KW) IDENT SEMI
            # Methods: [STATIC_KW] (VOID_KW|INT_KW|BOOL_KW) IDENT LPAREN …
            if self.peek() in ("INT_KW", "BOOL_KW") and self.tokens[self.pos+2].kind == "SEMI":
                # field
                tok_type = self.next()
                type_name = "int" if tok_type.kind=="INT_KW" else "boolean"
                idt = self.expect("IDENT")
                self.expect("SEMI")
                fields.append(self.ast.FieldDeclaration(idt.text, type_name, pos=(tok_type.line,tok_type.col)))

            else:
                # method
                is_static = False
                if self.peek() == "STATIC_KW":
                    self.next()
                    is_static = True

                # return type
                rt_tok = self.expect(self.peek())
                rt = {"VOID_KW":"void","INT_KW":"int","BOOL_KW":"boolean"}[rt_tok.kind]

                idt = self.expect("IDENT")
                # params (copy parse_fn_decl logic)…
                self.expect("LPAREN")
                params = []
                if self.peek()!="RPAREN":
                    while True:
                        ptype = {"INT_KW":"int","BOOL_KW":"boolean"}[self.expect(self.peek()).kind]
                        pn = self.expect("IDENT")
                        params.append((pn.text,ptype))
                        if self.peek()=="COMMA":
                            self.next(); continue
                        break
                self.expect("RPAREN")

                # body
                self.expect("LBRACE")
                body = []
                while self.peek()!="RBRACE":
                    body.append(self.parse_stmt())
                self.expect("RBRACE")

                methods.append(self.ast.MethodDeclaration(
                    idt.text, params, rt, body, is_static,
                    pos=(rt_tok.line, rt_tok.col)
                ))

        self.expect("RBRACE")
        return self.ast.StructureDeclaration(
            name_tok.text, fields, methods,
            pos=(kw.line, kw.col)
        )



    def parse_function_declaration(self):
        # return-type
        tok_ret = self.expect(self.peek())
        rt = {"INT_KW":"int","BOOL_KW":"boolean","VOID_KW":"void"}[tok_ret.kind]
        # name
        name_tok = self.expect("IDENT")
        name = name_tok.text
        # params
        self.expect("LPAREN")
        params = []
        if self.peek() != "RPAREN":
            while True:
                ty = {"INT_KW":"int","BOOL_KW":"boolean"}[self.expect(self.peek()).kind]
                idt = self.expect("IDENT")
                params.append((idt.text, ty))
                if self.peek()=="COMMA":
                    self.expect("COMMA")
                    continue
                break
        self.expect("RPAREN")
        # body
        self.expect("LBRACE")
        body=[]
        while self.peek()!="RBRACE":
            body.append(self.parse_stmt())
        self.expect("RBRACE")
        return self.ast.FunctionDeclaration(name, params, rt, body, pos=(tok_ret.line,tok_ret.col))

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

