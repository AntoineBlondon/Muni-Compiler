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
        # 1) host imports
        for imp in self.program.decls:
            if isinstance(imp, ImportDeclaration) and imp.source is None:
                param_decl = " ".join("i32" for _ in imp.params)
                rt = imp.return_type.name if hasattr(imp.return_type, "name") else imp.return_type # type: ignore
                result_decl = "" if rt == "void" else "(result i32)"
                self.out.append(
                    f'  (import "{imp.module}" "{imp.name}" '
                    f'(func ${imp.name} (param {param_decl}) {result_decl}))'
                )

        # 2) memory + malloc
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

        # 4) collect all struct layouts
        for d in self.program.decls:
            if isinstance(d, StructureDeclaration):
                self._collect_struct(d)

        # 5) emit static‐struct fields
        for d in self.program.decls:
            if isinstance(d, StructureDeclaration):
                for sf in d.static_fields:
                    val = sf.expr.value if isinstance(sf.expr, Number) else (1 if sf.expr.value else 0)
                    self.out.append(
                        f'  (global ${d.name}_{sf.name} i32 (i32.const {val}))'
                    )
        for sd in self.program.decls:
            if not isinstance(sd, StructureDeclaration):
                continue

            # 1) the “template” ctor: list<T>(…) → $list_list
            ctor = next((m for m in sd.methods if m.is_static and m.name == sd.name), None)
            if ctor:
                self.gen_method(sd.name, ctor, type_args=[])

            # 2) any other static helpers (append, set, #print…)
            for m in sd.methods:
                if m.is_static and m.name != sd.name:
                    self.gen_method(sd.name, m, type_args=[])

        # 6) emit all free, non-generic functions
        for fd in self.program.decls:
            if isinstance(fd, FunctionDeclaration) and not fd.type_params:
                self.gen_func(fd)

        # 7) monomorphize every used struct<…>
        #    (including the empty-targs case)
        # — but first, drop any instantiation that is _just_ the struct’s own type‐vars.
        #    i.e. ('list',('T',)) → skip
        #
        # build a map from struct → its declared type‐params
        template_tparams = {
            sd.name: sd.type_params
            for sd in self.program.decls
            if isinstance(sd, StructureDeclaration)
        }

        filtered = {}
        for (sname, targs), used in self.struct_insts.items():
            # if these targs exactly match the struct’s own T‐vars, skip
            if template_tparams.get(sname, []) == list(targs):
                continue
            filtered[(sname, targs)] = True
        self.struct_insts = filtered

    
        # now emit each concrete instantiation:
        for struct_name, targs in list(self.struct_insts):
            # find the StructureDeclaration
            sd = next(d for d in self.program.decls
                    if isinstance(d, StructureDeclaration) and d.name == struct_name)
            # build TypeExpr list
            tas = [TypeExpr(n) for n in targs]

            # 7a) static constructor for this instantiation
            ctor = next((m for m in sd.methods if m.is_static and m.name == struct_name), None)
            if ctor:
                self.gen_method(struct_name, ctor, type_args=tas)

            # 7b) instance methods for this instantiation
            for m in sd.methods:
                if not m.is_static:
                    self.gen_method(struct_name, m, type_args=tas)

            # 7c) any other static helpers (e.g. static methods not named ctor)
            for m in sd.methods:
                if m.is_static and m.name != struct_name:
                    self.gen_method(struct_name, m, type_args=tas)

        # 8) monomorphize any generic free functions
        for fn, targs in list(self.fn_insts):
            fd = next(f for f in self.program.decls
                    if isinstance(f, FunctionDeclaration) and f.name == fn)
            self.gen_func(fd, type_args=[TypeExpr(n) for n in targs])

        # 9) export main if present
        if any(isinstance(d, FunctionDeclaration) and d.name == "main"
            for d in self.program.decls):
            self.out.append('  (export "main" (func $main))')

        # 10) finish module
        self.out.append(")")
        return "\n".join(self.out)


    def _collect_struct(self, sd: StructureDeclaration):
        size = len(sd.fields) * 4
        offsets = {f.name: idx * 4 for idx, f in enumerate(sd.fields)}
        self.struct_layouts[sd.name] = {"size": size, "offsets": offsets}

    def gen_method(self, struct_name: str, m: MethodDeclaration, type_args=None):
        #print(f"[DEBUG] Generating method {m.name} for struct {struct_name} with type args {[*map(str, type_args)]}") # type: ignore
        self.current_struct = struct_name
        self.current_targs  = [ta.name for ta in (type_args or [])]
        self.current_method = m.name
        # reset per-method state
        self.code = []

        type_args = type_args or []
        # Look up the original template’s type-param names:
        sd = next(d for d in self.program.decls
                  if isinstance(d, StructureDeclaration) and d.name == struct_name)
        # Build a map Tvar → actual (e.g. "T" → TypeExpr("int"))
        self._tv_map = { tv: ta for tv, ta in zip(sd.type_params, type_args) }

        # mangle the name
        type_args = type_args or []
        raw_name = f"{struct_name}_{m.name}"
        fn_name = self._mangle(raw_name, type_args)

        # determine instance vs constructor
        is_instance    = not m.is_static
        is_constructor = m.is_static and m.name == struct_name

        # build parameter list
        params = []
        if is_instance or is_constructor:
            params.append("(param $this i32)")
        for pname, _ in m.params:
            params.append(f"(param ${pname} i32)")

        # return signature
        result_decl = "" if m.return_type == TypeExpr("void") else "(result i32)"

        # recursively collect locals (including those in for-init)
        self.locals = ["__struct_ptr", "__lit"]
        def scan(stmt):
            from .ast import VariableDeclaration, IfStmt, ForStmt, WhileStmt, DoStmt, UntilStmt
            # local variable
            if isinstance(stmt, VariableDeclaration) and stmt.type != TypeExpr("void"):
                if stmt.name not in self.locals:
                    self.locals.append(stmt.name)
            # if-statement
            elif isinstance(stmt, IfStmt):
                for s in stmt.then_stmts + stmt.else_stmts:
                    scan(s)
            # for-statement (catches init & post)
            elif isinstance(stmt, ForStmt):
                if stmt.init: scan(stmt.init)
                if stmt.post: scan(stmt.post)
                for s in stmt.body + stmt.else_body:
                    scan(s)
            # while/until
            elif isinstance(stmt, (WhileStmt, UntilStmt)):
                for s in stmt.body + stmt.else_body:
                    scan(s)
            # do-stmt
            elif isinstance(stmt, DoStmt):
                if stmt.count is not None and isinstance(stmt.count, VariableDeclaration):
                    scan(stmt.count)
                for s in stmt.body + stmt.else_body:
                    scan(s)
            # nested declarations in assignments or calls get picked up in their Expression handling

        # scan the entire body
        for st in m.body:
            scan(st)

        # emit the function header
        locals_decl = " ".join(f"(local ${n} i32)" for n in self.locals)
        header = f"  (func ${fn_name} {' '.join(params)} {result_decl} {locals_decl}"
        self.out.append(header)

        # emit the body
        for stmt in m.body:
            self.gen_stmt(stmt)

        # emit the tail
        if is_constructor:
            # constructors return `this`
            self.emit("local.get $this")
            self.emit("return")
        elif m.return_type == TypeExpr("void"):
            self.emit("return")
        else:
            # non-void must have returned on every path
            self.emit("unreachable")

        # splice in code and close
        self.out.extend(self.code)
        self.out.append("  )")



    def gen_func(self, func: FunctionDeclaration, type_args=None):
        #print(f"[DEBUG] Generating function {func.name} with type args {type_args}")
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
            # First, we need to get the address of the field
            # Generate the object expression to get the base address
            self.gen_expr(stmt.obj.obj)  # This is the object part of the MemberAccess
            
            # Generate the RHS value
            self.gen_expr(stmt.expr)
            
            # Get struct info from the MemberAccess node
            if not hasattr(stmt.obj, 'struct') or stmt.obj.struct is None:
                raise RuntimeError(f"MemberAssignment missing struct annotation on {stmt.obj}")
            
            struct_name = stmt.obj.struct.name
            if struct_name not in self.struct_layouts:
                raise RuntimeError(f"Unknown struct layout: {struct_name}")
                
            # Emit the store into that field
            off = self.struct_layouts[struct_name]["offsets"][stmt.field]
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
            first = expr.elements[0]

            # 1) figure out the TypeExpr for the element
            #    (either from the local TV map, or from a literal’s type)
            if isinstance(first, Number):
                elt_ty = TypeExpr("int")
            else:
                # for generic methods, _tv_map["T"] → TypeExpr("int") or TypeExpr("T")
                elt_ty = self._tv_map.get(first.name, None)  
                if elt_ty is None:
                    raise RuntimeError("can't infer list element type for " + repr(first))

            # 2) build the constructor call with that type
            head_call = FunctionCall("list", [elt_ty], [first], pos=expr.pos)

            # 3) debug-print to be sure:
            print(f"[ListLiteral] building list<{elt_ty.name}> ctor → "
                f"head_call.type_args = {[ta.name for ta in head_call.type_args]}")

            print("  ↳ created head_call:", head_call, "with type_args =", [*map(str, head_call.type_args)])
            print(f"[DEBUG] Generating ListLiteral with {[*map(str, head_call.type_args)]}")
            self.gen_expr(head_call)         # alloc + constructor
            self.emit("local.set $__lit")    # store head in $__lit

            # --- link remaining elements ---
            for elt in expr.elements[1:]:
                node_call = FunctionCall("list", [elt_ty], [elt], pos=expr.pos)
                self.gen_expr(node_call)     # alloc + constructor
                self.emit("local.set $__struct_ptr")

                # __lit.append(__struct_ptr)
                self.emit("local.get $__lit")
                self.emit("local.get $__struct_ptr")
                # mangle it with the same elt_ty
                append_fn = self._mangle("list_append", [elt_ty])
                self.emit(f"call ${append_fn}")

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
            # Generate the base object
            self.gen_expr(expr.obj)
            
            # Check if this is a static field access
            if hasattr(expr, 'is_static_field') and expr.is_static_field: # type: ignore
                # This should be handled by the static field case above
                raise RuntimeError("Static field access should be handled separately")
            
            # Get the struct type - should be set by semantic analysis
            if not hasattr(expr, 'struct') or expr.struct is None:
                raise RuntimeError(f"MemberAccess missing struct annotation for field '{expr.field}'")
            
            struct_name = expr.struct.name
            if struct_name not in self.struct_layouts:
                raise RuntimeError(f"Unknown struct layout: '{struct_name}' for field '{expr.field}'")
            
            # Get field offset and emit load
            if expr.field not in self.struct_layouts[struct_name]["offsets"]:
                raise RuntimeError(f"Field '{expr.field}' not found in struct '{struct_name}'")
                
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
            print(f"[CtorCall] in {self.current_struct}<{self.current_targs}>"
                          f"::{self.current_method}() got expr.type_args ="
              f" {[ta.name for ta in expr.type_args]}")            # remap any type-var arguments through the local map
            concrete_targs = [
                (self._tv_map[ta.name] if ta.name in self._tv_map else ta)
                for ta in expr.type_args
            ]
            # register the right instantiation
            key = (expr.name, tuple(ta.name for ta in concrete_targs))
            self.struct_insts[key] = True

            # and when you mangle the ctor name, use concrete_targs:
            raw_ctor = f"{expr.name}_{expr.name}"
            mangled_ctor = self._mangle(raw_ctor, concrete_targs)
            self.struct_insts[key] = True

            # the constructor was emitted as `<struct>_<struct>__<targs>` (or just `<struct>_<struct>` when no targs)
            raw_ctor = f"{expr.name}_{expr.name}"
            mangled_ctor = self._mangle(raw_ctor, concrete_targs)
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
        #print(f"[DEBUG] Mangling {base} with type args {[*map(str, type_args)]} to {base}__{suffix}")
        return f"{base}__{suffix}"
