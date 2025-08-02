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
    # --- collect top-level ---
    func_decls = [d for d in program.decls if isinstance(d, FunctionDeclaration)]
    stmts      = [d for d in program.decls if not isinstance(d, (FunctionDeclaration, StructureDeclaration))]

    # --- collect struct defs ---
    structs: dict[str, StructureDeclaration] = {}
    for d in program.decls:
        if isinstance(d, StructureDeclaration):
            if d.name in structs:
                raise SemanticError(f"Structure '{d.name}' redefined", d.pos)
            structs[d.name] = d

    for struct_name, sd in structs.items():
        for sf in sd.static_fields:
            # only literal initializers allowed:
            if isinstance(sf.expr, Number):
                init_t = "int"
            elif isinstance(sf.expr, BooleanLiteral):
                init_t = "boolean"
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
        
    # --- compute memory layouts for constructors ---
    struct_layouts = {
        name: {
            "size":    len(d.fields)*4,
            "offsets": { f.name: i*4 for i,f in enumerate(d.fields) }
        }
        for name,d in structs.items()
    }

    # --- build global function signatures (including print) ---
    func_sigs: dict[str, tuple[list[str], str]] = {}
    func_sigs["print"] = ( ["*"], "void" )   # print(*) → void

    for fd in func_decls:
        if fd.name in func_sigs:
            raise SemanticError(f"Function '{fd.name}' redefined", fd.pos)
        func_sigs[fd.name] = ([ty for _,ty in fd.params], fd.return_type)

    # --- check each struct’s methods ---
    for struct_name, sd in structs.items():
        for m in sd.methods:
            # build the method’s symbol table
            sym = { pname: pty for pname,pty in m.params }

            # only instance‐methods or constructors get a `this`
            is_instance    = not m.is_static
            is_constructor = m.is_static and m.name == struct_name

            if is_instance or is_constructor:
                sym['this'] = struct_name

            # type‐check the body
            check_block(m.body, sym, func_sigs, m.return_type, structs, struct_layouts)

            # methods that return non‐void must return on every path,
            # *except* our constructor (we’ll implicitly return `this`)
            if m.return_type != "void" and not is_constructor and not block_returns(m.body):
                raise SemanticError(
                    f"Method '{struct_name}.{m.name}' may exit without returning a value",
                    m.pos
                )

    # --- top-level vs script mode ---
    if "main" in func_sigs and stmts:
        first = stmts[0]
        raise SemanticError(
            "Top-level statements not allowed when 'main' is defined", first.pos
        )
    if stmts and "main" not in func_sigs:
        check_block(stmts, {}, func_sigs, "void", structs, struct_layouts)

    # --- finally, check every free function body ---
    for fd in func_decls:
        sym = {name: ty for name,ty in fd.params}
        check_block(fd.body, sym, func_sigs, fd.return_type, structs, struct_layouts)
        if fd.return_type != "void" and not block_returns(fd.body):
            raise SemanticError(
                f"Function '{fd.name}' may exit without returning a value", fd.pos
            )


