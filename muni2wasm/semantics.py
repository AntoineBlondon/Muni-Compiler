# mun2wasm/semantics.py

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
    TypeExpr,
)
from collections import defaultdict

class SemanticError(Exception):
    def __init__(self, message, pos=None):
        super().__init__(message)
        self.message = message
        self.pos     = pos

    def __str__(self):
        if self.pos:
            return f"{self.pos[0]}:{self.pos[1]}: {self.message}"
        return self.message

def check(program: Program):
    # ---
    # 1) Gather host-imports & free functions
    # ---
    imports    = [d for d in program.decls if isinstance(d, ImportDeclaration)]
    func_decls = [d for d in program.decls if isinstance(d, FunctionDeclaration)]
    top_stmts  = [
        d for d in program.decls
        if not isinstance(d, (ImportDeclaration, FunctionDeclaration, StructureDeclaration))
    ]

    # ---
    # 2) Gather struct‐templates
    #    key: struct name → ( type_params: list[str], sd:StructureDeclaration )
    # ---
    struct_templates: dict[str, tuple[list[str],StructureDeclaration]] = {}
    
    for d in program.decls:
        if not isinstance(d, StructureDeclaration):
            continue
        if d.name in struct_templates:
            raise SemanticError(f"Structure '{d.name}' redefined", d.pos)
        struct_templates[d.name] = (d.type_params, d)

    structs: dict[TypeExpr, StructureDeclaration] = {}
    for name, (_tparams, sd) in struct_templates.items():
        structs[TypeExpr(name)] = sd
    # ---
    # 3) Validate each struct’s **definition** (static fields, field decls, method signatures)
    #    *but* do _not_ yet check bodies under concrete type args
    # ---
    for struct_name, (tparams, sd) in struct_templates.items():
        # 3a) static‐field initializers must be literals
        for sf in sd.static_fields:
            if isinstance(sf.expr, Number):
                init_t = TypeExpr("int")
            elif isinstance(sf.expr, BooleanLiteral):
                init_t = TypeExpr("boolean")
            else:
                raise SemanticError(
                    f"Static initializer for '{sf.name}' must be a literal",
                    sf.pos
                )
            if init_t != sf.type:
                raise SemanticError(
                    f"Cannot assign {init_t} to static {sf.type} '{sf.name}'",
                    sf.pos
                )
        # 3b) every field’s declared type must be either
        #     - a built-in (int, boolean, void),
        #     - another struct template name (no params here),
        #     - or one of this struct’s type_params
        for f in sd.fields:
            tn = f.type.name
            if tn in ("int","boolean","void"):
                continue
            if tn in tparams:
                continue
            if tn not in struct_templates:
                raise SemanticError(f"Unknown field type '{tn}'", f.pos)

        # 3c) each method’s signature may refer to
        #     - built-ins,
        #     - any struct name,
        #     - or any of (struct_type_params ∪ method.type_params)
        for m in sd.methods:
            # build the **set** of type‐vars in scope
            scope_tvars = set(tparams) | set(m.type_params)
            def check_type(ty: TypeExpr):
                # bare var
                if not ty.params and ty.name in scope_tvars:
                    return
                # built-in
                if ty.name in ("int","boolean","void"):
                    if ty.params:
                        raise SemanticError(f"Type '{ty}' may not have parameters", m.pos)
                    return
                # struct instantiation
                if ty.name in struct_templates:
                    # correct number of params?
                    needed = len(struct_templates[ty.name][0])
                    if len(ty.params) != needed:
                        raise SemanticError(
                            f"Type '{ty.name}' expects {needed} parameter(s), got {len(ty.params)}",
                            m.pos
                        )
                    # recurse
                    for sub in ty.params:
                        check_type(sub)
                    return
                raise SemanticError(f"Unknown type '{ty}'", m.pos)

            # return type
            check_type(m.return_type)
            # param types
            for _, pty in m.params:
                check_type(pty)

    # ---
    # 4) build global function signatures (including generics)
    #    name → ( type_params, param_types, return_type )
    # ---
    func_sigs: dict[str, tuple[list[str],list[TypeExpr],TypeExpr]] = {}

    # 4a) host imports
    for imp in imports:
        if imp.name in func_sigs:
            raise SemanticError(f"Function '{imp.name}' redefined", imp.pos)
        func_sigs[imp.name] = ([], imp.params, imp.return_type) # type: ignore

    # 4b) user functions
    for fd in func_decls:
        if fd.name in func_sigs:
            raise SemanticError(f"Function '{fd.name}' redefined", fd.pos)
        param_tys = [ pty for _,pty in fd.params ]
        func_sigs[fd.name] = (fd.type_params, param_tys, fd.return_type)

    # which free functions are generic?
    generic_funcs = { f.name for f in func_decls if f.type_params }
    checked_func_insts = set()  # (fname, tuple[TypeExpr,...])

    # ---
    # 5) helper: monomorphize + type-check one struct‐template <…> inst
    #    we must check its *constructor* + *all instance methods* under the substitution
    #    only once per (struct_name, type_args)
    # ---
    checked_struct_insts = set()  # (struct_name, tuple[TypeExpr,...])

    def instantiate_struct(name: str, args: list[TypeExpr]):
        key = (name, tuple(args))
        if key in checked_struct_insts:
            return
        checked_struct_insts.add(key)

        tparams, sd = struct_templates[name]
        # build substitution map: Tvar → actual TypeExpr
        sub_map = dict(zip(tparams, args))

        structs[ TypeExpr(name, list(args)) ] = sd
        # helper to substitute in any TypeExpr
        def subst(ty: TypeExpr) -> TypeExpr:
            if not ty.params and ty.name in sub_map:
                return sub_map[ty.name]
            return TypeExpr(ty.name, [subst(c) for c in ty.params])

        # build a synthetic global func_sigs & structs visible for checking bodies
        #   here `structs` maps bare-TypeExpr(name) → Definition
        #   but for infer we only need lookup by name-part
        ...

        # type-check the static constructor
        ctor = next((m for m in sd.methods
                     if m.is_static and m.name == name), None)
        if ctor:
            # sym: parameters + this
            sym = {}
            sym['this'] = TypeExpr(name, args)
            for pname, pty in ctor.params:
                sym[pname] = subst(pty)
            check_block(ctor.body, sym,
                        expected_ret=TypeExpr(name,args),
                        in_loop=False,
                        struct_subst=sub_map,
                        method_subst={})

        # type-check each instance method
        for m in sd.methods:
            if m.is_static and m.name == name:
                continue
            # sym: this + params
            sym = {}
            sym['this'] = TypeExpr(name, args)
            for pname, pty in m.params:
                sym[pname] = subst(pty)
            check_block(m.body, sym,
                        expected_ret=subst(m.return_type),
                        in_loop=False,
                        struct_subst=sub_map,
                        method_subst={})

    # ---
    # 6) the main type-checker (expressions + statements)
    #    carries two substitution maps:
    #      - struct_subst: mapping struct-template Tvars→actual (only inside a method inst)
    #      - method_subst: mapping method-template Tvars→actual
    # ---
    def check_block(stmts: list, symbol_table: dict,
                    expected_ret: TypeExpr,
                    in_loop: bool,
                    struct_subst: dict[str,TypeExpr]={},
                    method_subst: dict[str,TypeExpr]={}):

        def subst(ty: TypeExpr) -> TypeExpr:
            # first method‐params, then struct‐params
            if not ty.params:
                if ty.name in method_subst:
                    return method_subst[ty.name]
                if ty.name in struct_subst:
                    return struct_subst[ty.name]
            return TypeExpr(ty.name, [subst(c) for c in ty.params])

        def infer(expr):
            pos = getattr(expr, "pos", None)

            # literals
            if isinstance(expr, Number):
                return TypeExpr("int")
            if isinstance(expr, BooleanLiteral):
                return TypeExpr("boolean")
            if isinstance(expr, NullLiteral):
                return TypeExpr("*")  # null‐pointer wildcard

            # list‐literal sugar (unchanged—uses bare 'list' ctor)
            if isinstance(expr, ListLiteral):
                if not expr.elements:
                    raise SemanticError("Cannot create empty list literal", pos)
                first_ty = infer(expr.elements[0])
                for e in expr.elements[1:]:
                    t = infer(e)
                    if t != first_ty:
                        raise SemanticError(f"List elements must all be {first_ty}, got {t}", e.pos)
                # instantiate `list<…>` if needed
                instantiate_struct("list", [first_ty])
                return TypeExpr("list", [first_ty])

            # variable / this
            if isinstance(expr, Ident):
                if expr.name not in symbol_table:
                    raise SemanticError(f"Undefined variable '{expr.name}'", pos)
                return symbol_table[expr.name]

            # unary/binary (same as before, but `==` can compare pointers/wildcards)
            if isinstance(expr, UnaryOp):
                t = infer(expr.expr)
                if expr.op == "!":
                    if t != TypeExpr("boolean"):
                        raise SemanticError(f"'!' expects boolean, got {t}", pos)
                    return TypeExpr("boolean")
                if expr.op == "-":
                    if t != TypeExpr("int"):
                        raise SemanticError(f"Unary '-' expects int, got {t}", pos)
                    return TypeExpr("int")
                raise SemanticError(f"Unknown unary '{expr.op}'", pos)

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
                    # ints‐ints or pointers‐pointers/null
                    if lt == rt or (lt == TypeExpr("*") and rt not in (TypeExpr("int"),TypeExpr("boolean"))) \
                                or (rt == TypeExpr("*") and lt not in (TypeExpr("int"),TypeExpr("boolean"))):
                        return TypeExpr("boolean")
                    raise SemanticError(f"Cannot compare {lt} {expr.op} {rt}", pos)
                if expr.op in {"&&","||"}:
                    if lt == rt == TypeExpr("boolean"):
                        return TypeExpr("boolean")
                    raise SemanticError(f"Logical '{expr.op}' expects booleans, got {lt},{rt}", pos)
                raise SemanticError(f"Unknown binary '{expr.op}'", pos)

            # --- method call ---
            if isinstance(expr, MethodCall):
                # first infer receiver
                r_ty = subst(infer(expr.receiver))
                expr.struct = r_ty # type: ignore
                # must be a struct instantiation
                if r_ty.name not in struct_templates:
                    raise SemanticError(f"Cannot call method '{expr.method}' on non-struct '{r_ty}'", pos)

                # ensure correct arity & on-demand instantiation
                instantiate_struct(r_ty.name, r_ty.params)

                # find the method declaration
                _, sd = struct_templates[r_ty.name]
                md = next((m for m in sd.methods if m.name == expr.method), None)
                if md is None:
                    raise SemanticError(f"Structure '{r_ty.name}' has no method '{expr.method}'", pos)
                # static vs instance
                if md.is_static:
                    raise SemanticError(f"Cannot call static method '{expr.method}' on instance", pos)

                # type-parameter arity
                if len(expr.type_args) != len(md.type_params):
                    raise SemanticError(
                        f"Method '{r_ty.name}.{md.name}' expects {len(md.type_params)} type-arg(s), got {len(expr.type_args)}",
                        pos
                    )
                # build method_subst & check args
                m_sub = dict(zip(md.type_params, expr.type_args))
                for arg, (pn, pty) in zip(expr.args, md.params):
                    at = infer(arg)
                    expty = subst(pty) if pty.params else subst(pty)
                    if at != expty:
                        raise SemanticError(
                            f"In call to '{r_ty.name}.{md.name}', expected {expty}, got {at}",
                            arg.pos
                        )
                return subst(md.return_type)

            # --- constructor or free function call ---
            if isinstance(expr, FunctionCall):

                
                # constructor?
                if expr.name in struct_templates:
                    # must supply struct-type-args
                    tparams, sd = struct_templates[expr.name]
                    if len(expr.type_args) != len(tparams):
                        raise SemanticError(
                            f"Constructor '{expr.name}' expects {len(tparams)} type-arg(s), got {len(expr.type_args)}",
                            pos
                        )
                    # on-demand instantiate that struct
                    instantiate_struct(expr.name, expr.type_args)

                    # check constructor arity + param types
                    ctor = next((m for m in sd.methods if m.is_static and m.name == expr.name), None)
                    if ctor is None:
                        raise SemanticError(f"No constructor for '{expr.name}'", pos)
 
                    # build a fresh mapping from Tvar -> actual for *this* instantiation
                    ctor_subs = dict(zip(tparams, expr.type_args))
                    def map_ty(ty: TypeExpr) -> TypeExpr:
                        # if it's a type-param, replace it
                        if not ty.params and ty.name in ctor_subs:
                            return ctor_subs[ty.name]
                        # otherwise recurse into any parameters
                        return TypeExpr(ty.name, [map_ty(c) for c in ty.params])
 
                    for arg, (pn, pty) in zip(expr.args, ctor.params):
                        at   = infer(arg)
                        expty = map_ty(pty)
                        if at != expty:
                            raise SemanticError(
                                f"In constructor {expr.name}(), field '{pn}' expects {expty}, got {at}",
                                arg.pos
                            )
                    return TypeExpr(expr.name, expr.type_args)

                # normal free function
                if expr.name not in func_sigs:
                    raise SemanticError(f"Call to undefined function '{expr.name}'", pos)
                tparams, ptypes, rtype = func_sigs[expr.name]

                # generic arity
                if len(expr.type_args) != len(tparams):
                    raise SemanticError(
                        f"Function '{expr.name}' expects {len(tparams)} type-arg(s), got {len(expr.type_args)}",
                        pos
                    )
                # build method_subst for free fn
                f_sub = dict(zip(tparams, expr.type_args))
                # instantiate free function if generic
                inst_key = (expr.name, tuple(expr.type_args))
                if expr.name in generic_funcs and inst_key not in checked_func_insts:
                    checked_func_insts.add(inst_key)
                    fd = next(f for f in func_decls if f.name == expr.name)
                    # check its body once
                    body_sym = {
                        pname: TypeExpr(pty.name, [f_sub.get(c.name,c) for c in pty.params])
                        for pname, pty in zip((p for p,_ in fd.params), ptypes)
                    }
                    check_block(fd.body, body_sym,
                                expected_ret=TypeExpr(rtype.name, [f_sub.get(c.name,c) for c in rtype.params]),
                                in_loop=False,
                                struct_subst={},
                                method_subst=f_sub)

                # now check each arg
                for arg, pty in zip(expr.args, ptypes):
                    at = infer(arg)
                    f_sub = dict(zip(tparams, expr.type_args))

                # helper to apply f_sub to any TypeExpr
                def fsubst(ty: TypeExpr) -> TypeExpr:
                    # if this is a bare type‐param, replace it
                    if not ty.params and ty.name in f_sub:
                        return f_sub[ty.name]
                    # otherwise recurse on its parameters
                    return TypeExpr(ty.name, [fsubst(c) for c in ty.params])

                # now check each argument against the substituted parameter‐type
                for arg, pty in zip(expr.args, ptypes):
                    at    = infer(arg)
                    expty = fsubst(pty)         # ← use fsubst here
                    if at != expty:
                        raise SemanticError(
                            f"In call to '{expr.name}', expected {expty}, got {at}",
                            arg.pos
                        )

                # finally return the substituted return‐type
                return fsubst(rtype)

            # --- field access ---
            if isinstance(expr, MemberAccess):
                # static field?
                if isinstance(expr.obj, Ident) and expr.obj.name in struct_templates:
                    _, sd = struct_templates[expr.obj.name]
                    sf = next((f for f in sd.static_fields if f.name == expr.field), None)
                    if sf is not None:
                        expr.struct = expr.obj # type: ignore
                        expr.is_static_field = True  # type: ignore
                        return sf.type
                # instance field
                r_ty = infer(expr.obj)
                if r_ty.name not in struct_templates:
                    raise SemanticError(f"Cannot access field on non-structure '{r_ty}'", pos)
                instantiate_struct(r_ty.name, r_ty.params)
 
                # pull out the template's own T-parameters:
                tparams, sd = struct_templates[r_ty.name]
                fd = next(f for f in sd.fields if f.name == expr.field)
                expr.struct = r_ty
        
                # build a one-off map { "T" → actual }:
                mapping = dict(zip(tparams, r_ty.params))
                def map_ty(ty: TypeExpr) -> TypeExpr:
                    # if this is a bare template variable, replace:
                    if not ty.params and ty.name in mapping:
                        return mapping[ty.name]
                    # otherwise recurse into its parameters:
                    return TypeExpr(ty.name, [map_ty(c) for c in ty.params])
        
                # now a.value is map_ty(T) → int
                return map_ty(fd.type)

            raise NotImplementedError(f"Cannot infer type of {expr}")

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
                    rt = subst(infer(stmt.expr))
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
                lhs_t = subst(infer(stmt.obj))
                if not hasattr(stmt.obj, "struct"):
                    raise SemanticError("Invalid left-hand side in member assignment", pos)
                rt = subst(infer(stmt.expr))
                if not (rt == lhs_t or (rt == TypeExpr("*") and lhs_t in structs)):
                    raise SemanticError(f"Cannot assign {rt} to field '{stmt.obj.field}' of type {lhs_t}", pos) 
                continue

            if isinstance(stmt, IfStmt):
                ct = infer(stmt.cond)
                if ct != TypeExpr("boolean"):
                    raise SemanticError(f"Condition of if must be boolean, got {ct}", stmt.cond.pos)
                check_block(stmt.then_stmts, symbol_table.copy(), expected_ret, in_loop, struct_subst, method_subst)
                check_block(stmt.else_stmts, symbol_table.copy(), expected_ret, in_loop, struct_subst, method_subst)
                continue

            if isinstance(stmt, ForStmt):
                backup = symbol_table.copy()
                if stmt.init:  check_block([stmt.init], symbol_table, expected_ret, in_loop, struct_subst, method_subst)
                ct = infer(stmt.cond) if stmt.cond else TypeExpr("boolean")
                if stmt.cond and ct != TypeExpr("boolean"):
                    raise SemanticError(f"Condition of for must be boolean, got {ct}", stmt.cond.pos)
                if stmt.post:  check_block([stmt.post], symbol_table, expected_ret, in_loop, struct_subst, method_subst)
                check_block(stmt.body, symbol_table, expected_ret, True, struct_subst, method_subst)
                check_block(stmt.else_body, symbol_table, expected_ret, in_loop, struct_subst, method_subst)
                symbol_table.clear(); symbol_table.update(backup)
                continue

            if isinstance(stmt, WhileStmt):
                ct = infer(stmt.cond)
                if ct != TypeExpr("boolean"):
                    raise SemanticError(f"Condition of while must be boolean, got {ct}", stmt.cond.pos)
                backup = symbol_table.copy()
                check_block(stmt.body, symbol_table, expected_ret, True, struct_subst, method_subst)
                check_block(stmt.else_body, symbol_table, expected_ret, in_loop, struct_subst, method_subst)
                symbol_table.clear(); symbol_table.update(backup)
                continue

            if isinstance(stmt, UntilStmt):
                ct = infer(stmt.cond)
                if ct != TypeExpr("boolean"):
                    raise SemanticError(f"Condition of until must be boolean, got {ct}", stmt.cond.pos)
                backup = symbol_table.copy()
                check_block(stmt.body, symbol_table, expected_ret, True, struct_subst, method_subst)
                check_block(stmt.else_body, symbol_table, expected_ret, in_loop, struct_subst, method_subst)
                symbol_table.clear(); symbol_table.update(backup)
                continue

            if isinstance(stmt, DoStmt):
                if stmt.count is not None:
                    ct = infer(stmt.count)
                    if ct != TypeExpr("int"):
                        raise SemanticError(f"Count in do‐repeat must be int, got {ct}", stmt.count.pos)
                backup = symbol_table.copy()
                check_block(stmt.body, symbol_table, expected_ret, True, struct_subst, method_subst)
                if stmt.cond is not None:
                    ct = infer(stmt.cond)
                    if ct != TypeExpr("boolean"):
                        raise SemanticError(f"Condition of do‐while must be boolean, got {ct}", stmt.cond.pos)
                check_block(stmt.else_body, symbol_table, expected_ret, in_loop, struct_subst, method_subst)
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


        
    for (struct_name, type_args) in list(checked_struct_insts):
        instantiate_struct(struct_name, list(type_args))

    # ---
    # 7) Finally:
    #   a) check every struct‐template’s *definition* has no top-level statements
    #   b) if script-mode, check top_stmts
    #   c) check every free non-generic function body
    # ---
    if "main" in func_sigs and top_stmts:
        raise SemanticError("Top-level statements not allowed when 'main' is defined", top_stmts[0].pos)
    if top_stmts and "main" not in func_sigs:
        check_block(top_stmts, {}, expected_ret=TypeExpr("void"), in_loop=False)

    for fd in func_decls:
        if fd.type_params:
            continue
        sym = { name: ty for name,ty in fd.params }
        check_block(fd.body, sym, expected_ret=fd.return_type, in_loop=False)

        # ensure non-void returns on every path
        def block_returns(bs):
            for s in bs:
                if isinstance(s, ReturnStmt):
                    return True
                if isinstance(s, IfStmt):
                    if block_returns(s.then_stmts) and block_returns(s.else_stmts):
                        return True
            return False

        if fd.return_type != TypeExpr("void") and not block_returns(fd.body):
            raise SemanticError(f"Function '{fd.name}' may exit without returning a value", fd.pos)
