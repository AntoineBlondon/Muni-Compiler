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
    ArrayLiteral,
    StringLiteral,
    CharLiteral,
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

        self.struct_layouts["array"] = {
            "size":   8,
            "offsets": {
                "length": 0,
                "buffer": 4
            }
        }

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
            if stmt.count is None:
                stmt.count = Number("1")
            try:
                if stmt.count.value == 0:
                    return
            except Exception:
                pass
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
        elif isinstance(expr, ArrayLiteral):
            # --- reuse the runtime constructor for us ---
            if not expr.elements:
                # empty array → null pointer
                self.emit("i32.const 0")
                return

            # assume int‐elements for now; extend size_of if you need other T
            elt_ty = TypeExpr("T")
            n = len(expr.elements)

            # 1) call array<T>(n)
            ctor_call = FunctionCall("array", [elt_ty], [Number(str(n))], pos=expr.pos)
            self.gen_expr(ctor_call)
            # stash the returned ptr
            self.emit("local.set $__lit")

            # 2) populate each slot: x.set(i, value)
            for i, elt in enumerate(expr.elements):

                # build an AST node for: $__lit.set(i, elt)
                set_call = MethodCall(
                   Ident("__lit", pos=expr.pos),   # receiver
                   [],                              # no type‐args
                   "set",                           # method name
                   [ Number(str(i), pos=expr.pos), elt ],
                   struct=TypeExpr("array", [elt_ty]),
                   pos=expr.pos
                )
                self.gen_expr(set_call)          # this will inline your intrinsic .set

            # finally leave the array ptr on the stack
            self.emit("local.get $__lit")
            return
        elif isinstance(expr, CharLiteral):
            # Convert char to its ASCII value
            ascii_value = ord(expr.value)
            self.emit(f"i32.const {ascii_value}")
        elif isinstance(expr, StringLiteral):
            # 1) turn the Python str into a series of CharLiterals:
            chars = [ CharLiteral(repr(c), pos=expr.pos) for c in expr.value ]

            # 2) build an array literal AST for [c0, c1, ...]:
            array_lit = ArrayLiteral(chars, pos=expr.pos)

            # 3) call vec<char>.from_array( array_lit ):
            char_ty = TypeExpr("int")
            vec_ty  = TypeExpr("vec", [char_ty])

            # a dummy Ident holding the struct for codegen:
            rcvr = Ident("vec", pos=expr.pos)
            # annotate its struct so gen_expr knows we're calling vec<char>
            method_call = MethodCall(
                receiver = rcvr,
                type_args = [char_ty],      # struct type-arg
                method    = "from_array",
                args      = [ array_lit ],
                struct    = vec_ty,         # <--- this is critical
                pos       = expr.pos
            )

            # now generate code for that call:
            self.gen_expr(method_call)
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
        
        # --- intrinsic array methods (must go _before_ any static‐generic logic) ---
        elif isinstance(expr, MethodCall) and expr.struct.name == "array": # type: ignore
            # array.get(idx)
            if expr.method == "get":
                self.gen_expr(expr.receiver)        # arr_ptr
                self.emit("i32.load offset=4")     # buf_ptr
                self.gen_expr(expr.args[0])        # idx
                self.emit("i32.const 4")
                self.emit("i32.mul")
                self.emit("i32.add")
                self.emit("i32.load")
                return

            # array.set(idx, val)
            if expr.method == "set":
                self.gen_expr(expr.receiver)
                self.emit("i32.load offset=4")
                self.gen_expr(expr.args[0])
                self.emit("i32.const 4")
                self.emit("i32.mul")
                self.emit("i32.add")
                self.gen_expr(expr.args[1])
                self.emit("i32.store")
                return

        # --- static method on a generic struct: Foo<T>.bar(...) ---
        #     only when the left‐hand is the _type_ name itself
        elif (isinstance(expr, MethodCall)
              and isinstance(expr.receiver, Ident)
              and expr.receiver.name == expr.struct.name): # type: ignore
            struct_ty: TypeExpr = expr.struct   # e.g. TypeExpr("list",[TypeExpr("int")]) # type: ignore
            base  = struct_ty.name
            targs = struct_ty.params

            # record for monomorphization
            key = (base, tuple(ta.name for ta in targs))
            self.struct_insts[key] = True

            # emit just the explicit args
            for arg in expr.args:
                self.gen_expr(arg)

            mangled = self._mangle(f"{base}_{expr.method}", targs)
            self.emit(f"call ${mangled}")
            return

        # --- everything else is an _instance_‐method call ---
        elif isinstance(expr, MethodCall):
            struct_ty: TypeExpr = expr.struct # type: ignore
            base, targs = struct_ty.name, struct_ty.params
            key = (base, tuple(ta.name for ta in targs))
            self.struct_insts[key] = True

            # first the receiver
            self.gen_expr(expr.receiver)
            # then the rest of the args
            for arg in expr.args:
                self.gen_expr(arg)

            mangled = self._mangle(f"{base}_{expr.method}", targs)
            self.emit(f"call ${mangled}")
            return

        elif isinstance(expr, FunctionCall) and expr.name == "array":
            # --- array<T>(length) constructor ---
            # expr.type_args == [ eltType ]
            # expr.args      == [ lengthExpr ]
            #
            # 1) compute header size & allocate it
            header_size = self.struct_layouts["array"]["size"]
            self.emit(f"i32.const {header_size}")
            self.emit("call $malloc")
            self.emit("local.set $__struct_ptr")      # $__struct_ptr = header_ptr

            # 2) evaluate length argument
            self.emit("local.get $__struct_ptr")      # stack: header_ptr
            self.gen_expr(expr.args[0])               # stack: header_ptr, length
            self.emit("i32.store offset=0")           # store length at [header_ptr + 0]

            # 3) compute element-buffer size = length * sizeof(T)
            self.emit("local.get $__struct_ptr")      # stack: header_ptr
            self.gen_expr(expr.args[0])               # stack: header_ptr, length
            self.emit("i32.const 4")                  # stack: header_ptr, length, 4
            self.emit("i32.mul")                      # stack: header_ptr, byteCount
            self.emit("call $malloc")                 # stack: header_ptr, buffer_ptr
            self.emit("i32.store offset=4")           # store buffer_ptr at [header_ptr + 4]


            # 4) return the header pointer
            self.emit("local.get $__struct_ptr")
            return

        # --- struct‐constructor (monomorphic or generic) ---
        elif isinstance(expr, FunctionCall) and expr.name in self.struct_layouts:
            # print(f"[CtorCall] in {self.current_struct}<{self.current_targs}>"
            #               f"::{self.current_method}() got expr.type_args ="
            #   f" {[ta.name for ta in expr.type_args]}")            # remap any type-var arguments through the local map
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


    def size_of(self, type_expr: TypeExpr) -> int:
        if type_expr.name == "int":
            return 4
        elif type_expr.name == "boolean":
            return 4
        elif type_expr.name == "void":
            return 0
        elif type_expr.name in self.struct_layouts:
            return self.struct_layouts[type_expr.name]["size"]
        raise NotImplementedError(f"Unknown type: {type_expr}")