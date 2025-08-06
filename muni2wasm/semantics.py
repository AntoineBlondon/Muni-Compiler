from .ast import (
    AliasDeclaration,
    Program,
    FunctionDeclaration,
    FunctionCall,
    ReturnStmt,
    VariableDeclaration,
    VariableAssignment,
    IfStmt,
    ForStmt,
    WhileStmt,
    UntilStmt,
    DoStmt,
    BreakStmt,
    ContinueStmt,
    BinOp,
    UnaryOp,
    Number,
    BooleanLiteral,
    Ident,
    StructureDeclaration,
    MemberAccess,
    MemberAssignment,
    MethodCall,
    NullLiteral,
    ArrayLiteral,
    ImportDeclaration,
    TypeExpr,
    FieldDeclaration,
    MethodDeclaration,
)

class SemanticError(Exception):
    def __init__(self, message, pos=None):
        super().__init__(message)
        self.message = message
        self.pos     = pos

    def __str__(self):
        if self.pos:
            return f"{self.pos[0]}:{self.pos[1]}: {self.message}"
        return self.message





class SemanticChecker:
    def __init__(self, program: Program):
        self.program = program
        self.func_sigs = {}
        self.struct_templates = {}
        self.alias_map = {}

        self.structs: dict[TypeExpr, StructureDeclaration] = {}
        self.generic_functions = {}
        self.checked_func_insts = set()
        self.checked_struct_insts = set()

    def check(self):
        self.decompose_program()

        for struct_decl in self.struct_decls:
            name = struct_decl.name
            if name in self.struct_templates:
                raise SemanticError(f"Redefinition of structure '{name}'", struct_decl.pos)
            self.struct_templates[name] = (
                struct_decl.type_params,
                struct_decl
            )

        self.define_array()

        self.validate_struct_templates()

        self.build_global_function_signatures()

        for struct_name, (tparams, _) in self.struct_templates.items():
            placeholder_args = [TypeExpr(param) for param in tparams]
            self.instantiate_struct(struct_name, placeholder_args)
        
        for (struct_name, type_args) in list(self.checked_struct_insts):
            self.instantiate_struct(struct_name, list(type_args))
        
        if "main" in self.func_sigs and self.top_stmts:
            raise SemanticError("Top-level statements not allowed when 'main' is defined", self.top_stmts[0].pos)
        if self.top_stmts and "main" not in self.func_sigs:
            self.check_block(self.top_stmts, {}, expected_ret=TypeExpr("void"), in_loop=False)
        
        for fd in self.func_decls:
            if fd.type_params:
                continue
            sym = { name: ty for name,ty in fd.params }
            self.check_block(fd.body, sym, expected_ret=fd.return_type, in_loop=False)

            # ensure non-void returns on every path
            

            if fd.return_type != TypeExpr("void") and not self.block_returns(fd.body):
                raise SemanticError(f"Function '{fd.name}' may exit without returning a value", fd.pos)

    def decompose_program(self):
        self.imports = [d for d in self.program.decls if isinstance(d, ImportDeclaration)]
        self.func_decls = [d for d in self.program.decls if isinstance(d, FunctionDeclaration)]
        self.struct_decls = [d for d in self.program.decls if isinstance(d, StructureDeclaration)]
        self.raw_aliases = [d for d in self.program.decls if isinstance(d, AliasDeclaration)]
        self.top_stmts = [
            d for d in self.program.decls
            if not isinstance(d, (ImportDeclaration, FunctionDeclaration, StructureDeclaration, AliasDeclaration))
        ]

        self.alias_map = {
            alias.name: (alias.type_params, alias.aliased)
            for alias in self.raw_aliases
        }


        self.expand_aliases()

        self.program.decls = [
            d for d in self.program.decls
            if not isinstance(d, AliasDeclaration)
        ]
    
    def expand_aliases(self):
        for d in self.program.decls:
            if isinstance(d, FunctionDeclaration):
                d.return_type = self.resolve_alias(d.return_type)
                for i, (n, pty) in enumerate(d.params):
                    d.params[i] = (n, self.resolve_alias(pty))

            elif isinstance(d, StructureDeclaration):
                for f in d.fields:
                    f.type = self.resolve_alias(f.type)
                for sf in d.static_fields:
                    sf.type = self.resolve_alias(sf.type)
                for m in d.methods:
                    m.return_type = self.resolve_alias(m.return_type)
                    for j, (n, pty) in enumerate(m.params):
                        m.params[j] = (n, self.resolve_alias(pty))
        for fd in self.func_decls:
            for stmt in fd.body:
                self.rewrite_types_in_stmt(stmt)
        for stmt in self.top_stmts:
            self.rewrite_types_in_stmt(stmt)

    def rewrite_types_in_stmt(self, stmt):
        # if this is a local var decl, rewrite its declared type:
        if isinstance(stmt, VariableDeclaration):
            stmt.type = self.resolve_alias(stmt.type)

        # now recurse through any child‐statements:
        for child_list in (
        getattr(stmt, "body", []),
        getattr(stmt, "then_stmts", []),
        getattr(stmt, "else_stmts", []),
        getattr(stmt, "else_body", []),
        [stmt.init]   if hasattr(stmt, "init")   and stmt.init   else [],
        [stmt.cond]   if hasattr(stmt, "cond")   and stmt.cond   else [],
        [stmt.post]   if hasattr(stmt, "post")   and stmt.post   else [],
        [stmt.count]  if hasattr(stmt, "count")  and stmt.count  else [],
        ):
            for s in child_list:
                self.rewrite_types_in_stmt(s)
        
    
    def define_array(self):
        array_struct_decl = StructureDeclaration(
            name="array",
            type_params=["T"],
            fields=[
                FieldDeclaration(name="length", type=TypeExpr("int")),
                FieldDeclaration(name="buffer", type=TypeExpr("T"))
            ],
            static_fields=[],
            methods=[
                MethodDeclaration(
                    name="array",
                    type_params=[],
                    params=[("length", TypeExpr("int"))],
                    return_type=TypeExpr("array", [TypeExpr("T")]),
                    body=[],           # empty body
                    is_static=True,
                    pos=None
                ),
                MethodDeclaration(
                    name="get",
                    type_params=[],
                    params=[("index", TypeExpr("int"))],
                    return_type=TypeExpr("T"),
                    body=[],
                    is_static=False,
                    pos=None
                ),
                MethodDeclaration(
                    name="set",
                    type_params=[],
                    params=[("index", TypeExpr("int")), ("value", TypeExpr("T"))],
                    return_type= TypeExpr("void"),
                    body=[],
                    is_static=False,
                    pos=None
                )
            ]
        )
        self.struct_decls.append(array_struct_decl)
        self.struct_templates["array"] = (["T"], array_struct_decl)
        self.structs[TypeExpr("array")] = array_struct_decl

    def check_type_with_scope(self, typ: TypeExpr, scope_type_vars: set[str]):
        # bare var
        if not typ.params and typ.name in scope_type_vars:
            return
        # built-in
        if typ.name in ("int", "boolean", "void"):
            if typ.params:
                raise SemanticError(f"Type '{typ}' may not have parameters", typ.pos)
            return
        # struct instantiation
        if typ.name in self.struct_templates:
            # correct number of params?
            needed = len(self.struct_templates[typ.name][0])
            if len(typ.params) != needed:
                raise SemanticError(
                    f"Type '{typ.name}' expects {needed} parameter(s), got {len(typ.params)}",
                    typ.pos
                )
            # recurse
            for sub in typ.params:
                self.check_type_with_scope(sub, scope_type_vars)
            return
        raise SemanticError(f"Unknown type '{typ}'", typ.pos)

    def validate_struct_templates(self):
        for struct_name, (type_params, struct_decl) in self.struct_templates.items():
            # static fields
            for static_field in struct_decl.static_fields:
                if not isinstance(static_field.expr, (Number, BooleanLiteral)):
                    raise SemanticError(f"Static field '{static_field.name}' in structure '{struct_name}' must be a constant expression", static_field.pos)
                if expr_type := self.infer(static_field.expr, {}, {}, {}) != static_field.type:
                    raise SemanticError(
                        f"Cannot assign {expr_type} to static {static_field.type} '{static_field.name}'",
                        static_field.pos
                    )

            # normal fields
            for field in struct_decl.fields:
                type_name = field.type.name
                if type_name not in ("int", "boolean") and type_name not in type_params:
                    if type_name not in self.struct_templates:
                        raise SemanticError(f"Undefined type '{type_name}' in structure '{struct_name}'", field.pos)

            # methods
            for method in struct_decl.methods:
                scope_vars = set(type_params) | set(method.type_params)
                self.check_type_with_scope(method.return_type, scope_vars)
                for _, param_type in method.params:
                    self.check_type_with_scope(param_type, scope_vars)

    def build_global_function_signatures(self):
        for imp in self.imports:
            if imp.name in self.func_sigs:
                raise SemanticError(f"Redefinition of function '{imp.name}'", imp.pos)
            self.func_sigs[imp.name] = (imp.type_params, imp.params, imp.return_type)

        for function_declaration in self.func_decls:
            if function_declaration.name in self.func_sigs:
                raise SemanticError(f"Redefinition of function '{function_declaration.name}'", function_declaration.pos)
            self.func_sigs[function_declaration.name] = (
                function_declaration.type_params, # TODO check
                function_declaration.params,
                function_declaration.return_type
            )
        self.generic_functions = { f.name for f in self.func_decls if f.type_params }

    def subst(self, ty: TypeExpr, substitution_map: dict[str, TypeExpr]) -> TypeExpr:
        if not ty.params and ty.name in substitution_map:
            return substitution_map[ty.name]
        return TypeExpr(ty.name, [self.subst(c, substitution_map) for c in ty.params])

    def instantiate_struct(self, name: str, args: list[TypeExpr]):
        key = (name, tuple(args))
        if key in self.checked_struct_insts:
            return
        self.checked_struct_insts.add(key)

        type_params, struct_declaration = self.struct_templates[name]

        sub_map = dict(zip(type_params, args))

        self.structs[TypeExpr(name, list(args))] = struct_declaration


        for method in struct_declaration.methods:

            symbol_table = {}
            symbol_table["this"] = TypeExpr(name, args)
            for param_name, param_type in method.params:
                symbol_table[param_name] = self.subst(param_type, sub_map)

            self.check_block(method.body, symbol_table,
                            expected_ret=   TypeExpr(name, args)
                                            if method.is_static and method.name == name
                                            else self.subst(method.return_type, sub_map),
                            in_loop=False,
                            struct_subst=sub_map,
                            method_subst={})

    def check_block(self, stmts: list, symbol_table: dict,
                    expected_ret: TypeExpr,
                    in_loop: bool,
                    struct_subst: dict[str,TypeExpr]={},
                    method_subst: dict[str,TypeExpr]={}):
        map_subst = {**method_subst, **struct_subst}
        for stmt in stmts:
            pos = getattr(stmt, "pos", None)

            if isinstance(stmt, VariableDeclaration):
                if stmt.name in symbol_table:
                    raise SemanticError(f"Redeclaration of '{stmt.name}'", pos)
                if stmt.type == TypeExpr("void"):
                    if stmt.expr is not None:
                        raise SemanticError(f"Cannot initialize void variable '{stmt.name}'", pos)
                    symbol_table[stmt.name] = TypeExpr("void")
                else:
                    if stmt.expr is None:
                        raise SemanticError(f"Missing initializer for '{stmt.name}'", pos)
                    rt = self.subst(self.infer(stmt.expr, symbol_table, method_subst, struct_subst), map_subst)
                    lhs_t = self.subst(stmt.type, map_subst)
                    if not (rt == lhs_t or (rt == TypeExpr("*") and lhs_t in self.structs)):
                        raise SemanticError(f"Cannot assign {rt} to {lhs_t} '{stmt.name}'", pos)
                    symbol_table[stmt.name] = lhs_t
                continue

            if isinstance(stmt, VariableAssignment):
                if stmt.name not in symbol_table:
                    raise SemanticError(f"Assignment to undefined '{stmt.name}'", pos)
                lt = symbol_table[stmt.name]
                rt = self.subst(self.infer(stmt.expr, symbol_table, method_subst, struct_subst), map_subst)
                if not (rt == lt or (rt == TypeExpr("*") and lt in self.structs)):
                    raise SemanticError(f"Cannot assign {rt} to {lt} '{stmt.name}'", pos)
                continue

            if isinstance(stmt, MemberAssignment):
                lhs_t = self.subst(self.infer(stmt.obj, symbol_table, method_subst, struct_subst), map_subst)
                
                if getattr(stmt.obj, "is_static_field", False):
                    raise SemanticError(f"Cannot assign to static field '{stmt.field}'", stmt.pos)
                
                rt = self.subst(self.infer(stmt.expr, symbol_table, method_subst, struct_subst), map_subst)
                if not (rt == lhs_t or (rt == TypeExpr("*") and lhs_t in self.structs)):
                    raise SemanticError(
                        f"Cannot assign {rt} to field '{stmt.obj.field}' of type {lhs_t}",
                        pos
                    )
                continue

            if isinstance(stmt, IfStmt):
                ct = self.infer(stmt.cond, symbol_table, method_subst, struct_subst)
                if ct != TypeExpr("boolean"):
                    raise SemanticError(f"Condition of if must be boolean, got {ct}", stmt.cond.pos)
                sym = symbol_table.copy()
                self.check_block(stmt.then_stmts, sym, expected_ret, in_loop, struct_subst, method_subst)
                self.check_block(stmt.else_stmts, sym, expected_ret, in_loop, struct_subst, method_subst)
                continue

            if isinstance(stmt, ForStmt):
                backup = symbol_table.copy()
                if stmt.init:
                    self.check_block([stmt.init], symbol_table, expected_ret, in_loop, struct_subst, method_subst)
                ct = self.infer(stmt.cond, symbol_table, method_subst, struct_subst) if stmt.cond else TypeExpr("boolean")
                if stmt.cond and ct != TypeExpr("boolean"):
                    raise SemanticError(f"Condition of for must be boolean, got {ct}", stmt.cond.pos)
                if stmt.post:
                    self.check_block([stmt.post], symbol_table, expected_ret, in_loop, struct_subst, method_subst)
                self.check_block(stmt.body, symbol_table, expected_ret, True, struct_subst, method_subst)
                self.check_block(stmt.else_body, symbol_table, expected_ret, in_loop, struct_subst, method_subst)
                symbol_table.clear(); symbol_table.update(backup)
                continue

            if isinstance(stmt, WhileStmt):
                ct = self.infer(stmt.cond, symbol_table, method_subst, struct_subst)
                if ct != TypeExpr("boolean"):
                    raise SemanticError(f"Condition of while must be boolean, got {ct}", stmt.cond.pos)
                backup = symbol_table.copy()
                self.check_block(stmt.body, symbol_table, expected_ret, True, struct_subst, method_subst)
                self.check_block(stmt.else_body, symbol_table, expected_ret, in_loop, struct_subst, method_subst)
                symbol_table.clear(); symbol_table.update(backup)
                continue

            if isinstance(stmt, UntilStmt):
                ct = self.infer(stmt.cond, symbol_table, method_subst, struct_subst)
                if ct != TypeExpr("boolean"):
                    raise SemanticError(f"Condition of until must be boolean, got {ct}", stmt.cond.pos)
                backup = symbol_table.copy()
                self.check_block(stmt.body, symbol_table, expected_ret, True, struct_subst, method_subst)
                self.check_block(stmt.else_body, symbol_table, expected_ret, in_loop, struct_subst, method_subst)
                symbol_table.clear(); symbol_table.update(backup)
                continue

            if isinstance(stmt, DoStmt):
                if stmt.count is not None:
                    ct = self.infer(stmt.count, symbol_table, method_subst, struct_subst)
                    if ct != TypeExpr("int"):
                        raise SemanticError(f"Count in do‐repeat must be int, got {ct}", stmt.count.pos)
                backup = symbol_table.copy()
                self.check_block(stmt.body, symbol_table, expected_ret, True, struct_subst, method_subst)
                if stmt.cond is not None:
                    ct = self.infer(stmt.cond, symbol_table, method_subst, struct_subst)
                    if ct != TypeExpr("boolean"):
                        raise SemanticError(f"Condition of do‐while must be boolean, got {ct}", stmt.cond.pos)
                self.check_block(stmt.else_body, symbol_table, expected_ret, in_loop, struct_subst, method_subst)
                symbol_table.clear(); symbol_table.update(backup)
                continue

            if isinstance(stmt, BreakStmt):
                if not in_loop:
                    raise SemanticError("'break' outside of loop", pos)
                continue

            if isinstance(stmt, ContinueStmt):
                if not in_loop:
                    raise SemanticError("'continue' outside of loop", pos)
                continue

            if isinstance(stmt, ReturnStmt):
                if expected_ret == TypeExpr("void"):
                    if stmt.expr is not None:
                        raise SemanticError("Cannot return a value from void function", pos)
                else:
                    if stmt.expr is None:
                        raise SemanticError(f"Missing return value in function returning '{expected_ret}'", pos)
                    rt = self.infer(stmt.expr, symbol_table, method_subst, struct_subst)
                    if not (rt == expected_ret or (rt == TypeExpr("*") and expected_ret in self.structs)):
                        raise SemanticError(f"Return type mismatch: expected {expected_ret}, got {rt}", pos)
                continue

            if isinstance(stmt, (FunctionCall, MethodCall)):
                self.infer(stmt, symbol_table, method_subst, struct_subst)
                continue

            self.infer(stmt, symbol_table, method_subst, struct_subst)

    def resolve_alias(self, te: TypeExpr,
                    seen: set[str] | None = None
                    ) -> TypeExpr:
        seen = seen or set()

        if te.name not in self.alias_map:
            return TypeExpr(te.name,
                            [self.resolve_alias(t, seen) for t in te.params])

        if te.name in seen:
            raise SemanticError(f"Circular alias: {te.name}")
        seen.add(te.name)

        type_params, aliased = self.alias_map[te.name]
        if len(type_params) != len(te.params):
            raise SemanticError(f"Wrong arity for alias {te.name}")

        substs = dict(zip(type_params, te.params))
        def subst(t: TypeExpr) -> TypeExpr:
            if not t.params and t.name in substs:
                return substs[t.name]
            return TypeExpr(t.name, [subst(c) for c in t.params])

        return self.resolve_alias(subst(aliased), seen)


    def infer(self, expr, symbol_table, substitution_map, struct_templates_params) -> TypeExpr:
        pos = getattr(expr, "pos", None)

        if isinstance(expr, Number): return TypeExpr("int")
        if isinstance(expr, BooleanLiteral): return TypeExpr("boolean")
        if isinstance(expr, NullLiteral): return TypeExpr("*")
        if isinstance(expr, ArrayLiteral):
            if not expr.elements: return TypeExpr("*")
            array_type = self.infer(expr.elements[0], symbol_table, substitution_map, struct_templates_params)
            for element in expr.elements[1:]:
                element_type = self.infer(element, symbol_table, substitution_map, struct_templates_params)
                if element_type != array_type:
                    raise SemanticError(f"Array elements must all be {array_type}, got {element_type}", pos)
            self.instantiate_struct("array", [array_type])
            return TypeExpr("array", [array_type])
        
        if isinstance(expr, Ident):
            if expr.name not in symbol_table:
                raise SemanticError(f"Undefined identifier: {expr.name}", pos)
            return symbol_table[expr.name]
        
        if isinstance(expr, UnaryOp):
            operand_type = self.infer(expr.expr, symbol_table, substitution_map, struct_templates_params)
            if expr.op == "!":
                if operand_type != TypeExpr("boolean"):
                    raise SemanticError(f"Unary '!' expects boolean, got {operand_type}", pos)
                return TypeExpr("boolean")
            if expr.op == "-":
                if operand_type != TypeExpr("int"):
                    raise SemanticError(f"Unary '-' expects int, got {operand_type}", pos)
                return TypeExpr("int")
            raise SemanticError(f"Unknown unary '{expr.op}'", pos)
        
        if isinstance(expr, BinOp):
            lt, rt = self.infer(expr.left, symbol_table, substitution_map, struct_templates_params), self.infer(expr.right, symbol_table, substitution_map, struct_templates_params)
            if expr.op in ("==", "!="):
                if lt == rt \
                    or (lt == TypeExpr("*") and not rt in (TypeExpr("boolean"), TypeExpr("int"))) \
                    or (rt == TypeExpr("*") and not lt in (TypeExpr("boolean"), TypeExpr("int"))):
                    return TypeExpr("boolean")
            elif lt != rt:
                raise SemanticError(f"Binary operator '{expr.op}' expects same types, got {lt} and {rt}", pos)
            elif expr.op in ("+", "-", "*", "/", "%"):
                if lt != TypeExpr("int"):
                    raise SemanticError(f"Binary operator '{expr.op}' expects int, got {lt}", pos)
                return TypeExpr("int")
            elif expr.op in (">", "<", ">=", "<=", "==", "!="):
                if lt != TypeExpr("int"):
                    raise SemanticError(f"Comparison operator '{expr.op}' expects int, got {lt}", pos)
                return TypeExpr("boolean")
            elif expr.op in ("&&", "||"):
                if lt != TypeExpr("boolean"):
                    raise SemanticError(f"Logical operator '{expr.op}' expects boolean, got {lt}", pos)
                return TypeExpr("boolean")
            raise SemanticError(f"Unknown binary operator '{expr.op}'", pos)

        # static method call
        if isinstance(expr, MethodCall) and isinstance(expr.receiver, Ident) and expr.receiver.name in self.struct_templates:
            type_name = expr.receiver.name
            struct_tvars, struct_decl = self.struct_templates[type_name]

            n_struct = len(struct_tvars)
            struct_args = expr.type_args[:n_struct]
            method_args = expr.type_args[n_struct:]

            self.instantiate_struct(type_name, struct_args)

            method_declaration = next(
                (m for m in struct_decl.methods if m.is_static and m.name == expr.method), None
            )

            if method_declaration is None:
                raise SemanticError(f"No static method '{expr.method}' in structure '{type_name}'", pos)

            if len(method_args) != len(method_declaration.type_params):
                raise SemanticError(
                    f"Method '{expr.method}' expects {len(method_declaration.type_params)} type-arg(s), got {len(method_args)}",
                    pos
                )
            
            method_sub_map = dict(zip(method_declaration.type_params, method_args))
            struct_sub_map = dict(zip(struct_tvars, struct_args))
            for arg, (param_name, param_type) in zip(expr.args, method_declaration.params):
                arg_type = self.infer(arg, symbol_table, substitution_map, struct_templates_params)

                expected_type = self.subst(param_type, {**method_sub_map, **struct_sub_map})
                if arg_type != expected_type:
                    raise SemanticError(
                        f"In call to '{type_name}.{expr.method}', expected {expected_type}, got {arg_type}",
                        arg.pos
                    )
            expr.struct = TypeExpr(type_name, struct_args) # type: ignore
            return self.subst(method_declaration.return_type, {**method_sub_map, **struct_sub_map})


        # method call
        if isinstance(expr, MethodCall):
            raw_receiver_type = self.infer(expr.receiver, symbol_table, substitution_map, struct_templates_params)
            receiver_type = self.subst(raw_receiver_type, substitution_map)
            expr.struct = receiver_type  # type: ignore
            if receiver_type.name not in self.struct_templates:
                raise SemanticError(f"Cannot call method on non-structure '{receiver_type}'", pos)
            
            self.instantiate_struct(receiver_type.name, receiver_type.params)

            type_params, struct_decl = self.struct_templates[receiver_type.name]
            method = next((m for m in struct_decl.methods if not m.is_static and m.name == expr.method), None)
            if method is None:
                raise SemanticError(f"No method '{expr.method}' in structure '{receiver_type.name}'", pos)
            if method.is_static:
                raise SemanticError(f"Cannot call static method '{expr.method}' on instance of '{receiver_type.name}'", pos)
            
            if len(expr.type_args) != len(method.type_params):
                raise SemanticError(
                    f"Method '{expr.method}' expects {len(method.type_params)} type-arg(s), got {len(expr.type_args)}",
                    pos
                )
            
            struct_tvars = dict(zip(type_params, receiver_type.params))
            struct_sub_map = dict(zip(type_params, receiver_type.params))
            method_sub_map = dict(zip(method.type_params, expr.type_args))

            for arg, (param_name, param_type) in zip(expr.args, method.params):
                arg_type = self.subst(self.infer(arg, symbol_table, substitution_map, struct_templates_params), {**method_sub_map, **struct_sub_map})

                expected_type = self.subst(param_type, {**method_sub_map, **struct_sub_map})
                if arg_type != expected_type:
                    raise SemanticError(
                        f"In call to '{receiver_type.name}.{expr.method}()', field '{param_name}' expects {expected_type}, got {arg_type}",
                        arg.pos
                    )
            return self.subst(method.return_type, {**method_sub_map, **struct_sub_map})

        # Constructor call
        if isinstance(expr, FunctionCall) and expr.name in self.struct_templates:
            tparams, struct_decl = self.struct_templates[expr.name]
            if len(expr.type_args) != len(tparams):
                raise SemanticError(
                    f"Constructor '{expr.name}' expects {len(tparams)} type-arg(s), got {len(expr.type_args)}",
                    pos
                )

            self.instantiate_struct(expr.name, expr.type_args)

            ctor = next((m for m in struct_decl.methods if m.is_static and m.name == expr.name), None)
            if ctor is None:
                raise SemanticError(f"No constructor for '{expr.name}'", pos)
            
            ctor_sub_map = dict(zip(tparams, expr.type_args))

            for arg, (param_name, param_type) in zip(expr.args, ctor.params):
                arg_type = self.infer(arg, symbol_table, substitution_map, struct_templates_params)

                expected_type = self.subst(self.subst(param_type, ctor_sub_map), substitution_map)
                if arg_type != expected_type:
                    raise SemanticError(
                        f"In constructor '{expr.name}()', field '{param_name}' expects {expected_type}, got {arg_type}",
                        arg.pos
                    )

            return TypeExpr(expr.name, expr.type_args)

        if isinstance(expr, FunctionCall):
            
            if expr.name not in self.func_sigs:
                raise SemanticError(f"Call to undefined function '{expr.name}'", pos)
            tparams, ptypes, rtype = self.func_sigs[expr.name]

            if len(expr.type_args) != len(tparams):
                raise SemanticError(
                    f"Function '{expr.name}' expects {len(tparams)} type-arg(s), got {len(expr.type_args)}",
                    pos
                )
            
            f_sub_map = dict(zip(tparams, expr.type_args))

            if expr.name in self.generic_functions and \
                (inst_key:=(expr.name, tuple(expr.type_args))) not in self.checked_func_insts:
                self.checked_func_insts.add(inst_key)
                function_declaration = next(f for f in self.func_decls if f.name == expr.name)
                body_symbol_table = {
                    param_name: TypeExpr(param_type.name, [f_sub_map.get(c.name, c) for c in param_type.params])
                    for param_name, param_type in zip((p for p,_ in function_declaration.params), ptypes)
                }
                self.check_block(
                    function_declaration.body,
                    body_symbol_table,
                    expected_ret=TypeExpr(rtype.name, [f_sub_map.get(c.name, c) for c in rtype.params]),
                    in_loop=False,
                    struct_subst={},
                    method_subst=f_sub_map
                    )
            
            for arg, param_type in zip(expr.args, ptypes):
                arg_type = self.infer(arg, symbol_table, substitution_map, struct_templates_params)

                expected_type = self.subst(param_type, f_sub_map)
                if arg_type != expected_type:
                    raise SemanticError(
                        f"In call to '{expr.name}', expected {expected_type}, got {arg_type}",
                        arg.pos
                    )


            return self.subst(rtype, dict(zip(tparams, expr.type_args)))

        if isinstance(expr, MemberAccess):
            receiver_type = self.infer(expr.obj, symbol_table, substitution_map, struct_templates_params)

            # static field
            if isinstance(expr.obj, Ident) and receiver_type.name in struct_templates_params:
                _, struct_decl = self.struct_templates[receiver_type.name]
                static_field = next((f for f in struct_decl.static_fields if f.name == expr.field), None)
                if static_field is not None:
                    expr.struct = TypeExpr(receiver_type.name, []) # type: ignore
                    expr.is_static_field = True #type: ignore
                    return static_field.type
            
            # instance field
            if receiver_type.name not in self.struct_templates:
                raise SemanticError(f"Cannot access field on non-structure '{receiver_type}'", pos)
            
            self.instantiate_struct(receiver_type.name, receiver_type.params)

            type_params, struct_decl = self.struct_templates[receiver_type.name]
            try:
                field_decl = next(f for f in struct_decl.fields if f.name == expr.field)
            except StopIteration:
                available_fields = [f.name for f in struct_decl.fields]
                raise SemanticError(f"Field '{expr.field}' not found in struct '{receiver_type.name}'. Available fields: {available_fields}", pos)
            
            expr.struct = receiver_type # type: ignore

            mapping = dict(zip(type_params, receiver_type.params))

            result_type = self.subst(field_decl.type, mapping)

            return result_type


        raise SemanticError(f"{expr} not an inferable expression", pos)

    def block_returns(self, bs):
        for s in bs:
            if isinstance(s, ReturnStmt):
                return True
            if isinstance(s, IfStmt):
                if self.block_returns(s.then_stmts) and self.block_returns(s.else_stmts):
                    return True
        return False