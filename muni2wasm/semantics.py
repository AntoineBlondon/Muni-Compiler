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
    MethodCall
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
    # Partition top-level decls into functions and loose statements
    func_decls = [d for d in program.decls if isinstance(d, FunctionDeclaration)]
    stmts     = [d for d in program.decls if not isinstance(d, (FunctionDeclaration, StructureDeclaration))]
    # collect structure definitions
    structs: dict[str, StructureDeclaration] = {}
    for d in program.decls:
        if isinstance(d, StructureDeclaration):
            if d.name in structs:
                raise SemanticError(f"Structure '{d.name}' redefined", d.pos)
            structs[d.name] = d
    
    struct_layouts = {
        name: {
            "size": len(d.fields)*4,
            "offsets": { f.name: i*4 for i,f in enumerate(d.fields) }
        }
        for name,d in structs.items()
    }



    # Build function signature table
    func_sigs: dict[str, tuple[list[str], str]] = {}
    func_sigs["print"] = ( ["*"], "void" )
    for fd in func_decls:
        if fd.name in func_sigs:
            raise SemanticError(f"Function '{fd.name}' redefined", fd.pos)
        func_sigs[fd.name] = ([ty for _,ty in fd.params], fd.return_type)
    

    for struct_name, sd in structs.items():
        for m in sd.methods:
            sym = {pname:pty for pname,pty in m.params}
            sym['this'] = struct_name
            check_block(m.body, sym, func_sigs, m.return_type, structs, struct_layouts)
            if m.return_type != "void" and not block_returns(m.body):
                raise SemanticError(
                    f"Method '{struct_name}.{m.name}' may exit without returning a value",
                    m.pos
                )


    # If there's a 'main', disallow loose statements
    if "main" in func_sigs and stmts:
        first = stmts[0]
        raise SemanticError("Top-level statements not allowed when 'main' is defined", first.pos)

    # Script mode: no main, but loose stmts → treat as implicit void main
    if stmts and "main" not in func_sigs:
        check_block(stmts, {}, func_sigs, "void", structs, struct_layouts)

    for fd in func_decls:
        symbol_table = {name: ty for name,ty in fd.params}
        check_block(fd.body, symbol_table, func_sigs, fd.return_type, structs, struct_layouts)

        
        if fd.return_type != "void" and not block_returns(fd.body):
            raise SemanticError(
                f"Function '{fd.name}' may exit without returning a value",
                fd.pos
            )