def check_block(stmts, symbol_table, func_sigs, expected_ret,
                structs, struct_layouts, in_loop=False):
    def infer(expr):
        pos = getattr(expr, "pos", None)

        # --- primitives ---
        if isinstance(expr, Number):
            return "int"
        if isinstance(expr, BooleanLiteral):
            return "boolean"

        # --- null literal (`void`) ---
        if isinstance(expr, NullLiteral):
            return "*"   # wildcard pointer

        if isinstance(expr, ListLiteral):
            if not expr.elements:
                raise SemanticError("Cannot create empty list literal", expr.pos)
            # all elements must have same type
            first_ty = infer(expr.elements[0])
            for e in expr.elements[1:]:
                t = infer(e)
                if t != first_ty:
                    raise SemanticError(
                        f"List literal elements must all be {first_ty}, got {t}", e.pos
                    )
            # must have a struct called “list” with a one‐arg constructor
            if "list" not in structs:
                raise SemanticError("No structure 'list' defined for list literal", expr.pos)
            sd = structs["list"]
            ctor = next((m for m in sd.methods if m.name=="list" and m.is_static), None)
            if ctor is None:
                raise SemanticError("Structure 'list' has no constructor", expr.pos)
            # constructor must take exactly one param of that element type
            if len(ctor.params)!=1 or ctor.params[0][1]!=first_ty:
                raise SemanticError(
                  f"Constructor list({ctor.params}) not compatible with element type {first_ty}",
                  expr.pos
                )
            return "list"

        # --- local var or `this` ---
        if isinstance(expr, Ident):
            if expr.name not in symbol_table:
                raise SemanticError(f"Undefined variable '{expr.name}'", pos)
            return symbol_table[expr.name]

        # --- unary / binary ops ---
        if isinstance(expr, UnaryOp):
            t = infer(expr.expr)
            if expr.op == "!":
                if t != "boolean":
                    raise SemanticError(f"Operator '!' expects boolean, got {t}", pos)
                return "boolean"
            if expr.op == "-":
                if t != "int":
                    raise SemanticError(f"Unary '-' expects int, got {t}", pos)
                return "int"
            raise SemanticError(f"Unknown unary operator '{expr.op}'", pos)

        if isinstance(expr, BinOp):
            lt = infer(expr.left)
            rt = infer(expr.right)
            if expr.op in {"+","-","*","/","%"}:
                if lt == rt == "int":
                    return "int"
                raise SemanticError(f"Arithmetic '{expr.op}' expects ints, got {lt},{rt}", pos)
            if expr.op in {"<",">","<=",">="}:
                if lt == rt == "int":
                    return "boolean"
                raise SemanticError(f"Comparison '{expr.op}' expects ints, got {lt},{rt}", pos)
            # pointer‐ or int‐equality
            if expr.op in ("==","!="):
                # ints compare among themselves, or pointers among themselves/null
                if lt == rt or (lt == "*" and rt not in ("int","boolean")) or (rt == "*" and lt not in ("int","boolean")):
                    return "boolean"
                raise SemanticError(f"Cannot compare {lt} {expr.op} {rt}", pos)
            # ordered comparisons only on ints
            if expr.op in ("<",">","<=",">="):
                if lt == rt == "int":
                    return "boolean"
                raise SemanticError(f"Comparison '{expr.op}' expects ints, got {lt},{rt}", pos)
            if expr.op in {"&&","||"}:
                if lt == rt == "boolean":
                    return "boolean"
                raise SemanticError(f"Logical '{expr.op}' expects booleans, got {lt},{rt}", pos)
            raise SemanticError(f"Unknown binary operator '{expr.op}'", pos)

        # --- method calls (static or instance) ---
        if isinstance(expr, MethodCall):
            # static: receiver is a struct name
            if isinstance(expr.receiver, Ident) and expr.receiver.name in structs:
                S = expr.receiver.name
                sd = structs[S]
                md = next((m for m in sd.methods if m.name==expr.method), None)
                if md is None:
                    raise SemanticError(f"Structure '{S}' has no method '{expr.method}'", pos)
                if not md.is_static:
                    raise SemanticError(f"Cannot call instance method '{expr.method}' without an object", pos)
                if len(expr.args) != len(md.params):
                    raise SemanticError(
                        f"Static method '{S}.{expr.method}' expects {len(md.params)} args, got {len(expr.args)}",
                        pos
                    )
                for arg, (pn,pty) in zip(expr.args, md.params):
                    at = infer(arg)
                    if at != pty:
                        raise SemanticError(
                            f"In call to '{S}.{expr.method}', expected {pty}, got {at}",
                            arg.pos
                        )
                expr.struct_name = S
                return md.return_type

            # instance: receiver has a struct type
            r_t = infer(expr.receiver)
            if r_t not in structs:
                raise SemanticError(f"Cannot call method '{expr.method}' on non-struct '{r_t}'", pos)
            sd = structs[r_t]
            md = next((m for m in sd.methods if m.name==expr.method), None)
            if md is None:
                raise SemanticError(f"Structure '{r_t}' has no method '{expr.method}'", pos)
            if md.is_static:
                raise SemanticError(f"Cannot call static method '{expr.method}' on instance", pos)
            if len(expr.args) != len(md.params):
                raise SemanticError(
                    f"Method '{r_t}.{expr.method}' expects {len(md.params)} args, got {len(expr.args)}",
                    pos
                )
            for arg, (pn,pty) in zip(expr.args, md.params):
                at = infer(arg)
                if at != pty:
                    raise SemanticError(
                        f"In call to '{r_t}.{expr.method}', expected {pty}, got {at}",
                        arg.pos
                    )
            expr.struct_name = r_t # type: ignore
            return md.return_type

        # --- free function or constructor calls ---
        if isinstance(expr, FunctionCall):
            # constructor?
            if expr.name in structs:
                sd   = structs[expr.name]
                # look up the user‐declared constructor
                ctor = next((m for m in sd.methods 
                            if m.name == expr.name and m.is_static), None)
                if ctor is None:
                    raise SemanticError(
                        f"Structure '{expr.name}' has no constructor", expr.pos
                    )
                # arity check
                if len(expr.args) != len(ctor.params):
                    raise SemanticError(
                        f"{expr.name}() expects {len(ctor.params)} args, got {len(expr.args)}",
                        expr.pos
                    )
                # type‐check each parameter
                for arg, (pname, pty) in zip(expr.args, ctor.params):
                    at = infer(arg)
                    if at != pty:
                        raise SemanticError(
                        f"In constructor {expr.name}(), field '{pname}' expects {pty}, got {at}",
                        arg.pos
                        )
                # OK—treat it as producing a value of type `expr.name`
                return expr.name

            # normal function
            if expr.name not in func_sigs:
                raise SemanticError(f"Call to undefined function '{expr.name}'", pos)
            ptypes, rtype = func_sigs[expr.name]
            if expr.name == "print":
                if len(expr.args) != 1:
                    raise SemanticError("print() takes exactly one argument", pos)
                at = infer(expr.args[0])
                if at not in ("int","boolean"):
                    raise SemanticError(f"print() only accepts int or boolean, got {at}", expr.args[0].pos)
                return "void"
            if len(expr.args) != len(ptypes):
                raise SemanticError(
                    f"Function '{expr.name}' expects {len(ptypes)} args, got {len(expr.args)}", pos
                )
            for arg,pty in zip(expr.args, ptypes):
                at = infer(arg)
                if at != pty:
                    raise SemanticError(f"In call to '{expr.name}', expected {pty}, got {at}", pos)
            return rtype

        # --- field access ---
        if isinstance(expr, MemberAccess):
            # static‐field access: math.pi
            if isinstance(expr.obj, Ident) and expr.obj.name in structs:
                sd = structs[expr.obj.name]
                sf = next((f for f in sd.static_fields if f.name==expr.field), None)
                if sf is not None:
                    expr.struct_name = expr.obj.name
                    expr.is_static_field = True # type: ignore
                    return sf.type
            obj_t = infer(expr.obj)
            if obj_t not in structs:
                raise SemanticError(f"Cannot access field on non-structure '{obj_t}'", pos)
            sd = structs[obj_t]
            for f in sd.fields:
                if f.name == expr.field:
                    expr.struct_name = obj_t # type: ignore
                    return f.type
            raise SemanticError(f"Structure '{obj_t}' has no field '{expr.field}'", pos)



    # --- now walk statements ---
    for stmt in stmts:
        pos = getattr(stmt, "pos", None)

        if isinstance(stmt, VariableDeclaration):
            if stmt.name in symbol_table:
                raise SemanticError(f"Redeclaration of '{stmt.name}'", pos)
            # void‐typed locals must have no initializer
            if stmt.type == "void":
                if stmt.expr is not None:
                    raise SemanticError(f"Cannot initialize void variable '{stmt.name}'", pos)
                symbol_table[stmt.name] = "void"
            else:
                if stmt.expr is None:
                    raise SemanticError(f"Missing initializer for '{stmt.name}'", pos)
                rt = infer(stmt.expr)
                # allow null -> any struct
                if not (rt == stmt.type or (rt == "*" and stmt.type in structs)):
                    raise SemanticError(f"Cannot assign {rt} to {stmt.type} '{stmt.name}'", pos)
                symbol_table[stmt.name] = stmt.type
            continue

        elif isinstance(stmt, VariableAssignment):
            if stmt.name not in symbol_table:
                raise SemanticError(f"Assignment to undefined '{stmt.name}'", pos)
            lt = symbol_table[stmt.name]
            rt = infer(stmt.expr)
            if not (rt == lt or (rt=="*" and lt in structs)):
                raise SemanticError(f"Cannot assign {rt} to {lt} '{stmt.name}'", pos)
            continue

        elif isinstance(stmt, MemberAssignment):
            # LHS must be MemberAccess
            if getattr(stmt.obj, "is_static_field", False):
                raise SemanticError(f"Cannot assign to static field '{stmt.field}'", stmt.pos)
            lhs_t = infer(stmt.obj)
            if not hasattr(stmt.obj, "struct_name"):
                raise SemanticError("Invalid left-hand side in member assignment", pos)
            rt = infer(stmt.expr)
            if not (rt == lhs_t or (rt=="*" and lhs_t in structs)):
                raise SemanticError(
                    f"Cannot assign {rt} to field '{stmt.obj.field}' of type {lhs_t}", pos
                )
            continue

        elif isinstance(stmt, IfStmt):
            ct = infer(stmt.cond)
            if ct != "boolean":
                raise SemanticError(f"Condition of if must be boolean, got {ct}", stmt.cond.pos)
            check_block(stmt.then_stmts, symbol_table.copy(),
                        func_sigs, expected_ret, structs, struct_layouts, in_loop)
            check_block(stmt.else_stmts, symbol_table.copy(),
                        func_sigs, expected_ret, structs, struct_layouts, in_loop)
            continue

        elif isinstance(stmt, ForStmt):
            table = symbol_table.copy()
            check_block([stmt.init], symbol_table, func_sigs,expected_ret, structs, struct_layouts, in_loop)
            
            ct = infer(stmt.cond)
            if ct != "boolean":
                raise SemanticError(f"Condition of if must be boolean, got {ct}", stmt.cond.pos)
            check_block([stmt.post], symbol_table, func_sigs,expected_ret, structs, struct_layouts, in_loop)
            check_block(stmt.body, symbol_table, func_sigs,expected_ret, structs, struct_layouts, in_loop=True)
            check_block(stmt.else_body, symbol_table, func_sigs,expected_ret, structs, struct_layouts, in_loop)
            symbol_table = table
        
        elif isinstance(stmt, WhileStmt):
            # while (cond) { body } else { else_body }
            ct = infer(stmt.cond)
            if ct != "boolean":
                raise SemanticError(f"Condition of while must be boolean, got {ct}", stmt.cond.pos)
            # body and else-body each get their own copy of the symbol table
            table = symbol_table.copy()
            check_block(stmt.body, table, func_sigs, expected_ret, structs, struct_layouts, in_loop=True)
            check_block(stmt.else_body, table, func_sigs, expected_ret, structs, struct_layouts, in_loop)

        elif isinstance(stmt, UntilStmt):
            # until (cond) { body } else { else_body }
            ct = infer(stmt.cond)
            if ct != "boolean":
                raise SemanticError(f"Condition of until must be boolean, got {ct}", stmt.cond.pos)
            # body and else-body each get their own copy of the symbol table
            table = symbol_table.copy()
            check_block(stmt.body, table, func_sigs, expected_ret, structs, struct_layouts, in_loop=True)
            check_block(stmt.else_body, table, func_sigs, expected_ret, structs, struct_layouts, in_loop)

        elif isinstance(stmt, DoStmt):
            # do [count] { body } [while(cond)] else { else_body }
            if stmt.count is not None:
                ct = infer(stmt.count)
                if ct != "int":
                    raise SemanticError(f"Count in do‐repeat must be int, got {ct}", stmt.count.pos)
            table = symbol_table.copy()
            # body
            check_block(stmt.body, table, func_sigs, expected_ret, structs, struct_layouts, in_loop=True)
            # while‐condition (optional)
            if stmt.cond is not None:
                ct = infer(stmt.cond)
                if ct != "boolean":
                    raise SemanticError(f"Condition of do‐while must be boolean, got {ct}", stmt.cond.pos)
            # else‐body
            check_block(stmt.else_body, table, func_sigs, expected_ret, structs, struct_layouts, in_loop)

        elif isinstance(stmt, BreakStmt):
            if not in_loop:
                raise SemanticError("'break' outside of loop", pos)
            continue
        elif isinstance(stmt, ContinueStmt):
            if not in_loop:
                raise SemanticError("'continue' outside of loop", pos)
            continue

            

        elif isinstance(stmt, ReturnStmt):
            if expected_ret == "void":
                if stmt.expr is not None:
                    raise SemanticError("Cannot return a value from void function", pos)
            else:
                if stmt.expr is None:
                    raise SemanticError(
                        f"Missing return value in function returning '{expected_ret}'", pos
                    )
                rt = infer(stmt.expr)
                if not (rt == expected_ret or (rt=="*" and expected_ret in structs)):
                    raise SemanticError(
                        f"Return type mismatch: expected {expected_ret}, got {rt}", pos
                    )
            continue

        elif isinstance(stmt, FunctionCall) or isinstance(stmt, MethodCall):
            infer(stmt)
            continue


        else:
            infer(stmt)


def block_returns(stmts) -> bool:
    """
    True if every control path unconditionally hits a ReturnStmt.
    """
    for stmt in stmts:
        if isinstance(stmt, ReturnStmt):
            return True
        if isinstance(stmt, IfStmt):
            if block_returns(stmt.then_stmts) and block_returns(stmt.else_stmts):
                return True
    return False