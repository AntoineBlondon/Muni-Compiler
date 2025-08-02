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
            if self.peek() == "IMPORT_KW":
                decls.append(self.parse_import_declaration())
                continue
            elif ((self.peek() in ("VOID_KW","INT_KW","BOOL_KW") or self.peek()=="IDENT")
                    and self.tokens[self.pos+1].kind=="IDENT"
                    and self.tokens[self.pos+2].kind in ("LT","LPAREN")):
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

        # local declaration: int|boolean|void
        if kind in ["INT_KW", "BOOL_KW", "VOID_KW"] or (kind == "IDENT"
            and self.tokens[self.pos+1].kind == "IDENT"
            and self.tokens[self.pos+2].kind == "ASSIGN"):
            first_tok = self.peek_token()
            declaration_type = self.parse_type_expr()
            name_tok = self.expect("IDENT")
            self.expect("ASSIGN")
            expr = self.parse_expr()
            if semi: self.expect("SEMI")
            return self.ast.VariableDeclaration(
                declaration_type, name_tok.text, expr,
                pos=(first_tok.line, first_tok.col)
            )


        

        # fallback: any other expression as statement
        expr = self.parse_expr()
        if semi: self.expect("SEMI")
        return expr
    
    def parse_import_declaration(self):
        tok = self.expect("IMPORT_KW")
        # --- source-file import ---
        if self.peek() == "LT":
            self.expect("LT")
            path = ""
            while self.peek() != "GT":
                path += self.next().text
            self.expect("GT")
            self.expect("SEMI")
            return self.ast.ImportDeclaration(source=path, pos=(tok.line,tok.col))

        # --- host import:  module.name(params…) -> retType; ---
        mod = self.expect("IDENT").text
        self.expect("DOT")
        function_name  = self.expect("IDENT").text
        self.expect("LPAREN")
        params = []
        if self.peek() != "RPAREN":
            while True:
                # allow INT_KW|BOOL_KW|VOID_KW or IDENT (for structs)
                pk = self.peek()
                if pk in ("INT_KW","BOOL_KW","VOID_KW"):
                    t = self.next().kind
                    params.append(self.ast.TypeExpr({"INT_KW":"int","BOOL_KW":"boolean","VOID_KW":"void"}[t]))
                elif pk == "IDENT":
                    params.append(self.ast.TypeExpr(self.next().text))
                else:
                    p = self.peek_token()
                    raise SyntaxError(f"{p.line}:{p.col}: Unexpected type {pk}")
                if self.peek()=="COMMA":
                    self.next(); continue
                break
        self.expect("RPAREN")
        self.expect("RARROW")
        # return‐type
        rt_kind = self.peek()
        if rt_kind in ("INT_KW","BOOL_KW","VOID_KW"):
            rt = self.ast.TypeExpr({"INT_KW":"int","BOOL_KW":"boolean","VOID_KW":"void"}[self.next().kind])
        elif rt_kind == "IDENT":
            rt = self.ast.TypeExpr(self.next().text)
        else:
            p = self.peek_token()
            raise SyntaxError(f"{p.line}:{p.col}: Unexpected return type {rt_kind}")
        self.expect("SEMI")
        return self.ast.ImportDeclaration(
            module=mod, name=function_name,
            params=params,
            return_type=rt,
            pos=(tok.line, tok.col)
        )

    def parse_structure_declaration(self):
        kw       = self.expect("STRUCTURE_KW")
        name_tok = self.expect("IDENT")
        struct_name = name_tok.text
        self.expect("LBRACE")

        fields, static_fields, methods = [], [], []
        while self.peek() != "RBRACE":

            # --- static field? ---
            if self.peek()=="STATIC_KW" and self.tokens[self.pos+3].kind=="ASSIGN":
                st_tok = self.next()                         # STATIC_KW
                # parse type (INT_KW|BOOL_KW|IDENT)
                if self.peek() in ("INT_KW","BOOL_KW"):
                    ty_tok = self.next()
                    ty = self.ast.TypeExpr("int") if ty_tok.kind=="INT_KW" else self.ast.TypeExpr("boolean")
                elif self.peek()=="IDENT":
                    ty_tok = self.next()
                    ty = self.ast.TypeExpr(ty_tok.text)
                else:
                    t = self.peek_token()
                    raise SyntaxError(f"{t.line}:{t.col}: Unexpected static‐field type {self.peek()}")
                name_tok = self.expect("IDENT")
                self.expect("ASSIGN")
                init = self.parse_expr()
                self.expect("SEMI")
                static_fields.append(
                    self.ast.StaticFieldDeclaration(name_tok.text, ty, init, # type: ignore
                                                    pos=(ty_tok.line,ty_tok.col))
                )
                continue
            # --- constructor?  IDENT == struct_name + LPAREN ---
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
                            self.next(); p_ty=self.ast.TypeExpr("int")
                        elif pk == "BOOL_KW":
                            self.next(); p_ty=self.ast.TypeExpr("boolean")
                        elif pk == "IDENT":
                            p_tok = self.next(); p_ty = self.ast.TypeExpr(p_tok.text)
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

            # --- ordinary field? type can be int, boolean or any struct IDENT ---
            if (self.peek() in ("INT_KW","BOOL_KW","IDENT")
                and self.tokens[self.pos+2].kind == "SEMI"):
                tok_type = self.next()
                if tok_type.kind == "INT_KW":
                    field_type = self.ast.TypeExpr("int")
                elif tok_type.kind == "BOOL_KW":
                    field_type = self.ast.TypeExpr("boolean")
                else:
                    # user‐defined struct
                    field_type = self.ast.TypeExpr(tok_type.text)
                idt = self.expect("IDENT")
                self.expect("SEMI")
                fields.append(self.ast.FieldDeclaration(
                    idt.text, field_type,
                    pos=(tok_type.line, tok_type.col)
                ))
                continue


            # --- method (static or instance) ---
            is_static = False
            if self.peek() == "STATIC_KW":
                self.next()
                is_static = True

            # parse return type: void|int|boolean or a user‐defined struct name
            tok = self.peek()
            if tok in ("VOID_KW","INT_KW","BOOL_KW"):
                rt_tok = self.next()
                rt = self.ast.TypeExpr({"VOID_KW":"void","INT_KW":"int","BOOL_KW":"boolean"}[rt_tok.kind])
            elif tok == "IDENT":
                rt_tok = self.next()
                rt = self.ast.TypeExpr(rt_tok.text)
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
                        ptype = self.ast.TypeExpr({"INT_KW":"int","BOOL_KW":"boolean","VOID_KW":"void"}[p_tok.kind])
                    # struct type
                    elif kind == "IDENT":
                        p_tok = self.next()
                        ptype = self.ast.TypeExpr(p_tok.text)
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
                idt.text, params, rt, body, is_static, # type: ignore
                pos=(rt_tok.line, rt_tok.col)
            ))


        self.expect("RBRACE")
        return self.ast.StructureDeclaration(
            struct_name, fields, static_fields, methods,
            pos=(kw.line, kw.col)
        )

    def parse_function_declaration(self):
        # return type: VOID_KW|INT_KW|BOOL_KW|IDENT
        first_tok = self.peek_token()
        return_type = self.parse_type_expr()

        name_tok = self.expect("IDENT")
        function_name = name_tok.text

        type_params = []
        if self.peek() == "LT":
            self.next()  # consume '<'
            while True:
                tok = self.expect("IDENT")
                type_params.append(tok.text)
                if self.peek()=="COMMA":
                    self.next()
                    continue
                break
            self.expect("GT")

        # params
        self.expect("LPAREN")
        params = []
        if self.peek() != "RPAREN":
            while True:
                parameter_type = self.parse_type_expr()
                parameter_name = self.expect("IDENT").text
                params.append((parameter_name, parameter_type))
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
            function_name, type_params, params, return_type, body, pos=(first_tok.line, first_tok.col)
        )



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
        type_args = []
        if self.peek() == "LT":
            self.next()
            while True:
                type_args.append(self.parse_type_expr())
                if self.peek()=="COMMA":
                    self.next(); continue
                break
            self.expect("GT")
        self.expect("LPAREN")
        args=[]
        if self.peek()!="RPAREN":
            while True:
                args.append(self.parse_expr())
                if self.peek()=="COMMA":
                    self.expect("COMMA"); continue
                break
        self.expect("RPAREN")
        return self.ast.FunctionCall(name_tok.text, type_args, args, pos=(name_tok.line,name_tok.col))


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
            self.peek() in ["OP", "LT", "GT"] and 
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

        # --- list‐literal sugar: [ e1, e2, … ] ---
        if kind == "LBRACK":
           self.next()  # consume “[”
           elems = []
           if self.peek() != "RBRACK":
               while True:
                   elems.append(self.parse_expr())
                   if self.peek() == "COMMA":
                       self.next(); continue
                   break
           self.expect("RBRACK")
           return self.ast.ListLiteral(elems, pos=(line,col))

        if kind == "NULL_KW":
            self.next()
            return self.ast.NullLiteral(pos=(line,col))

        # identifier or function‐call
        if kind == "IDENT":
            name = text
            self.next()
            # call‐lookahead
            type_args = []
            if self.peek() == "LT":
                self.next()
                while True:
                    type_args.append(self.parse_type_expr())
                    if self.peek()=="COMMA":
                        self.next(); continue
                    break
                self.expect("GT")
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
                node = self.ast.FunctionCall(name, type_args, args, pos=(line,col))
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

    def parse_type_expr(self):
        # caller must have peek()=="IDENT"
        if self.peek() in ["INT_KW", "VOID_KW", "BOOL_KW"]:
            name = {"INT_KW": "int", "VOID_KW": "void", "BOOL_KW": "boolean"}[self.next().kind]
            return self.ast.TypeExpr(name)
        else:
            tok = self.expect("IDENT")
            name = tok.text
            params = []
            if self.peek() == "LT":           # '<'
                self.next()
                while True:
                    params.append(self.parse_type_expr())
                    if self.peek()=="COMMA":
                        self.next(); continue
                    break
                self.expect("GT")            # '>'
            return self.ast.TypeExpr(name, params, pos=(tok.line,tok.col))