def check_block(stmts, symbol_table, func_sigs, expected_ret, structs, struct_layouts, in_loop=False):
    def infer(expr):
        pos = getattr(expr, "pos", None)
        if isinstance(expr, Number):
            return "int"
        if isinstance(expr, BooleanLiteral):
            return "boolean"
        if isinstance(expr, Ident):
            if expr.name not in symbol_table:
                raise SemanticError(f"Undefined variable '{expr.name}'", pos)
            return symbol_table[expr.name]
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
            op = expr.op
            if op in {"+","-","*","/","%"}:
                if lt == rt == "int":
                    return "int"
                raise SemanticError(f"Arithmetic '{op}' expects ints, got {lt},{rt}", pos)
            if op in {"<",">","<=",">=","==","!="}:
                if lt == rt == "int":
                    return "boolean"
                raise SemanticError(f"Comparison '{op}' expects ints, got {lt},{rt}", pos)
            if op in {"&&","||"}:
                if lt == rt == "boolean":
                    return "boolean"
                raise SemanticError(f"Logical '{op}' expects booleans, got {lt},{rt}", pos)
            raise SemanticError(f"Unknown binary operator '{op}'", pos)

        if isinstance(expr, MethodCall):
            # two cases:  
            # (A) static call: receiver is the struct name itself  
            # (B) instance call: receiver is an expression of struct type

            # try static first
            if isinstance(expr.receiver, Ident) and expr.receiver.name in structs:
                struct_name = expr.receiver.name
                sd = structs[struct_name]
                # find the method
                md = next((m for m in sd.methods if m.name == expr.method), None)
                if md is None:
                    raise SemanticError(
                        f"Structure '{struct_name}' has no method '{expr.method}'",
                        expr.pos
                    )
                if not md.is_static:
                    raise SemanticError(
                        f"Cannot call instance method '{expr.method}' without an object",
                        expr.pos
                    )
                # check args
                if len(expr.args) != len(md.params):
                    raise SemanticError(
                        f"Static method '{struct_name}.{expr.method}' expects {len(md.params)} args, got {len(expr.args)}",
                        expr.pos
                    )
                for arg, (pname, pty) in zip(expr.args, md.params):
                    at = infer(arg)
                    if at != pty:
                        raise SemanticError(
                            f"In call to '{struct_name}.{expr.method}', expected {pty}, got {at}",
                            arg.pos
                        )
                expr.struct_name = struct_name
                return md.return_type

            # otherwise instance call
            r_t = infer(expr.receiver)
            if r_t not in structs:
                raise SemanticError(
                    f"Cannot call method '{expr.method}' on non-struct '{r_t}'",
                    expr.pos
                )
            sd = structs[r_t]
            md = next((m for m in sd.methods if m.name == expr.method), None)
            if md is None:
                raise SemanticError(
                    f"Structure '{r_t}' has no method '{expr.method}'",
                    expr.pos
                )
            if md.is_static:
                raise SemanticError(
                    f"Cannot call static method '{expr.method}' on instance",
                    expr.pos
                )
            # check args
            if len(expr.args) != len(md.params):
                raise SemanticError(
                    f"Method '{r_t}.{expr.method}' expects {len(md.params)} args, got {len(expr.args)}",
                    expr.pos
                )
            for arg, (pname, pty) in zip(expr.args, md.params):
                at = infer(arg)
                if at != pty:
                    raise SemanticError(
                        f"In call to '{r_t}.{expr.method}', expected {pty}, got {at}",
                        arg.pos
                    )
            expr.struct_name = r_t # type: ignore
            return md.return_type

        if isinstance(expr, FunctionCall):
            # --- struct constructor? ---
            if expr.name in struct_layouts:
                layout = struct_layouts[expr.name]
                fields = structs[expr.name].fields
                # arity check
                if len(expr.args) != len(fields):
                    raise SemanticError(
                      f"{expr.name}() expects {len(fields)} args, got {len(expr.args)}",
                      expr.pos
                    )
                # every arg must match the declared field type
                for arg, fld in zip(expr.args, fields):
                    at = infer(arg)
                    if at != fld.type:
                        raise SemanticError(
                          f"In constructor {expr.name}(), field '{fld.name}' "
                          f"expects {fld.type}, got {at}",
                          arg.pos
                        )
                # type of this expr is the struct‘s name
                return expr.name

            # --- otherwise fall back to real function ---
            if expr.name not in func_sigs:
                raise SemanticError(f"Call to undefined function '{expr.name}'", pos)
            param_types, ret_type = func_sigs[expr.name]
            if expr.name == "print":
                if len(expr.args) != 1:
                    raise SemanticError(f"print() takes exactly one argument", pos)
                arg_t = infer(expr.args[0])
                if arg_t not in ("int","boolean"):
                    raise SemanticError(f"print() only accepts int or boolean, got {arg_t}", expr.args[0].pos)
                return "void"
            if len(expr.args) != len(param_types):
                raise SemanticError(
                    f"Function '{expr.name}' expects {len(param_types)} args, got {len(expr.args)}",
                    pos
                )
            for arg, pty in zip(expr.args, param_types):
                at = infer(arg)
                if at != pty:
                    raise SemanticError(
                        f"In call to '{expr.name}', expected {pty}, got {at}",
                        getattr(arg, "pos", None)
                    )
            return ret_type
        if isinstance(expr, MemberAccess):
            # get object’s type
            obj_t = infer(expr.obj)
            if obj_t not in structs:
                raise SemanticError(f"Cannot access field on non-structure '{obj_t}'", expr.pos)
            struct_def = structs[obj_t]
            # find the field; also remember the struct on the node
            for f in struct_def.fields:
                if f.name == expr.field:
                    expr.struct_name = obj_t    # annotate for codegen # type: ignore
                    return f.type
            raise SemanticError(f"Structure '{obj_t}' has no field '{expr.field}'", expr.pos)
    for stmt in stmts:
        pos = getattr(stmt, "pos", None)

        if isinstance(stmt, VariableDeclaration):
            if stmt.name in symbol_table:
                raise SemanticError(f"Redeclaration of '{stmt.name}'", pos)
            if stmt.type == "void":
                if stmt.expr is not None:
                    raise SemanticError(f"Cannot initialize void variable '{stmt.name}'", pos)
                symbol_table[stmt.name] = "void"
            else:
                if stmt.expr is None:
                    raise SemanticError(f"Missing initializer for '{stmt.name}'", pos)
                rt = infer(stmt.expr)
                if rt != stmt.type:
                    raise SemanticError(f"Cannot assign {rt} to {stmt.type} '{stmt.name}'", pos)
                symbol_table[stmt.name] = stmt.type

        elif isinstance(stmt, VariableAssignment):
            if stmt.name not in symbol_table:
                raise SemanticError(f"Assignment to undefined '{stmt.name}'", pos)
            lt = symbol_table[stmt.name]
            if lt == "void":
                raise SemanticError(f"Cannot assign to void variable '{stmt.name}'", pos)
            rt = infer(stmt.expr)
            if rt != lt:
                raise SemanticError(f"Cannot assign {rt} to {lt} '{stmt.name}'", pos)

        elif isinstance(stmt, MemberAssignment):
             # LHS must be a MemberAccess whose type we already annotated
             lhs_t = infer(stmt.obj)
             # ensure field exists and record came from semantics
             if not isinstance(stmt.obj, MemberAccess) or not hasattr(stmt.obj, "struct_name"):
                 raise SemanticError(f"Invalid left‐hand side in member assignment", stmt.pos)
             # now check RHS type matches
             rt = infer(stmt.expr)
             if rt != lhs_t:
                 raise SemanticError(
                     f"Cannot assign {rt} to field '{stmt.obj.field}' of type {lhs_t}",
                     stmt.pos
                 )
        elif isinstance(stmt, IfStmt):
            ct = infer(stmt.cond)
            if ct != "boolean":
                raise SemanticError(f"Condition of if must be boolean, got {ct}", stmt.cond.pos)
            # use a copy of symbol_table so inner blocks can't leak declarations
            check_block(stmt.then_stmts, symbol_table.copy(), func_sigs, expected_ret, structs, struct_layouts, in_loop)
            check_block(stmt.else_stmts, symbol_table.copy(), func_sigs, expected_ret, structs, struct_layouts, in_loop)

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
                    raise SemanticError(f"Missing return value in function returning '{expected_ret}'", pos)
                rt = infer(stmt.expr)
                if rt != expected_ret:
                    raise SemanticError(f"Return type mismatch: expected {expected_ret}, got {rt}", pos)
        elif isinstance(stmt, FunctionCall):
            # bare call as statement
            infer(stmt)
        elif isinstance(stmt, MethodCall):
            # bare method‐call as statement
            infer(stmt)
        
        else:
            infer(stmt)


def block_returns(stmts) -> bool:
    """
    Returns True if every control‐path in this list of stmts
    is guaranteed to hit a ReturnStmt (no fall‐through).
    """
    for stmt in stmts:
        if isinstance(stmt, ReturnStmt):
            return True
        if isinstance(stmt, IfStmt):
            # both branches must return
            then_ret = block_returns(stmt.then_stmts)
            else_ret = block_returns(stmt.else_stmts)
            if then_ret and else_ret:
                return True
        # other statements do not guarantee return, continue scanning
    return False