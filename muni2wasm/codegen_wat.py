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
    MethodDeclaration,
    MethodCall,
    NullLiteral,
    ListLiteral,
    ImportDeclaration,
    TypeExpr
)

class CodeGen:
    def __init__(self, program: Program):
        self.program = program
        self.struct_layouts: dict[str, dict] = {}
        self.out: list[str] = []
        self._label_count = 0
        # Stack of (break_label, continue_label, exit_label)
        self._loop_stack: list[tuple[str, str, str]] = []
        # map (struct_name, tuple[type_arg_names]) -> True
        self.struct_insts: dict[tuple[str,tuple[str,...]], bool] = {}
        # same for free generic functions
        self.fn_insts: dict[tuple[str,tuple[str,...]], bool] = {}

    def _fresh_label(self, base: str) -> str:
        lbl = f"${base}_{self._label_count}"
        self._label_count += 1
        return lbl

    def gen(self) -> str:
        self.out = ["(module"]
        
            

        for imp in self.program.decls:
            if isinstance(imp, ImportDeclaration) and imp.source is None:
                # host import (ignore any type-parameters)
                param_decl = " ".join("i32" for _ in imp.params)
                # imp.return_type might be a string or a TypeExpr
                rt = imp.return_type.name if hasattr(imp.return_type, "name") else imp.return_type # type: ignore
                result_decl = "" if rt == "void" else "(result i32)"
                self.out.append(
                    f'  (import "{imp.module}" "{imp.name}" '
                    f'(func ${imp.name} (param {param_decl}) {result_decl}))'
                )
        
        self.out.extend([
            "  (memory $mem 1)",
            "  (global $heap (mut i32) (i32.const 4))",
            "  (func $malloc (param $n i32) (result i32)",
            "    global.get $heap",
            "    global.get $heap",
            "    local.get $n",
            "    i32.add",
            "    global.set $heap",
            "  )",
            '  (export "memory" (memory $mem))',
            '  (export "malloc" (func $malloc))',
        ])

        for d in self.program.decls:
            if isinstance(d, StructureDeclaration):
                self.struct_insts[(d.name, ())] = True

        # 1) collect struct layouts
        for d in self.program.decls:
            if isinstance(d, StructureDeclaration):
                self._collect_struct(d)


        # --- emit all static‐struct fields as immutable globals ---
        for d in self.program.decls:
            if isinstance(d, StructureDeclaration):
                for sf in d.static_fields:
                    # sf.expr is either Number or BooleanLiteral
                    if isinstance(sf.expr, Number):
                        val = sf.expr.value
                    else:
                        # boolean: true→1, false→0
                        val = 1 if sf.expr.value else 0
                    self.out.append(
                        f'  (global ${d.name}_{sf.name} i32 (i32.const {val}))'
                    )

       

        # 2) emit struct‐template constructors (they are static, no mangle)
        for sd in self.program.decls:
            if isinstance(sd, StructureDeclaration):
                ctor = next((m for m in sd.methods if m.is_static and m.name == sd.name), None)
                if ctor:
                     self.gen_method(sd.name, ctor)  # the raw “template” ctor

        # 2b) now monomorphize every specialization we actually used:
        

        # 3) emit free **monomorphic** fns now
        for fd in self.program.decls:
            if isinstance(fd, FunctionDeclaration) and not fd.type_params:
                self.gen_func(fd)

        # 4) emit **monomorphized struct instance‐methods**
        for (struct_name, targs) in self.struct_insts:
            # find the decl
            sd = next(d for d in self.program.decls
                    if isinstance(d, StructureDeclaration) and d.name == struct_name)

            # for each *instance* method:
            for m in sd.methods:
                if m.is_static and m.name==struct_name:
                    continue
                # give gen_method the type_args
                self.gen_method(struct_name, m,
                                type_args=[TypeExpr(n) for n in targs])
        
        for (fn, targs) in self.fn_insts:
            fd = next(f for f in self.program.decls
                if isinstance(f,FunctionDeclaration) and f.name==fn)
            self.gen_func(fd, type_args=[TypeExpr(n) for n in targs])
        
        #     for ('list', ('int',)), emit a ctor called $list_list__int
        for (struct_name, targs) in list(self.struct_insts):
            if not targs:
                continue
            sd = next(d for d in self.program.decls
                      if isinstance(d, StructureDeclaration) and d.name == struct_name)
            ctor = next((m for m in sd.methods if m.is_static and m.name == struct_name), None)
            if ctor:
                # turn ["int"] → [ TypeExpr("int") ]
                tas = [TypeExpr(n) for n in targs]
                self.gen_method(struct_name, ctor, type_args=tas)
        
        for sd in self.program.decls:
            if isinstance(sd, StructureDeclaration):
                for m in sd.methods:
                    if m.is_static and m.name != sd.name:
                        self.gen_method(sd.name, m, type_args=[])
        # export main if present
        if any(isinstance(d, FunctionDeclaration) and d.name == "main"
               for d in self.program.decls):
            self.out.append('  (export "main" (func $main))')

        self.out.append(")")
        return "\n".join(self.out)

    def _collect_struct(self, sd: StructureDeclaration):
        size = len(sd.fields) * 4
        offsets = {f.name: idx * 4 for idx, f in enumerate(sd.fields)}
        self.struct_layouts[sd.name] = {"size": size, "offsets": offsets}

    def gen_method(self, struct_name: str, m: MethodDeclaration, type_args = None):
        self.locals = []
        self.code   = []

        type_args = type_args or []
        raw_name = f"{struct_name}_{m.name}"
        fn_name  = self._mangle(raw_name, type_args)

        # 1) figure out if this is (a) an instance-method or (b) our constructor
        is_instance    = not m.is_static
        is_constructor = m.is_static and m.name == struct_name

        # 2) build the parameter list
        params = []
        if is_instance or is_constructor:
            params.append("(param $this i32)")
        for pname, _ in m.params:
            params.append(f"(param ${pname} i32)")

        # 3) return signature
        result_decl = "" if m.return_type == TypeExpr("void") else "(result i32)"

        # 4) gather locals (excluding parameters)
        for s in m.body:
            if isinstance(s, VariableDeclaration) and s.type != TypeExpr("void"):
                self.locals.append(s.name)
        # a scratch local for things like `do { … }`
        self.locals.append("__struct_ptr")
        self.locals.append("__lit") 

        locals_decl = " ".join(f"(local ${n} i32)" for n in self.locals)

        # 5) emit the function header
        header = f"  (func ${fn_name} {' '.join(params)} {result_decl} {locals_decl}"
        self.out.append(header)

        # 6) emit the body
        for stmt in m.body:
            self.gen_stmt(stmt)

        # 7) emit the tail
        if is_constructor:
            # constructors implicitly return `this`
            self.emit("local.get $this")
            self.emit("return")
        elif m.return_type == TypeExpr("void"):
            self.emit("return")
        else:
            # non-void methods must return explicitly on every path, unreachable otherwise
            self.emit("unreachable")

        # 8) splice in the generated instructions and close
        self.out.extend(self.code)
        self.out.append("  )")


    def gen_func(self, func: FunctionDeclaration, type_args=None):
        
        self.locals = ["__struct_ptr", "__lit"]
        self.code = []
        raw = func.name
        name = self._mangle(raw, type_args or [])

        # recursively collect locals
        def scan(s):
            from .ast import VariableDeclaration, IfStmt, ForStmt, WhileStmt, DoStmt, UntilStmt
            if isinstance(s, VariableDeclaration) and s.type != TypeExpr("void"):
                if s.name not in self.locals:
                    self.locals.append(s.name)
            elif isinstance(s, IfStmt):
                for t in s.then_stmts + s.else_stmts:
                    scan(t)
            elif isinstance(s, (WhileStmt, UntilStmt)):
                for t in s.body + s.else_body:
                    scan(t)
            elif isinstance(s, ForStmt):
                if s.init:   scan(s.init)
                if s.post:   scan(s.post)
                for t in s.body + s.else_body:
                    scan(t)
            elif isinstance(s, DoStmt):
                for t in s.body + s.else_body:
                    scan(t)

        for st in func.body:
            scan(st)

        params_decl = " ".join(f"(param ${n} i32)" for n, _ in func.params)
        result_decl = "" if func.return_type == TypeExpr("void") else "(result i32)"
        locals_decl = " ".join(f"(local ${n} i32)" for n in self.locals)

        hdr = f"  (func ${name} {params_decl} {result_decl} {locals_decl}"
        self.out.append(hdr)

        for st in func.body:
            self.gen_stmt(st)

        self.emit("return" if func.return_type == TypeExpr("void") else "unreachable")
        self.out.extend(self.code)
        self.out.append("  )")

    def gen_stmt(self, stmt):
        # VariableDeclaration


        if isinstance(stmt, VariableDeclaration):
            if stmt.expr is not None:
                self.gen_expr(stmt.expr)
                self.emit(f"local.set ${stmt.name}")
            return

        # VariableAssignment
        if isinstance(stmt, VariableAssignment):
            self.gen_expr(stmt.expr)
            self.emit(f"local.set ${stmt.name}")
            return

        # MemberAssignment
        if isinstance(stmt, MemberAssignment):
            self.gen_expr(stmt.obj.obj)
            self.gen_expr(stmt.expr)
            off = self.struct_layouts[stmt.obj.struct.name]["offsets"][stmt.field]
            self.emit(f"i32.store offset={off}")
            return

        # ReturnStmt
        if isinstance(stmt, ReturnStmt):
            if stmt.expr:
                self.gen_expr(stmt.expr)
            self.emit("return")
            return

        # Bare FunctionCall
        if isinstance(stmt, FunctionCall):
            self.gen_expr(stmt)
            return

        # Bare MethodCall
        if isinstance(stmt, MethodCall):
            self.gen_expr(stmt)
            return

        # IfStmt
        if isinstance(stmt, IfStmt):
            self.gen_expr(stmt.cond)
            self.emit("if")
            for t in stmt.then_stmts:
                self.gen_stmt(t)
            if stmt.else_stmts:
                self.emit("else")
                for e in stmt.else_stmts:
                    self.gen_stmt(e)
            self.emit("end")
            return

        # ForStmt with proper continue placement
        if isinstance(stmt, ForStmt):
            saved = list(self.locals)
            if isinstance(stmt.init, VariableDeclaration):
                self.locals.append(stmt.init.name)
            # init runs once
            if stmt.init:
                self.gen_stmt(stmt.init)

            br_lbl   = self._fresh_label("for_break")
            cont_lbl = self._fresh_label("for_cont")
            exit_lbl = self._fresh_label("for_exit")
            loop_lbl = self._fresh_label("for_loop")
            self._loop_stack.append((br_lbl, cont_lbl, exit_lbl))

            self.emit(f"block {br_lbl}")   # break target
            self.emit(f"block {exit_lbl}")  # exit-to-else
            self.emit(f"loop {loop_lbl}")   # loop header

            # condition
            if stmt.cond:
                self.gen_expr(stmt.cond)
                self.emit("i32.eqz")
                self.emit(f"br_if {exit_lbl}")

            # continue target wraps the body
            self.emit(f"block {cont_lbl}")
            for b in stmt.body:
                self.gen_stmt(b)
            self.emit("end")  # end continue block

            # post-statement
            if stmt.post:
                self.gen_stmt(stmt.post)

            # back to loop header
            self.emit(f"br {loop_lbl}")
            self.emit("end")  # end loop
            self.emit("end")  # end exit

            # else-body
            for e in stmt.else_body:
                self.gen_stmt(e)
            self.emit("end")  # end break

            self._loop_stack.pop()
            self.locals = saved
            return

        # WhileStmt
        if isinstance(stmt, WhileStmt):
            saved = list(self.locals)
            br_lbl, cont_lbl, exit_lbl = (
                self._fresh_label("while_break"),
                None,  # continue jumps to loop header
                self._fresh_label("while_exit")
            )
            loop_lbl = self._fresh_label("while_loop")
            cont_lbl = loop_lbl
            self._loop_stack.append((br_lbl, cont_lbl, exit_lbl))

            self.emit(f"block {br_lbl}")
            self.emit(f"block {exit_lbl}")
            self.emit(f"loop {loop_lbl}")

            self.gen_expr(stmt.cond)
            self.emit("i32.eqz")
            self.emit(f"br_if {exit_lbl}")

            for b in stmt.body:
                self.gen_stmt(b)

            self.emit(f"br {loop_lbl}")
            self.emit("end")
            self.emit("end")

            for e in stmt.else_body:
                self.gen_stmt(e)
            self.emit("end")

            self._loop_stack.pop()
            self.locals = saved
            return

        # UntilStmt
        if isinstance(stmt, UntilStmt):
            saved = list(self.locals)
            br_lbl, cont_lbl, exit_lbl = (
                self._fresh_label("until_break"),
                None,
                self._fresh_label("until_exit")
            )
            loop_lbl = self._fresh_label("until_loop")
            cont_lbl = loop_lbl
            self._loop_stack.append((br_lbl, cont_lbl, exit_lbl))

            self.emit(f"block {br_lbl}")
            self.emit(f"block {exit_lbl}")
            self.emit(f"loop {loop_lbl}")

            self.gen_expr(stmt.cond)
            self.emit(f"br_if {exit_lbl}")

            for b in stmt.body:
                self.gen_stmt(b)
            self.emit(f"br {loop_lbl}")

            self.emit("end")
            self.emit("end")

            for e in stmt.else_body:
                self.gen_stmt(e)
            self.emit("end")

            self._loop_stack.pop()
            self.locals = saved
            return

        # DoStmt
        if isinstance(stmt, DoStmt):
            saved = list(self.locals)
            br_lbl, cont_lbl, _ = (
                self._fresh_label("do_break"),
                None,
                None
            )
            loop_lbl = self._fresh_label("do_loop")
            cont_lbl = loop_lbl
            self._loop_stack.append((br_lbl, cont_lbl, None))  # type: ignore

            self.emit(f"block {br_lbl}")
            if stmt.count is None:
                stmt.count = Number("1")

            if stmt.count is not None:
                self.gen_expr(stmt.count)
                self.emit("local.set $__struct_ptr")
                self.emit(f"loop {loop_lbl}")
                for b in stmt.body:
                    self.gen_stmt(b)
                self.emit("local.get $__struct_ptr")
                self.emit("i32.const 1")
                self.emit("i32.sub")
                self.emit("local.tee $__struct_ptr")
                self.emit(f"br_if {loop_lbl}")
                self.emit("end")

            if stmt.cond is not None:
                self.emit(f"loop {loop_lbl}")
                for b in stmt.body:
                    self.gen_stmt(b)
                self.gen_expr(stmt.cond)
                self.emit(f"br_if {loop_lbl}")
                self.emit("end")

            for e in stmt.else_body:
                self.gen_stmt(e)
            self.emit("end")

            self._loop_stack.pop()
            self.locals = saved
            return

        # BreakStmt
        if isinstance(stmt, BreakStmt):
            if not self._loop_stack:
                raise RuntimeError("`break` outside loop")
            br_lbl, _, _ = self._loop_stack[-1]
            self.emit(f"br {br_lbl}")
            return

        # ContinueStmt
        if isinstance(stmt, ContinueStmt):
            if not self._loop_stack:
                raise RuntimeError("`continue` outside loop")
            _, cont_lbl, _ = self._loop_stack[-1]
            self.emit(f"br {cont_lbl}")
            return

        raise NotImplementedError(f"Cannot codegen statement: {stmt}")

    def gen_expr(self, expr):
        if isinstance(expr, Number):
            self.emit(f"i32.const {expr.value}")
        elif isinstance(expr, BooleanLiteral):
            self.emit(f"i32.const {1 if expr.value else 0}")
        elif isinstance(expr, ListLiteral):
            # --- head node ---
            head_call = FunctionCall("list", [], [expr.elements[0]], pos=expr.pos)
            self.gen_expr(head_call)         # alloc + constructor
            self.emit("local.set $__lit")    # store head in $__lit

            # --- link remaining elements ---
            for elt in expr.elements[1:]:
                node_call = FunctionCall("list", [], [elt], pos=expr.pos)
                self.gen_expr(node_call)     # alloc + constructor
                self.emit("local.set $__struct_ptr")

                # __lit.append(__struct_ptr)
                self.emit("local.get $__lit")
                self.emit("local.get $__struct_ptr")
                self.emit("call $list_append")

            # --- result of the literal is the head ptr ---
            self.emit("local.get $__lit")
            return
        elif isinstance(expr, NullLiteral):
            self.emit("i32.const 0")
        elif isinstance(expr, Ident):
            self.emit(f"local.get ${expr.name}")
        elif isinstance(expr, UnaryOp):
            if expr.op == "!":
                self.gen_expr(expr.expr)
                self.emit("i32.eqz")
            else:
                self.emit("i32.const 0")
                self.gen_expr(expr.expr)
                self.emit("i32.sub")
        elif isinstance(expr, BinOp):
            self.gen_expr(expr.left)
            self.gen_expr(expr.right)
            opmap = {
                "||": "i32.or", "&&": "i32.and",
                "==": "i32.eq", "!=": "i32.ne",
                "<":  "i32.lt_s", "<=": "i32.le_s",
                ">":  "i32.gt_s", ">=": "i32.ge_s",
                "+":  "i32.add", "-":  "i32.sub",
                "*":  "i32.mul", "/":  "i32.div_s", "%": "i32.rem_s",
            }
            self.emit(opmap[expr.op])
        # static‐field access (math.pi → global.get $math_pi)
        elif isinstance(expr, MemberAccess) and getattr(expr, "is_static_field", False):
            self.emit(f"global.get ${expr.struct}_{expr.field}")
            return

        # instance‐field access
        elif isinstance(expr, MemberAccess):
            self.gen_expr(expr.obj)
            struct_name = ""
            if expr.struct:
                struct_name = expr.struct.name
            off = self.struct_layouts[struct_name]["offsets"][expr.field]
            self.emit(f"i32.load offset={off}")
            return
        
        
        elif isinstance(expr, MethodCall):
            # we rely on the semantic pass having set `expr.struct`
            struct_ty: TypeExpr = expr.struct    # e.g. TypeExpr("list", [TypeExpr("int")]) # type: ignore
            base   = struct_ty.name               # "list"
            targs  = struct_ty.params             # [ TypeExpr("int") ]
            # record that we need to monomorphize its methods
            key = (base, tuple(ta.name for ta in targs))
            self.struct_insts[key] = True

            # mangle <struct>_<method>__<targs…>
            mangled = self._mangle(f"{base}_{expr.method}", targs)

            # emit receiver + all args
            self.gen_expr(expr.receiver)
            for arg in expr.args:
                self.gen_expr(arg)
            self.emit(f"call ${mangled}")
            return

        # --- struct‐constructor (monomorphic or generic) ---
        elif isinstance(expr, FunctionCall) and expr.name in self.struct_layouts:
            # register for monomorphization
            key = (expr.name, tuple(ta.name for ta in expr.type_args))
            self.struct_insts[key] = True

            # the constructor was emitted as `<struct>_<struct>__<targs>` (or just `<struct>_<struct>` when no targs)
            raw_ctor = f"{expr.name}_{expr.name}"
            mangled_ctor = self._mangle(raw_ctor, expr.type_args)
            layout = self.struct_layouts[expr.name]
 

            # malloc(layout.size)
            self.emit(f"i32.const {layout['size']}")
            self.emit("call $malloc")
            self.emit("local.set $__struct_ptr")

            # call ctor(ptr, …args)
            self.emit("local.get $__struct_ptr")
            for arg in expr.args:
                self.gen_expr(arg)
            self.emit(f"call ${mangled_ctor}")
            return
        
        elif isinstance(expr, FunctionCall) and expr.type_args:
            key = (expr.name, tuple(ta.name for ta in expr.type_args))
            self.fn_insts[key] = True
            mangled = self._mangle(expr.name, expr.type_args)
            # emit the mangled call…
            for arg in expr.args:
                self.gen_expr(arg)
            self.emit(f"call ${mangled}")
            return
        elif isinstance(expr, FunctionCall):
            for a in expr.args:
                self.gen_expr(a)
            self.emit(f"call ${expr.name}")
        else:
            raise NotImplementedError(f"Cannot codegen expression: {expr}")

    def emit(self, instr: str):
        self.code.append(f"    {instr}")
    
    def _mangle(self, base: str, type_args: list[TypeExpr]) -> str:
        if not type_args:
            return base
        suffix = "_".join(arg.name for arg in type_args)
        return f"{base}__{suffix}"
