from .ast import (
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
    ListLiteral,
    ImportDeclaration,
    TypeExpr
)

class SemanticError(Exception):
    def __init__(self, message, pos=None):
        super().__init__(message)
        self.message = message
        self.pos = pos

    def __str__(self):
        if self.pos:
            return f"{self.pos[0]}:{self.pos[1]}: {self.message}"
        return self.message

def check(program: Program):
    # --- collect top-level declarations ---
    imports    = [d for d in program.decls if isinstance(d, ImportDeclaration)]
    func_decls = [d for d in program.decls if isinstance(d, FunctionDeclaration)]
    stmts      = [d for d in program.decls
                  if not isinstance(d, (FunctionDeclaration, StructureDeclaration, ImportDeclaration))]

    # --- collect struct definitions ---
    structs: dict[TypeExpr, StructureDeclaration] = {}
    for d in program.decls:
        if not isinstance(d, StructureDeclaration):
            continue
        key = TypeExpr(d.name)
        if key in structs:
            raise SemanticError(f"Structure '{d.name}' redefined", d.pos)
        structs[key] = d

    # --- check static‐field initializers ---
    for sd in structs.values():
        for sf in sd.static_fields:
            if isinstance(sf.expr, Number):
                init_t = TypeExpr("int")
            elif isinstance(sf.expr, BooleanLiteral):
                init_t = TypeExpr("boolean")
            else:
                raise SemanticError(f"Static initializer for '{sf.name}' must be a literal", sf.pos)
            if init_t != sf.type:
                raise SemanticError(f"Cannot assign {init_t} to static {sf.type} '{sf.name}'", sf.pos)

    # --- compute struct layouts for codegen ---
    struct_layouts = {
        key: {
            "size":    len(sd.fields) * 4,
            "offsets": { f.name: i*4 for i, f in enumerate(sd.fields) }
        }
        for key, sd in structs.items()
    }

    # --- build global function signatures (including generics) ---
    #  name -> ( type_params: list[str],
    #            param_types: list[TypeExpr],
    #            return_type: TypeExpr )
    func_sigs: dict[str, tuple[list[str], list[TypeExpr], TypeExpr]] = {}

    # host imports
    for imp in imports:
        if imp.name in func_sigs:
            raise SemanticError(f"Function '{imp.name}' redefined", imp.pos)
        # params are strings (names of basic types), return is string or TypeExpr
        sig_params = [ p for p in imp.params ]
        sig_ret    = imp.return_type if isinstance(imp.return_type, str) else imp.return_type
        func_sigs[imp.name] = ([], sig_params, sig_ret)  # no type-params # type: ignore

    # user‐defined functions (may be generic)
    for fd in func_decls:
        if fd.name in func_sigs:
            raise SemanticError(f"Function '{fd.name}' redefined", fd.pos)
        param_tys = [ pty for _, pty in fd.params ]
        func_sigs[fd.name] = (fd.type_params, param_tys, fd.return_type)

    # --- bookkeeping for generics ---
    # which functions are generic?
    generic_funcs = { fd.name for fd in func_decls if fd.type_params }
    # which instantiations have we checked?
    checked_instantiations: set[tuple[str, tuple[TypeExpr, ...]]] = set()

    # --- nested type-checker, with on‐demand generic instantiation ---
    def check_block(stmts, symbol_table, expected_ret, in_loop=False):
        def infer(expr):
            pos = getattr(expr, "pos", None)

            # primitives
            if isinstance(expr, Number):
                return TypeExpr("int")
            if isinstance(expr, BooleanLiteral):
                return TypeExpr("boolean")
            if isinstance(expr, NullLiteral):
                return TypeExpr("*")  # wildcard pointer

            # list literal sugar
            if isinstance(expr, ListLiteral):
                if not expr.elements:
                    raise SemanticError("Cannot create empty list literal", expr.pos)
                first_ty = infer(expr.elements[0])
                for e in expr.elements[1:]:
                    t = infer(e)
                    if t != first_ty:
                        raise SemanticError(
                            f"List literal elements must all be {first_ty}, got {t}", e.pos
                        )
                list_ty = TypeExpr("list")
                if list_ty not in structs:
                    raise SemanticError("No structure 'list' defined for list literal", expr.pos)
                sd = structs[list_ty]
                ctor = next((m for m in sd.methods if m.name == "list" and m.is_static), None)
                if ctor is None or len(ctor.params) != 1 or ctor.params[0][1] != first_ty:
                    raise SemanticError(
                        f"Constructor list({ctor.params if ctor else []}) not compatible with element type {first_ty}",
                        expr.pos
                    )
                return list_ty

            # variable or `this`
            if isinstance(expr, Ident):
                if expr.name not in symbol_table:
                    raise SemanticError(f"Undefined variable '{expr.name}'", pos)
                return symbol_table[expr.name]

            # unary/binary ops
            if isinstance(expr, UnaryOp):
                t = infer(expr.expr)
                if expr.op == "!":
                    if t != TypeExpr("boolean"):
                        raise SemanticError(f"Operator '!' expects boolean, got {t}", pos)
                    return TypeExpr("boolean")
                if expr.op == "-":
                    if t != TypeExpr("int"):
                        raise SemanticError(f"Unary '-' expects int, got {t}", pos)
                    return TypeExpr("int")
                raise SemanticError(f"Unknown unary operator '{expr.op}'", pos)

            if isinstance(expr, BinOp):
                lt, rt = infer(expr.left), infer(expr.right)
                if expr.op in {"+","-","*","/","%"}:
                    if lt == rt == TypeExpr("int"):
                        return TypeExpr("int")
                    raise SemanticError(f"Arithmetic '{expr.op}' expects ints, got {lt},{rt}", pos)
                if expr.op in {"<",">","<=",">="}:
                    if lt == rt == TypeExpr("int"):
                        return TypeExpr("boolean")
                    raise SemanticError(f"Comparison '{expr.op}' expects ints, got {lt},{rt}", pos)
                if expr.op in ("==","!="):
                    # ints or pointers
                    if lt == rt or (lt == TypeExpr("*") and rt not in (TypeExpr("int"),TypeExpr("boolean"))) \
                                or (rt == TypeExpr("*") and lt not in (TypeExpr("int"),TypeExpr("boolean"))):
                        return TypeExpr("boolean")
                    raise SemanticError(f"Cannot compare {lt} {expr.op} {rt}", pos)
                if expr.op in {"&&","||"}:
                    if lt == rt == TypeExpr("boolean"):
                        return TypeExpr("boolean")
                    raise SemanticError(f"Logical '{expr.op}' expects booleans, got {lt},{rt}", pos)
                raise SemanticError(f"Unknown binary operator '{expr.op}'", pos)

            # method call
            if isinstance(expr, MethodCall):
                # static
                if isinstance(expr.receiver, Ident) and TypeExpr(expr.receiver.name) in structs:
                    S = expr.receiver.name; sd = structs[TypeExpr(S)]
                    md = next((m for m in sd.methods if m.name == expr.method), None)
                    if md is None:
                        raise SemanticError(f"Structure '{S}' has no method '{expr.method}'", pos)
                    if not md.is_static:
                        raise SemanticError(f"Cannot call instance method '{expr.method}' without an object", pos)
                    if len(expr.args) != len(md.params):
                        raise SemanticError(f"Static method '{S}.{expr.method}' expects {len(md.params)} args, got {len(expr.args)}", pos)
                    for arg,(pn,pty) in zip(expr.args, md.params):
                        at = infer(arg)
                        if at != pty:
                            raise SemanticError(f"In call to '{S}.{expr.method}', expected {pty}, got {at}", arg.pos)
                    expr.struct_name = S
                    return md.return_type

                # instance
                r_t = infer(expr.receiver)
                if r_t not in structs:
                    raise SemanticError(f"Cannot call method '{expr.method}' on non-struct '{r_t}'", pos)
                sd = structs[r_t]
                md = next((m for m in sd.methods if m.name == expr.method), None)
                if md is None:
                    raise SemanticError(f"Structure '{r_t}' has no method '{expr.method}'", pos)
                if md.is_static:
                    raise SemanticError(f"Cannot call static method '{expr.method}' on instance", pos)
                if len(expr.args) != len(md.params):
                    raise SemanticError(f"Method '{r_t}.{expr.method}' expects {len(md.params)} args, got {len(expr.args)}", pos)
                for arg,(pn,pty) in zip(expr.args, md.params):
                    at = infer(arg)
                    if at != pty:
                        raise SemanticError(f"In call to '{r_t}.{expr.method}', expected {pty}, got {at}", arg.pos)
                expr.struct_name = r_t.name
                return md.return_type

            # free function or constructor
            if isinstance(expr, FunctionCall):
                # constructor
                ctor_key = TypeExpr(expr.name)
                if ctor_key in structs:
                    sd = structs[ctor_key]
                    ctor = next((m for m in sd.methods if m.name == expr.name and m.is_static), None)
                    if ctor is None:
                        raise SemanticError(f"Structure '{expr.name}' has no constructor", pos)
                    if len(expr.args) != len(ctor.params):
                        raise SemanticError(f"{expr.name}() expects {len(ctor.params)} args, got {len(expr.args)}", pos)
                    for arg,(pn,pty) in zip(expr.args, ctor.params):
                        at = infer(arg)
                        if at != pty:
                            raise SemanticError(f"In constructor {expr.name}(), field '{pn}' expects {pty}, got {at}", arg.pos)
                    return ctor_key

                # normal (possibly generic) function
                if expr.name not in func_sigs:
                    raise SemanticError(f"Call to undefined function '{expr.name}'", pos)
                type_params, ptypes, rtype = func_sigs[expr.name]

                # type‐arg arity
                if len(expr.type_args) != len(type_params):
                    raise SemanticError(
                        f"Function '{expr.name}' expects {len(type_params)} type argument(s), got {len(expr.type_args)}",
                        pos
                    )

                # substitute type‐variables
                subst_map = { tp: targ for tp, targ in zip(type_params, expr.type_args) }
                def subst(ty: TypeExpr) -> TypeExpr:
                    if not ty.params and ty.name in subst_map:
                        return subst_map[ty.name]
                    return TypeExpr(ty.name, [subst(c) for c in ty.params])

                inst_ptypes = [ subst(pt) for pt in ptypes ]
                inst_rtype  = subst(rtype)

                # argument arity & types
                if len(expr.args) != len(inst_ptypes):
                    raise SemanticError(f"Function '{expr.name}' expects {len(inst_ptypes)} arg(s), got {len(expr.args)}", pos)
                for arg, pty in zip(expr.args, inst_ptypes):
                    at = infer(arg)
                    if at != pty:
                        raise SemanticError(f"In call to '{expr.name}', expected {pty}, got {at}", arg.pos)

                # monomorphize generic on first instantiation
                if expr.name in generic_funcs:
                    inst_key = (expr.name, tuple(expr.type_args))
                    if inst_key not in checked_instantiations:
                        checked_instantiations.add(inst_key)
                        fd = next(f for f in func_decls if f.name == expr.name)
                        body_sym = {
                            pname: tyt for (pname,_), tyt in zip(fd.params, inst_ptypes)
                        }
                        check_block(fd.body, body_sym, inst_rtype, in_loop=False)

                return inst_rtype

            # field access
            if isinstance(expr, MemberAccess):
                # static field
                if isinstance(expr.obj, Ident) and TypeExpr(expr.obj.name) in structs:
                    sd = structs[TypeExpr(expr.obj.name)]
                    sf = next((f for f in sd.static_fields if f.name == expr.field), None)
                    if sf is not None:
                        expr.struct_name = expr.obj.name
                        expr.is_static_field = True  # type: ignore
                        return sf.type

                # instance field
                obj_t = infer(expr.obj)
                if obj_t not in structs:
                    raise SemanticError(f"Cannot access field on non-structure '{obj_t}'", pos)
                sd = structs[obj_t]
                for f in sd.fields:
                    if f.name == expr.field:
                        expr.struct_name = obj_t.name  # type: ignore
                        return f.type
                raise SemanticError(f"Structure '{obj_t}' has no field '{expr.field}'", pos)

            # if we get here, it's unhandled
            raise NotImplementedError(f"Cannot infer type of expression: {expr}")

        # walk statements
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
                    rt = infer(stmt.expr)
                    if not (rt == stmt.type or (rt == TypeExpr("*") and stmt.type in structs)):
                        raise SemanticError(f"Cannot assign {rt} to {stmt.type} '{stmt.name}'", pos)
                    symbol_table[stmt.name] = stmt.type
                continue

            if isinstance(stmt, VariableAssignment):
                if stmt.name not in symbol_table:
                    raise SemanticError(f"Assignment to undefined '{stmt.name}'", pos)
                lt = symbol_table[stmt.name]
                rt = infer(stmt.expr)
                if not (rt == lt or (rt == TypeExpr("*") and lt in structs)):
                    raise SemanticError(f"Cannot assign {rt} to {lt} '{stmt.name}'", pos)
                continue

            if isinstance(stmt, MemberAssignment):
                if getattr(stmt.obj, "is_static_field", False):
                    raise SemanticError(f"Cannot assign to static field '{stmt.field}'", stmt.pos)
                lhs_t = infer(stmt.obj)
                if not hasattr(stmt.obj, "struct_name"):
                    raise SemanticError("Invalid left-hand side in member assignment", pos)
                rt = infer(stmt.expr)
                if not (rt == lhs_t or (rt == TypeExpr("*") and lhs_t in structs)):
                    raise SemanticError(f"Cannot assign {rt} to field '{stmt.obj.field}' of type {lhs_t}", pos)
                continue

            if isinstance(stmt, IfStmt):
                ct = infer(stmt.cond)
                if ct != TypeExpr("boolean"):
                    raise SemanticError(f"Condition of if must be boolean, got {ct}", stmt.cond.pos)
                check_block(stmt.then_stmts, symbol_table.copy(), expected_ret, in_loop)
                check_block(stmt.else_stmts, symbol_table.copy(), expected_ret, in_loop)
                continue

            if isinstance(stmt, ForStmt):
                backup = symbol_table.copy()
                if stmt.init:  check_block([stmt.init], symbol_table, expected_ret, in_loop)
                ct = infer(stmt.cond) if stmt.cond else TypeExpr("boolean")
                if stmt.cond and ct != TypeExpr("boolean"):
                    raise SemanticError(f"Condition of for must be boolean, got {ct}", stmt.cond.pos)
                if stmt.post:  check_block([stmt.post], symbol_table, expected_ret, in_loop)
                check_block(stmt.body, symbol_table, expected_ret, in_loop=True)
                check_block(stmt.else_body, symbol_table, expected_ret, in_loop)
                symbol_table.clear(); symbol_table.update(backup)
                continue

            if isinstance(stmt, WhileStmt):
                ct = infer(stmt.cond)
                if ct != TypeExpr("boolean"):
                    raise SemanticError(f"Condition of while must be boolean, got {ct}", stmt.cond.pos)
                backup = symbol_table.copy()
                check_block(stmt.body, symbol_table, expected_ret, in_loop=True)
                check_block(stmt.else_body, symbol_table, expected_ret, in_loop)
                symbol_table.clear(); symbol_table.update(backup)
                continue

            if isinstance(stmt, UntilStmt):
                ct = infer(stmt.cond)
                if ct != TypeExpr("boolean"):
                    raise SemanticError(f"Condition of until must be boolean, got {ct}", stmt.cond.pos)
                backup = symbol_table.copy()
                check_block(stmt.body, symbol_table, expected_ret, in_loop=True)
                check_block(stmt.else_body, symbol_table, expected_ret, in_loop)
                symbol_table.clear(); symbol_table.update(backup)
                continue

            if isinstance(stmt, DoStmt):
                if stmt.count is not None:
                    ct = infer(stmt.count)
                    if ct != TypeExpr("int"):
                        raise SemanticError(f"Count in do‐repeat must be int, got {ct}", stmt.count.pos)
                backup = symbol_table.copy()
                check_block(stmt.body, symbol_table, expected_ret, in_loop=True)
                if stmt.cond is not None:
                    ct = infer(stmt.cond)
                    if ct != TypeExpr("boolean"):
                        raise SemanticError(f"Condition of do‐while must be boolean, got {ct}", stmt.cond.pos)
                check_block(stmt.else_body, symbol_table, expected_ret, in_loop)
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
                    rt = infer(stmt.expr)
                    if not (rt == expected_ret or (rt == TypeExpr("*") and expected_ret in structs)):
                        raise SemanticError(f"Return type mismatch: expected {expected_ret}, got {rt}", pos)
                continue

            # expression‐statement
            if isinstance(stmt, (FunctionCall, MethodCall)):
                infer(stmt)
                continue

            # fallback for any other node
            infer(stmt)

    # --- helper to see if a block always returns ---
    def block_returns(stmts) -> bool:
        for s in stmts:
            if isinstance(s, ReturnStmt):
                return True
            if isinstance(s, IfStmt):
                if block_returns(s.then_stmts) and block_returns(s.else_stmts):
                    return True
        return False

    # --- type‐check struct methods ---
    for struct_ty, sd in structs.items():
        for m in sd.methods:
            # build parameter table
            sym = { pname: pty for pname, pty in m.params }
            if not m.is_static:
                sym['this'] = struct_ty
            elif m.name == struct_ty.name:
                # static constructor
                sym['this'] = struct_ty

            check_block(m.body, sym, m.return_type, in_loop=False)
            if m.return_type != TypeExpr("void") \
               and not (m.is_static and m.name == struct_ty.name) \
               and not block_returns(m.body):
                raise SemanticError(f"Method '{struct_ty.name}.{m.name}' may exit without returning a value", m.pos)

    # --- top‐level vs. script mode ---
    if "main" in func_sigs and stmts:
        raise SemanticError("Top-level statements not allowed when 'main' is defined", stmts[0].pos)
    if stmts and "main" not in func_sigs:
        check_block(stmts, {}, TypeExpr("void"), in_loop=False)

    # --- finally, check every non-generic free function body ---
    for fd in func_decls:
        if fd.type_params:
            continue
        sym = { name: ty for name, ty in fd.params }
        check_block(fd.body, sym, fd.return_type, in_loop=False)
        if fd.return_type != TypeExpr("void") and not block_returns(fd.body):
            raise SemanticError(f"Function '{fd.name}' may exit without returning a value", fd.pos)
