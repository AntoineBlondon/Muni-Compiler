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
            # function or constructor: return‐type could be VOID_KW|INT_KW|FLOAT_KW|BOOL_KW|IDENT
            if self.peek() == "IMPORT_KW":
                decls.append(self.parse_import_declaration())
                continue
            elif self._looks_like_function_decl():
                decls.append(self.parse_function_declaration())
            elif self.peek() == "ALIAS_KW":
                decls.append(self.parse_alias_declaration())
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
        
        # member‐assignment or reassignment: p.x = expr; p.x += expr;
        if kind == "IDENT" and self.tokens[self.pos+1].kind == "DOT":
            # look ahead for ASSIGN
            j = self.pos + 1
            while j < len(self.tokens) and self.tokens[j].kind == "DOT":
                if self.tokens[j+1].kind != "IDENT":
                    break
                j += 2
            if j < len(self.tokens) and self.tokens[j].kind in ("ASSIGN", "REASSIGN"):
                lhs = self.parse_primary()  # MemberAccess
                if self.peek() == "ASSIGN":
                    self.expect("ASSIGN")
                    rhs = self.parse_expr()
                    if semi: self.expect("SEMI")
                    return self.ast.MemberAssignment(lhs, lhs.field, rhs, pos=(tok.line, tok.col)) #type: ignore
                elif self.peek() == "REASSIGN":
                    op_text = self.expect("REASSIGN").text  # e.g. "+="
                    op = op_text[0]                         # '+', '-', '*', '/', '%'
                    rhs = self.parse_expr()
                    if semi: self.expect("SEMI")
                    # desugar: p.x += e  ==>  p.x = (p.x + e)
                    new_rhs = self.ast.BinOp(op, lhs, rhs)
                    return self.ast.MemberAssignment(lhs, lhs.field, new_rhs, pos=(tok.line, tok.col)) # type: ignore

        # plain assignment or reassignment: x = expr; x += expr;
        if kind == "IDENT" and self.tokens[self.pos+1].kind in ("ASSIGN", "REASSIGN"):
            return self.parse_assignment(tok, semi)

        # local declaration: int|boolean|void
        # local declaration: built-in or T or T<…>
        is_local_decl = False
        if kind in ("INT_KW", "FLOAT_KW","BOOL_KW","VOID_KW"):
            is_local_decl = True
        elif kind in ("IDENT"):
            # simple: IDENT name = …
            if (self.tokens[self.pos+1].kind == "IDENT" and
                self.tokens[self.pos+2].kind == "ASSIGN"):
                is_local_decl = True
            # generic: IDENT<…> name = …
            elif self.tokens[self.pos+1].kind == "LT":
                # skip to matching '>'
                j = self.pos + 2
                depth = 1
                while j < len(self.tokens) and depth > 0:
                    if self.tokens[j].kind == "LT":
                        depth += 1
                    elif self.tokens[j].kind == "GT":
                        depth -= 1
                    j += 1
                # now j points just past '>'
                if (j < len(self.tokens) and
                    self.tokens[j].kind == "IDENT" and
                    self.tokens[j+1].kind == "ASSIGN"):
                    is_local_decl = True
        if is_local_decl:
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
        if kind == "IDENT" and self.tokens[self.pos+1].kind in ("INCR", "DECR"):
            name_tok = self.expect("IDENT")
            op_tok   = self.next()  # INCR or DECR
            if semi: self.expect("SEMI")
            lvalue = self.ast.Ident(name_tok.text, pos=(name_tok.line, name_tok.col))
            return self._incdec_assignment_from_lvalue(
                lvalue, is_inc=(op_tok.kind=="INCR"), pos=(name_tok.line, name_tok.col)
            )
        
        # member postfix inc/dec: p.x++; p.y.z--;
        if kind == "IDENT" and self.tokens[self.pos+1].kind == "DOT":
            # Look ahead through .ident chains and check for INCR/DECR
            j = self.pos
            # parse a primary to reuse your existing chain logic
            save = self.pos
            try:
                lhs = self.parse_primary()  # should yield MemberAccess/Ident/MethodCall...
            finally:
                pass
            # If next token is INCR/DECR and lhs is an lvalue (Ident or MemberAccess):
            if self.peek() in ("INCR", "DECR") and isinstance(lhs, (self.ast.Ident, self.ast.MemberAccess)):
                op_tok = self.next()
                if semi: self.expect("SEMI")
                return self._incdec_assignment_from_lvalue(
                    lhs, is_inc=(op_tok.kind=="INCR"), pos=(tok.line, tok.col)
                )
            else:
                # not an inc/dec – rewind so other branches can parse this normally
                self.pos = save



        

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
        mod  = self.expect("IDENT").text
        self.expect("DOT")
        fn   = self.expect("IDENT").text
        self.expect("LPAREN")

        params: list = []
        if self.peek() != "RPAREN":
            while True:
                params.append(self.parse_type_expr())
                if self.peek() == "COMMA":
                    self.next()
                    continue
                break
        self.expect("RPAREN")
        self.expect("RARROW")

        ret_type = self.parse_type_expr()

        self.expect("SEMI")
        return self.ast.ImportDeclaration(
            module      = mod,
            name        = fn,
            params      = params,
            return_type = ret_type,
            pos         = (tok.line, tok.col)
        )

    def parse_alias_declaration(self):
        tok = self.expect("ALIAS_KW")
        name = self.expect("IDENT").text

        # optional generic parameters:
        type_params = []
        if self.peek() == "LT":
            self.next()
            while True:
                type_params.append(self.expect("IDENT").text)
                if self.peek()=="COMMA": self.next(); continue
                break
            self.expect("GT")

        self.expect("ASSIGN")
        aliased = self.parse_type_expr()
        self.expect("SEMI")
        return self.ast.AliasDeclaration(name, type_params, aliased, pos=(tok.line,tok.col))

    def parse_structure_declaration(self):
        kw       = self.expect("STRUCTURE_KW")
        name_tok = self.expect("IDENT")
        struct_name = name_tok.text

        struct_type_params: list[str] = []
        if self.peek() == "LT":
            # consume '<'
            self.next()
            while True:
                tp = self.expect("IDENT").text
                struct_type_params.append(tp)
                if self.peek() == "COMMA":
                    self.next()
                    continue
                break
            self.expect("GT")
        self.expect("LBRACE")

        fields, static_fields, methods = [], [], []
        while self.peek() != "RBRACE":

            # --- static field declarations ---
            if self.peek() == "STATIC_KW" and self.tokens[self.pos+3].kind == "ASSIGN":
                st_tok = self.next()  # STATIC_KW
                # parse the full type (could be generic)
                ty = self.parse_type_expr()
                name_tok = self.expect("IDENT")
                self.expect("ASSIGN")
                init = self.parse_expr()
                self.expect("SEMI")
                static_fields.append(
                    self.ast.StaticFieldDeclaration(
                        name_tok.text, ty, init,
                        pos=(ty.pos or (st_tok.line, st_tok.col))
                    )
                )
                continue

            # --- constructor: exactly IDENT==struct_name(...) plus optional <…> ---
            if self.peek() == "IDENT" and self.tokens[self.pos].text == struct_name:
                # look ahead past any <…> type‐args
                j = self.pos + 1
                if j < len(self.tokens) and self.tokens[j].kind == "LT":
                    depth = 1
                    j += 1
                    while j < len(self.tokens) and depth > 0:
                        if self.tokens[j].kind == "LT":
                            depth += 1
                        elif self.tokens[j].kind == "GT":
                            depth -= 1
                        j += 1
                # only if the very next token after <…> is '(' do we have a ctor
                if j < len(self.tokens) and self.tokens[j].kind == "LPAREN":
                    ctor_tok = self.next()   # consume struct_name
                    # optional ctor<…> TPs
                    ctor_type_params: list[str] = []
                    if self.peek() == "LT": 
                        self.next()
                        while True:
                            tp = self.expect("IDENT").text
                            ctor_type_params.append(tp)
                            if self.peek() == "COMMA":
                                self.next(); continue
                            break
                        self.expect("GT")

                    # now the parameter list
                    self.expect("LPAREN")
                    ctor_params = []
                    if self.peek() != "RPAREN":
                        while True:
                            p_ty   = self.parse_type_expr()
                            p_name = self.expect("IDENT").text
                            ctor_params.append((p_name, p_ty))
                            if self.peek() == "COMMA":
                                self.next(); continue
                            break   
                    self.expect("RPAREN")

                    # body
                    self.expect("LBRACE")
                    body = []
                    while self.peek() != "RBRACE":
                        body.append(self.parse_stmt())
                    self.expect("RBRACE")

                    ctor_ret = self.ast.TypeExpr(
                        struct_name,
                        [ self.ast.TypeExpr(tp) for tp in struct_type_params ]
                    )
                    # record it as a static method whose name == struct_name
                    methods.append(self.ast.MethodDeclaration(
                        struct_name,
                        ctor_type_params,
                        ctor_params,
                        ctor_ret,
                        body,
                        True,
                        pos=(ctor_tok.line, ctor_tok.col)
                    ))
                    continue

            # --- normal instance field:  <type> <name>; ---
            if self.peek() in ("INT_KW", "FLOAT_KW","BOOL_KW","IDENT"):
                # look‐ahead past any generic args to see if we really have
                #   <type> <name> ;
                j = self.pos + 1
                # if there's a '<', skip to its matching '>'
                if j < len(self.tokens) and self.tokens[j].kind == "LT":
                    depth = 1
                    j += 1
                    while j < len(self.tokens) and depth > 0:
                        if self.tokens[j].kind == "LT":
                            depth += 1
                        elif self.tokens[j].kind == "GT":
                            depth -= 1
                        j += 1
                # now we should be at the field‐name IDENT, followed by SEMI
                if j + 1 < len(self.tokens) and \
                self.tokens[j].kind == "IDENT" and \
                self.tokens[j+1].kind == "SEMI":
                    # yup, it's a field
                    ty = self.parse_type_expr()
                    name_tok = self.expect("IDENT")
                    self.expect("SEMI")
                    fields.append(self.ast.FieldDeclaration(
                        name_tok.text, ty, pos=(name_tok.line, name_tok.col)
                    ))
                    continue

            # --- methods (instance or static) ---
            is_static = False
            if self.peek() == "STATIC_KW":
                self.next()
                is_static = True

            # return type
            rt = self.parse_type_expr()
            # method name
            name_tok = self.expect("IDENT")

            # optional method<…> TPs
            method_type_params: list[str] = []
            if self.peek() == "LT":
                self.next()
                while True:
                    tp = self.expect("IDENT").text
                    method_type_params.append(tp)
                    if self.peek() == "COMMA":
                        self.next(); continue
                    break
                self.expect("GT")

            # param list
            self.expect("LPAREN")
            m_params = []
            if self.peek() != "RPAREN":
                while True:
                    p_ty   = self.parse_type_expr()
                    p_name = self.expect("IDENT").text
                    m_params.append((p_name, p_ty))
                    if self.peek() == "COMMA":
                        self.next(); continue
                    break
            self.expect("RPAREN")

            # body
            self.expect("LBRACE")
            body = []
            while self.peek() != "RBRACE":
                body.append(self.parse_stmt())
            self.expect("RBRACE")

            methods.append(self.ast.MethodDeclaration(
                name_tok.text,
                method_type_params,
                m_params,
                rt,
                body,
                is_static,
                pos=(name_tok.line, name_tok.col)
            ))
            continue

        # close the struct
        self.expect("RBRACE")
        return self.ast.StructureDeclaration(
            struct_name,
            struct_type_params,
            fields,
            static_fields,
            methods,
            pos=(kw.line, kw.col)
        )


    def parse_function_declaration(self):
        # --- speculative lookahead so we only commit if this truly is a function decl ---
        start_pos = self.pos
        first_tok = self.peek_token()
        try:
            # try to parse a return type (handles IDENT<...> too)
            self.parse_type_expr()
            # must have a function name next
            if self.peek() != "IDENT":
                raise SyntaxError(f"{first_tok.line}:{first_tok.col}: expected function name after return type")
            # and then either generic type params "<...>" or a parameter list "("
            if self.pos + 1 >= len(self.tokens):
                raise SyntaxError(f"{first_tok.line}:{first_tok.col}: unexpected EOF after function name")
            nxt = self.tokens[self.pos + 1].kind
            if nxt not in ("LT", "LPAREN"):
                raise SyntaxError(f"{first_tok.line}:{first_tok.col}: expected '<' or '(' after function name")
        finally:
            # reset so we can actually parse and build the AST nodes
            self.pos = start_pos

        # --- real parse begins here ---
        return_type = self.parse_type_expr()

        name_tok = self.expect("IDENT")
        function_name = name_tok.text

        # optional generic type parameters on the function itself: foo<T,U>(...)
        type_params: list[str] = []
        if self.peek() == "LT":
            self.next()  # consume '<'
            while True:
                type_params.append(self.expect("IDENT").text)
                if self.peek() == "COMMA":
                    self.next(); continue
                break
            self.expect("GT")

        # parameters
        self.expect("LPAREN")
        params = []
        if self.peek() != "RPAREN":
            while True:
                pty = self.parse_type_expr()
                pname = self.expect("IDENT").text
                params.append((pname, pty))
                if self.peek() == "COMMA":
                    self.next(); continue
                break
        self.expect("RPAREN")

        # body
        self.expect("LBRACE")
        body = []
        while self.peek() != "RBRACE":
            body.append(self.parse_stmt())
        self.expect("RBRACE")

        return self.ast.FunctionDeclaration(
            function_name, type_params, params, return_type, body,
            pos=(first_tok.line, first_tok.col)
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
        # tok_ident is the IDENT token already peeked by caller
        name = tok_ident.text
        self.expect("IDENT")
        if self.peek() == "ASSIGN":
            self.next()
            expr = self.parse_expr()
            if semi: self.expect("SEMI")
            return self.ast.VariableAssignment(name, expr, pos=(tok_ident.line, tok_ident.col))
        elif self.peek() == "REASSIGN":
            op_text = self.next().text  # "+=", "-=", ...
            op = op_text[0]
            rhs = self.parse_expr()
            if semi: self.expect("SEMI")
            # desugar: x += e  ==>  x = (x + e)
            left_ident = self.ast.Ident(name, pos=(tok_ident.line, tok_ident.col))
            new_rhs = self.ast.BinOp(op, left_ident, rhs)
            return self.ast.VariableAssignment(name, new_rhs, pos=(tok_ident.line, tok_ident.col))
        else:
            raise SyntaxError(f"{tok_ident.line}:{tok_ident.col}: Expected ASSIGN or REASSIGN")


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

        # integer literal
        if kind == "INT":
            self.next()
            return self.ast.IntLiteral(text, pos=(line,col))

        # float literal
        if kind == "FLOAT":
            self.next()
            return self.ast.FloatLiteral(text, pos=(line,col))

        # boolean literal
        if kind == "TRUE":
            self.next()
            return self.ast.BooleanLiteral(True, pos=(line,col))
        if kind == "FALSE":
            self.next()
            return self.ast.BooleanLiteral(False, pos=(line,col))

        # --- array‐literal sugar: [ e1, e2, … ] ---
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
           return self.ast.ArrayLiteral(elems, pos=(line,col))

        if kind == "NULL_KW":
            self.next()
            return self.ast.NullLiteral(pos=(line,col))
        
        if kind == "CHAR":
            self.next()
            return self.ast.CharLiteral(text, pos=(line,col))
        
        if kind == "STRING":
            self.next()
            return self.ast.StringLiteral(text, pos=(line,col))

        # identifier or function‐call
        if kind in ("IDENT"):
            name = text
            self.next()
            # call‐lookahead
            type_args = []
            is_function = True
            save = self.pos
            if self.peek() == "LT":
                self.next()
                while True:
                    try: 
                        type_args.append(self.parse_type_expr())
                        if self.peek()=="COMMA":
                            self.next(); continue
                        break
                    except:
                        is_function = False
                        break
                if is_function:
                    try: 
                        self.expect("GT")
                    except:
                        is_function = False
            if self.peek() == "LPAREN" and is_function:
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
                self.pos = save
                node = self.ast.Ident(name, pos=(line,col))

            save = self.pos
            if self.peek()=="LT" and self._looks_like_static_generic():
                # parse struct‐type‐args
                struct_args = []
                is_method = True
                self.next()
                while True:
                    struct_args.append(self.parse_type_expr())
                    if self.peek()=="COMMA": self.next(); continue
                    break
                try:
                    self.expect("GT")
                except:
                    is_method = False
                if self.peek()=="DOT" and self.tokens[self.pos+1].kind=="IDENT" and self.tokens[self.pos+2].kind=="LPAREN" and is_method:
                    # consume the dot
                    self.next()
                    
                    method_name = self.expect("IDENT").text
                    # optional <…> on the method itself
                    method_args = []
                    if self.peek()=="LT":
                        self.next()
                        while True:
                            method_args.append(self.parse_type_expr())
                            if self.peek()=="COMMA": self.next(); continue
                            break
                        self.expect("GT")
                    # now the call parens
                    self.expect("LPAREN")
                    call_args = []
                    if self.peek()!="RPAREN":
                        while True:
                            call_args.append(self.parse_expr())
                            if self.peek()=="COMMA": self.next(); continue
                            break
                    self.expect("RPAREN")

                    # rebuild as a single MethodCall whose receiver is the *type* Ident
                    all_targs = struct_args + method_args
                    return self.ast.MethodCall(
                        self.ast.Ident(node.name, pos=node.pos),
                        all_targs,
                        method_name,
                        call_args,
                        pos=node.pos
                    )
            # if it didn’t match, roll back
            self.pos = save

            # 1) any number of “.field” or “.method(...)”
            while self.peek() == "DOT":
                self.next()  # consume '.'
                name = self.expect("IDENT").text
                type_args = []
                if self.peek() == "LT" and self._looks_like_generic():
                    self.next()
                    while True:
                        try: 
                            type_args.append(self.parse_type_expr())
                            if self.peek()=="COMMA":
                                self.next(); continue
                            break
                        except:
                            is_function = False
                            break
                    try:
                        self.expect("GT")
                    except:
                        is_function = False

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
                    node = self.ast.MethodCall(node, type_args, name, args, pos=(line,col))
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

        if self.peek() in ["INT_KW", "FLOAT_KW", "VOID_KW", "BOOL_KW"]:
            name = {"INT_KW": "int", "FLOAT_KW": "float", "VOID_KW": "void", "BOOL_KW": "boolean"}[self.next().kind]
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

    def _looks_like_static_generic(self):
        # starting at self.pos, we should see:
        #   LT, … matching GT, DOT, IDENT, LPAREN
        depth = 0
        i = self.pos
        while i < len(self.tokens):
            if self.tokens[i].kind == "LT":
                depth += 1
            elif self.tokens[i].kind == "GT":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        # now `i` points at the '>'
        return (
            depth == 0 and
            i+3 < len(self.tokens) and
            self.tokens[i+1].kind == "DOT" and
            self.tokens[i+2].kind == "IDENT" and
            self.tokens[i+3].kind == "LPAREN"
        )
    def _looks_like_generic(self):
        # starting at a '<', scan forward to its matching '>'
        depth = 0
        for i in range(self.pos, len(self.tokens)):
            if self.tokens[i].kind == "LT":
                depth += 1
            elif self.tokens[i].kind == "GT":
                depth -= 1
                if depth == 0:
                    # now i points at the '>'
                    return i + 1 < len(self.tokens) and \
                           self.tokens[i+1].kind == "LPAREN"
        return False


    def _looks_like_function_decl(self) -> bool:
        save = self.pos
        try:
            # Must be able to parse a type expression at the start
            if self.peek() not in ("VOID_KW", "INT_KW", "FLOAT_KW", "BOOL_KW", "IDENT"):
                return False

            self.parse_type_expr()             # consume the return type (handles nested <...>)
            if self.peek() != "IDENT":         # must have function name
                return False

            # look one past the name: either '<' (generic TPs) or '(' (params)
            if self.pos + 1 >= len(self.tokens):
                return False
            nxt = self.tokens[self.pos + 1].kind
            return nxt in ("LT", "LPAREN")
        except Exception:
            return False
        finally:
            self.pos = save

    def _incdec_assignment_from_lvalue(self, lvalue_node, is_inc: bool, pos):
        one = self.ast.IntLiteral("1", pos=pos)
        op  = "+" if is_inc else "-"

        if isinstance(lvalue_node, self.ast.Ident):
            # x++  ->  x = x + 1
            rhs = self.ast.BinOp(op, self.ast.Ident(lvalue_node.name, pos=lvalue_node.pos), one)
            return self.ast.VariableAssignment(lvalue_node.name, rhs, pos=pos)

        if isinstance(lvalue_node, self.ast.MemberAccess):
            # p.x++  ->  p.x = p.x + 1
            rhs = self.ast.BinOp(op,
                                self.ast.MemberAccess(lvalue_node.obj, lvalue_node.field, pos=lvalue_node.pos),
                                one)
            return self.ast.MemberAssignment(lvalue_node.obj, lvalue_node.field, rhs, pos=pos)

        raise SyntaxError(f"{pos[0]}:{pos[1]}: ++/-- requires an assignable lvalue")
