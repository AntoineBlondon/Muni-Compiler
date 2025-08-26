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
    IntLiteral,
    FloatLiteral,
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
    CharLiteral,
    StringLiteral,
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

        self.validate_struct_templates()

        self.build_global_function_signatures()

        self.check_main_signature()

        for struct_name, (tparams, _) in self.struct_templates.items():
            placeholder_args = [TypeExpr(param) for param in tparams]
            self.instantiate_struct(struct_name, placeholder_args)
        
        for (struct_name, type_args) in list(self.checked_struct_insts):
            self.instantiate_struct(struct_name, list(type_args))
        
        
        for fd in self.func_decls:
            if fd.type_params:
                continue
            sym = { name: ty for name,ty in fd.params }
            self.check_block(fd.body, sym, expected_ret=fd.return_type, in_loop=False)

            # ensure non-void returns on every path
            if fd.return_type != TypeExpr("void") and not self.block_returns(fd.body):
                raise SemanticError(f"Function '{fd.name}' may exit without returning a value", fd.pos)
        
        for fd in self.func_decls:
            setattr(fd, "_wasm_params", [self.wasm_ty_of(pty) for (_n, pty) in fd.params])
            setattr(fd, "_wasm_result", self.wasm_ty_of(fd.return_type))
        for imp in self.imports:
            setattr(imp, "_wasm_params", [self.wasm_ty_of(t) for t in imp.params])
            if imp.return_type is None:
                setattr(imp, "_wasm_result", "void")
            else:
                setattr(imp, "_wasm_result", self.wasm_ty_of(imp.return_type))

    def decompose_program(self):
        self.imports = [d for d in self.program.decls if isinstance(d, ImportDeclaration)]
        self.func_decls = [d for d in self.program.decls if isinstance(d, FunctionDeclaration)]
        self.struct_decls = [d for d in self.program.decls if isinstance(d, StructureDeclaration)]
        self.raw_aliases = [d for d in self.program.decls if isinstance(d, AliasDeclaration)]


        self.define_char_and_string()

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
        # 1) rewrite all the *declaration* sites
        for d in self.program.decls:
            if isinstance(d, FunctionDeclaration):
                d.return_type = self.resolve_alias(d.return_type)
                for i, (name, pty) in enumerate(d.params):
                    d.params[i] = (name, self.resolve_alias(pty))

            elif isinstance(d, StructureDeclaration):
                for f in d.fields:
                    f.type = self.resolve_alias(f.type)
                for sf in d.static_fields:
                    sf.type = self.resolve_alias(sf.type)
                for m in d.methods:
                    m.return_type = self.resolve_alias(m.return_type)
                    for j, (name, pty) in enumerate(m.params):
                        m.params[j] = (name, self.resolve_alias(pty))

            elif isinstance(d, ImportDeclaration):
                for i, type_expr in enumerate(d.params):
                    d.params[i] = self.resolve_alias(type_expr)
                
                d.return_type = self.resolve_alias(d.return_type) # type: ignore


        # 2) now rewrite every statement (and every expression inside) in every function, method & top level
        for fd in self.func_decls:
            for stmt in fd.body:
                self.rewrite_types_in_stmt(stmt)
        for sd in self.struct_decls:
            for m in sd.methods:
                for stmt in m.body:
                    self.rewrite_types_in_stmt(stmt)

    def rewrite_types_in_stmt(self, stmt):
        # if this is a local var decl, rewrite its declared type:
        if isinstance(stmt, VariableDeclaration):
            stmt.type = self.resolve_alias(stmt.type)
            stmt.expr = self.rewrite_types_in_expr(stmt.expr) if stmt.expr else None

        # if this is an assignment to a local, rewrite the RHS expr:
        if isinstance(stmt, VariableAssignment):
            stmt.expr = self.rewrite_types_in_expr(stmt.expr)

        # if this is return, rewrite the returned expr:
        if isinstance(stmt, ReturnStmt) and stmt.expr is not None:
            stmt.expr = self.rewrite_types_in_expr(stmt.expr)
        

        # recurse into sub-statements:
        for child_list in (
            getattr(stmt, "body", []),
            getattr(stmt, "then_stmts", []),
            getattr(stmt, "else_stmts", []),
            getattr(stmt, "else_body", []),
        ):
            for s in child_list:
                self.rewrite_types_in_stmt(s)

        # handle loop heads:
        if hasattr(stmt, "init") and stmt.init:                                  # type: ignore
            if isinstance(stmt.init, (VariableDeclaration, VariableAssignment)): # type: ignore
                self.rewrite_types_in_stmt(stmt.init)                            # type: ignore
        if hasattr(stmt, "cond") and stmt.cond:                                  # type: ignore
            stmt.cond = self.rewrite_types_in_expr(stmt.cond)                    # type: ignore
        if hasattr(stmt, "post") and stmt.post:                                  # type: ignore
            if isinstance(stmt.post, (VariableDeclaration, VariableAssignment)): # type: ignore
                self.rewrite_types_in_stmt(stmt.post)                            # type: ignore

    def rewrite_types_in_expr(self, expr):
        if isinstance(expr, MethodCall):
            expr.args = [self.rewrite_types_in_expr(a) for a in expr.args]
            expr.receiver = self.rewrite_types_in_expr(expr.receiver)
            expr.type_args = [self.resolve_alias(t) for t in expr.type_args]

            if isinstance(expr.receiver, Ident) and expr.receiver.name in self.alias_map:
                alias_ty = TypeExpr(expr.receiver.name, expr.type_args)
                real_ty  = self.resolve_alias(alias_ty)
                expr.receiver.name = real_ty.name
                expr.type_args     = real_ty.params
            return expr

        if isinstance(expr, FunctionCall):
            expr.args = [self.rewrite_types_in_expr(a) for a in expr.args]
            expr.type_args = [self.resolve_alias(t) for t in expr.type_args]
            if expr.name in self.alias_map:
                alias_ty = TypeExpr(expr.name, expr.type_args)
                real_ty  = self.resolve_alias(alias_ty)
                expr.name      = real_ty.name
                expr.type_args = real_ty.params
            return expr

        # MemberAccess / MemberAssignment
        if isinstance(expr, MemberAccess):
            expr.obj = self.rewrite_types_in_expr(expr.obj)
            return expr

        if isinstance(expr, MemberAssignment):
            expr.obj  = self.rewrite_types_in_expr(expr.obj)
            expr.expr = self.rewrite_types_in_expr(expr.expr)
            return expr

        # Binary/Unary operators recurse
        if isinstance(expr, BinOp):
            expr.left  = self.rewrite_types_in_expr(expr.left)
            expr.right = self.rewrite_types_in_expr(expr.right)
            return expr

        if isinstance(expr, UnaryOp):
            expr.expr = self.rewrite_types_in_expr(expr.expr)
            return expr

        # ArrayLiteral
        if isinstance(expr, ArrayLiteral):
            expr.elements = [self.rewrite_types_in_expr(e) for e in expr.elements]
            return expr

        # all other exprs are terminals (Number, BooleanLiteral, Ident, NullLiteral)
        return expr

    def define_char_and_string(self):
        char_alias = AliasDeclaration(
            name="char",
            type_params=[],
            aliased=TypeExpr("int")
        )

        string_alias = AliasDeclaration(
            name="string",
            type_params=[],
            aliased=TypeExpr("vec", [TypeExpr("char")])
        )

        self.raw_aliases.append(char_alias)
        self.raw_aliases.append(string_alias)


    def check_type_with_scope(self, typ: TypeExpr, scope_type_vars: set[str]):
        # bare var
        if not typ.params and typ.name in scope_type_vars:
            return
        # built-in
        if typ.name in ("int", "float", "boolean", "void"):
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
        for struct_decl in self.struct_decls:
            name = struct_decl.name
            if name in self.struct_templates:
                raise SemanticError(f"Redefinition of structure '{name}'", struct_decl.pos)
            self.struct_templates[name] = (
                struct_decl.type_params,
                struct_decl
            )

        for struct_name, (type_params, struct_decl) in self.struct_templates.items():
            # static fields
            for static_field in struct_decl.static_fields:
                setattr(static_field, "_wt", self.wasm_ty_of(static_field.type))
                if not isinstance(static_field.expr, (IntLiteral, FloatLiteral, BooleanLiteral)):
                    raise SemanticError(f"Static field '{static_field.name}' in structure '{struct_name}' must be a constant expression", static_field.pos)
                if expr_type := self.infer(static_field.expr, {}, {}, {}) != static_field.type:
                    raise SemanticError(
                        f"Cannot assign {expr_type} to static {static_field.type} '{static_field.name}'",
                        static_field.pos
                    )

            # normal fields
            for field in struct_decl.fields:
                type_name = field.type.name
                if type_name not in ("int", "float", "boolean") and type_name not in type_params:
                    if type_name not in self.struct_templates:
                        raise SemanticError(f"Undefined type '{type_name}' in structure '{struct_name}'", field.pos)

            # methods
            for method in struct_decl.methods:
                scope_vars = set(type_params) | set(method.type_params)
                self.check_type_with_scope(method.return_type, scope_vars)
                for _, param_type in method.params:
                    self.check_type_with_scope(param_type, scope_vars)

    def check_main_signature(self):
        if "main" not in self.func_sigs:
            raise SemanticError("Missing 'main' function", None)
        params = self.func_sigs["main"][1]
        if len(params) != 0:
            raise SemanticError("Invalid 'main' function signature: 'main' must have no parameters", None)
        if self.func_sigs["main"][2] != TypeExpr("void"):
            raise SemanticError("Invalid 'main' function signature: 'main' must return void", None)

    def build_global_function_signatures(self):
        for function_declaration in self.func_decls:
            if function_declaration.name in self.func_sigs:
                raise SemanticError(f"Redefinition of function '{function_declaration.name}'", function_declaration.pos)
            param_types = [pty for (_n, pty) in function_declaration.params]
            self.func_sigs[function_declaration.name] = (
                function_declaration.type_params, # TODO check
                param_types,
                function_declaration.return_type
            )
            
        for imp in self.imports:
            if imp.name in self.func_sigs:
                raise SemanticError(f"Redefinition of function '{imp.name}'", imp.pos)
            self.func_sigs[imp.name] = (imp.type_params, imp.params, imp.return_type)

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
                    setattr(stmt, "_wt", self.wasm_ty_of(lhs_t))
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
                    map_subst = {**method_subst, **struct_subst}
                    rt = self.subst(rt, map_subst)
                    exp = self.subst(expected_ret, map_subst)
                    if not (rt == exp or (rt == TypeExpr("*") and exp in self.structs)):
                        raise SemanticError(f"Return type mismatch: expected {exp}, got {rt}", pos)
                continue

            if isinstance(stmt, FunctionCall):
                self.infer(stmt, symbol_table, method_subst, struct_subst)
                _, param_types, _ = self.func_sigs[stmt.name]
                expected_args = len(param_types)
                if len(stmt.args) != expected_args:
                    raise SemanticError(f"Function '{stmt.name}' expects {expected_args} arguments, got {len(stmt.args)}", pos)
                continue
            
            if isinstance(stmt, MethodCall):
                # Type-check the call first, then compute the expected value-arg count from the target method
                self.infer(stmt, symbol_table, method_subst, struct_subst)
                if isinstance(stmt.receiver, Ident) and stmt.receiver.name in self.struct_templates:
                    # static method
                    _, struct_decl = self.struct_templates[stmt.receiver.name]
                    method_decl = next((m for m in struct_decl.methods if m.is_static and m.name == stmt.method), None)
                    if method_decl is None:
                        raise SemanticError(f"No static method '{stmt.method}' in structure '{stmt.receiver.name}'", pos)
                    expected_args = len(method_decl.params)
                else:
                    # instance method
                    receiver_ty = self.subst(self.infer(stmt.receiver, symbol_table, method_subst, struct_subst), method_subst)
                    if receiver_ty.name not in self.struct_templates:
                        raise SemanticError(f"Cannot call method on non-structure '{receiver_ty}'", pos)
                    _, struct_decl = self.struct_templates[receiver_ty.name]
                    method_decl = next((m for m in struct_decl.methods if not m.is_static and m.name == stmt.method), None)
                    if method_decl is None:
                        raise SemanticError(f"No method '{stmt.method}' in structure '{receiver_ty.name}'", pos)
                    expected_args = len(method_decl.params)
                if len(stmt.args) != expected_args:
                    raise SemanticError(f"Method '{stmt.method}' expects {expected_args} arguments, got {len(stmt.args)}", pos)
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
        return self.resolve_alias(self.subst(aliased, substs), seen)

    def infer(self, expr, symbol_table, substitution_map, struct_templates_params) -> TypeExpr:
        pos = getattr(expr, "pos", None)

        if isinstance(expr, IntLiteral): return self.mark(expr, TypeExpr("int"))
        if isinstance(expr, FloatLiteral): return self.mark(expr, TypeExpr("float"))
        if isinstance(expr, BooleanLiteral): return self.mark(expr, TypeExpr("boolean"))
        if isinstance(expr, NullLiteral): return self.mark(expr, TypeExpr("*"))
        if isinstance(expr, CharLiteral): return self.mark(expr, TypeExpr("int"))
        if isinstance(expr, ArrayLiteral):
            if not expr.elements: return TypeExpr("*")
            array_type = self.infer(expr.elements[0], symbol_table, substitution_map, struct_templates_params)
            for element in expr.elements[1:]:
                element_type = self.infer(element, symbol_table, substitution_map, struct_templates_params)
                if element_type != array_type:
                    raise SemanticError(f"Array elements must all be {array_type}, got {element_type}", pos)
            self.instantiate_struct("array", [array_type])
            expr.element_type = array_type  # type: ignore
            setattr(expr, "_elem_wt", array_type)
            return self.mark(expr, TypeExpr("array", [array_type]))

        if isinstance(expr, StringLiteral):
            str_ty = self.resolve_alias(TypeExpr("string"))
            # typically vec<int> after char := int
            if str_ty.name != "vec" or len(str_ty.params) != 1:
                raise SemanticError("Internal: 'string' must resolve to vec<…>")
            self.instantiate_struct(str_ty.name, str_ty.params)
            return self.mark(expr, str_ty)

        if isinstance(expr, Ident):
            if expr.name not in symbol_table:
                raise SemanticError(f"Undefined identifier: {expr.name}", pos)
            return self.mark(expr, symbol_table[expr.name])
        
        if isinstance(expr, UnaryOp):
            operand_type = self.infer(expr.expr, symbol_table, substitution_map, struct_templates_params)
            if expr.op == "!":
                if operand_type != TypeExpr("boolean"):
                    raise SemanticError(f"Unary '!' expects boolean, got {operand_type}", pos)
                return self.mark(expr, TypeExpr("boolean"))
            if expr.op == "-":
                if operand_type == TypeExpr("int"):
                    return self.mark(expr, TypeExpr("int"))
                elif operand_type == TypeExpr("float"):
                    return self.mark(expr, TypeExpr("float"))
                else:
                    raise SemanticError(f"Unary '-' expects int or float, got {operand_type}", pos)
                
            raise SemanticError(f"Unknown unary '{expr.op}'", pos)
        
        if isinstance(expr, BinOp):
            lt, rt = self.infer(expr.left, symbol_table, substitution_map, struct_templates_params), self.infer(expr.right, symbol_table, substitution_map, struct_templates_params)
            if expr.op in ("==", "!="):
                if lt == rt \
                    or (lt == TypeExpr("*") and not rt in (TypeExpr("boolean"), TypeExpr("int"))) \
                    or (rt == TypeExpr("*") and not lt in (TypeExpr("boolean"), TypeExpr("int"))):
                    return self.mark(expr, TypeExpr("boolean"))
                raise SemanticError(f"Binary operator '{expr.op}' expects same types, got {lt} and {rt}", pos)
            elif lt != rt:
                raise SemanticError(f"Binary operator '{expr.op}' expects same types, got {lt} and {rt}", pos)
            elif expr.op in ("+", "-", "*", "/", "%"):
                if lt == TypeExpr("int"):
                    return self.mark(expr, TypeExpr("int"))
                elif lt == TypeExpr("float") and expr.op != "%":
                    return self.mark(expr, TypeExpr("float"))
                #check if structure has a _add method
                elif lt in self.structs:
                    tparams, struct_decl = self.struct_templates[lt.name]
                    mname = self._op_method_name(expr.op)
                    method = next((m for m in struct_decl.methods if m.name == mname and not m.is_static), None)
                    if method is None:
                        raise SemanticError(f"Structure '{lt}' has no method for {expr.op}", pos)

                    subst_map = dict(zip(tparams, lt.params))
                    ret_ty = self.subst(method.return_type, subst_map)   # SPECIALIZE here
                    return self.mark(expr, ret_ty)
                raise SemanticError(f"Arithmetic operator '{expr.op}' expects int, float or structure, got {lt}", pos)
            elif expr.op in ("+=", "-=", "*=", "/=", "%="):
                if lt == TypeExpr("int"):
                    return self.mark(expr, TypeExpr("int"))
                elif lt == TypeExpr("float") and expr.op != "%=":
                    return self.mark(expr, TypeExpr("float"))
                elif lt in self.structs:
                    tparams, struct_decl = self.struct_templates[lt.name]
                    mname = self._op_method_name(expr.op)
                    method = next((m for m in struct_decl.methods if m.name == mname and not m.is_static), None)
                    if method is None:
                        raise SemanticError(f"Structure '{lt}' has no method for {expr.op}", pos)
                    ret_ty = self.subst(method.return_type, dict(zip(tparams, lt.params)))
                    return self.mark(expr, ret_ty)
                raise SemanticError(f"Compound assignment operator '{expr.op}' expects int, float or structure, got {lt}", pos)
            elif expr.op in (">", "<", ">=", "<=", "==", "!="):
                if lt in [TypeExpr("int"), TypeExpr("float")]:
                    return self.mark(expr, TypeExpr("boolean"))
                else:
                    raise SemanticError(f"Comparison operator '{expr.op}' expects int or float, got {lt}", pos)
            elif expr.op in ("&&", "||"):
                if lt != TypeExpr("boolean"):
                    raise SemanticError(f"Logical operator '{expr.op}' expects boolean, got {lt}", pos)
                return self.mark(expr, TypeExpr("boolean"))
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
            return self.mark(expr, self.subst(method_declaration.return_type, {**method_sub_map, **struct_sub_map}))

        # method call
        if isinstance(expr, MethodCall):
            raw_receiver_type = self.infer(expr.receiver, symbol_table, substitution_map, struct_templates_params)
            receiver_type = self.subst(raw_receiver_type, substitution_map)
            expr.struct = receiver_type  # type: ignore
            if receiver_type.name not in self.struct_templates:
                raise SemanticError(f"Cannot call method on non-structure '{receiver_type}'", pos)

            if receiver_type.name == "array":
                expr.element_type = receiver_type.params[0] if receiver_type.params else None #type: ignore

            self.instantiate_struct(receiver_type.name, receiver_type.params)

            type_params, struct_decl = self.struct_templates[receiver_type.name]
            method = next((m for m in struct_decl.methods if m.name == expr.method), None)
            if method is None:
                raise SemanticError(f"No method '{expr.method}' in structure '{receiver_type.name}'", pos)
            if method.is_static:
                raise SemanticError(f"Cannot call static method '{expr.method}' on instance of '{receiver_type.name}'", pos)

            if len(expr.type_args) != len(method.type_params):
                raise SemanticError(
                    f"Method '{expr.method}' expects {len(method.type_params)} type-arg{('s' if len(method.type_params) != 1 else '')}, got {len(expr.type_args)}",
                    pos
                )
            
            if len(expr.args) != len(method.params):
                raise SemanticError(
                    f"Method '{expr.method}' expects {len(method.params)} argument{('s' if len(method.params) != 1 else '')}, got {len(expr.args)}",
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
            return self.mark(expr, self.subst(method.return_type, {**method_sub_map, **struct_sub_map}))

        if isinstance(expr, FunctionCall) and expr.name == "as" and len(expr.args) == 1 and len(expr.type_args) == 1:
            src = self.infer(expr.args[0], symbol_table, substitution_map, struct_templates_params)
            # apply current substitutions to the destination type param
            dst = self.subst(self.resolve_alias(expr.type_args[0]), {**substitution_map, **struct_templates_params})
            if not self.can_cast(src, dst):
                raise SemanticError(f"Cannot cast {src} to {dst}", expr.pos)
            return self.mark(expr, dst)

        # Constructor call
        if isinstance(expr, FunctionCall) and expr.name in self.struct_templates:
            tparams, struct_decl = self.struct_templates[expr.name]

            # Remap call-site type args through current substitutions
            # (method_subst/substitution_map + struct_subst/struct_templates_params)
            remap = {**substitution_map, **struct_templates_params}
            type_args = [self.subst(self.resolve_alias(t), remap) for t in expr.type_args]

            if len(type_args) != len(tparams):
                raise SemanticError(
                    f"Constructor '{expr.name}' expects {len(tparams)} type-arg(s), got {len(type_args)}",
                    pos
                )

            # Use the remapped concrete args from here on
            self.instantiate_struct(expr.name, type_args)

            ctor = next((m for m in struct_decl.methods
                        if m.is_static and m.name == expr.name), None)
            if ctor is None:
                raise SemanticError(f"No constructor for '{expr.name}'", pos)

            struct_sub_map = dict(zip(tparams, type_args))

            for arg, (pname, ptype) in zip(expr.args, ctor.params):
                arg_t = self.infer(arg, symbol_table, substitution_map, struct_templates_params)
                # Apply both maps to BOTH sides
                arg_t = self.subst(arg_t, {**substitution_map, **struct_sub_map})
                exp_t = self.subst(ptype, {**substitution_map, **struct_sub_map})
                if arg_t != exp_t:
                    raise SemanticError(
                        f"In constructor '{expr.name}()', field '{pname}' expects {exp_t}, got {arg_t}",
                        arg.pos
                    )
            if expr.name == "array":
                setattr(expr, "_elem_type", type_args[0] if type_args else None)
                expr.element_type = type_args[0] if type_args else None # type: ignore
                


            return self.mark(expr, TypeExpr(expr.name, type_args))



        if isinstance(expr, FunctionCall):
            if expr.name not in self.func_sigs:
                raise SemanticError(f"Call to undefined function '{expr.name}'", pos)
            tparams, ptypes, rtype = self.func_sigs[expr.name]
            
            if len(expr.type_args) != len(tparams):
                raise SemanticError(
                    f"Function '{expr.name}' expects {len(tparams)} type-arg{('s' if len(tparams) != 1 else '')}, got {len(expr.type_args)}",
                    pos
                )

            if len(expr.args) != len(ptypes):
                raise SemanticError(
                    f"Function '{expr.name}' expects {len(ptypes)} argument{('s'if len(ptypes)!=1 else'')}, got {len(expr.args)}",
                    pos
                )

            f_sub_map = dict(zip(tparams, expr.type_args))

            if expr.name in self.generic_functions and \
                (inst_key:=(expr.name, tuple(expr.type_args))) not in self.checked_func_insts:
                self.checked_func_insts.add(inst_key)
                function_declaration = next(f for f in self.func_decls if f.name == expr.name)
                body_symbol_table = {
                    param_name: self.subst(param_type, f_sub_map)
                    for param_name, param_type in zip((p for p,_ in function_declaration.params), ptypes)
                }
                self.check_block(
                    function_declaration.body,
                    body_symbol_table,
                    expected_ret = self.subst(rtype, f_sub_map),
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


            return self.mark(expr, self.subst(rtype, dict(zip(tparams, expr.type_args))))

        if isinstance(expr, MemberAccess):

            # static field
            if isinstance(expr.obj, Ident) and expr.obj.name in self.struct_templates:
                _, struct_decl = self.struct_templates[expr.obj.name]
                static_field = next((f for f in struct_decl.static_fields if f.name == expr.field), None)
                if static_field is not None:
                    expr.struct = TypeExpr(expr.obj.name, []) # type: ignore
                    expr.is_static_field = True #type: ignore
                    return self.mark(expr, static_field.type)

            receiver_type = self.infer(expr.obj, symbol_table, substitution_map, struct_templates_params)
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

            return self.mark(expr, result_type)

        raise SemanticError(f"{expr} not an inferable expression", pos)

    def block_returns(self, bs):
        for s in bs:
            if isinstance(s, ReturnStmt):
                return True
            if isinstance(s, IfStmt):
                if self.block_returns(s.then_stmts) and self.block_returns(s.else_stmts):
                    return True
        return False

        
    def wasm_ty_of(self, t: TypeExpr) -> str:
        if t.name in ("int", "boolean"): return "i32"
        if t.name in ("float"):   return "f32"
        if t.name == "void":             return "void"
        return "i32"

    def mark(self, expr, ty: TypeExpr) -> TypeExpr:
        setattr(expr, "_wt", self.wasm_ty_of(ty))
        setattr(expr, "type", ty)
        return ty
    
    def can_cast(self, src: TypeExpr, dst: TypeExpr) -> bool:
        if src == dst:
            return True
        # null/star → any ref type
        if src == TypeExpr("*") and dst.name not in ("int","float","boolean","void"):
            return True
        # numeric & bool casts (both ways)
        if (src.name, dst.name) in {
            ("int","float"), ("float","int"),
            ("int","boolean"), ("boolean","int"),
            ("float","boolean"), ("boolean","float"),
        }:
            return True
        # any ref (struct/array) → boolean (i32 != 0)
        if src.name not in ("int","float","boolean","void") and dst == TypeExpr("boolean"):
            return True
        return False

    def _op_method_name(self, op: str) -> str:
        # arithmetic
        if op in ("+", "+="): return "_add"
        if op in ("-", "-="): return "_sub"
        if op in ("*", "*="): return "_mul"
        if op in ("/", "/="): return "_div"
        if op in ("%", "%="): return "_mod"
        raise SemanticError(f"Unknown operator '{op}'")