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
    IntLiteral,
    FloatLiteral,
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

malloc ="""
(func $malloc (param $n i32) (result i32)
  (local $old i32)
  (local $new i32)
  (local $pages_now i32)
  (local $pages_need i32)
  (local $delta i32)

  ;; align n to 4: n = (n + 3) & ~3
  local.get $n
  i32.const 3
  i32.add
  i32.const -4
  i32.and
  local.set $n

  ;; old/new heap pointers
  global.get $heap
  local.tee $old
  local.get $n
  i32.add
  local.tee $new
  global.set $heap

  ;; pages_now = memory.size()
  memory.size
  local.set $pages_now

  ;; pages_need = ceil((new)/65536) = (new + 65535) >> 16
  local.get $new
  i32.const 65535
  i32.add
  i32.const 16
  i32.shr_u
  local.set $pages_need

  ;; delta = pages_need - pages_now
  local.get $pages_need
  local.get $pages_now
  i32.sub
  local.tee $delta
  i32.const 0
  i32.gt_s
  if
    local.get $delta
    memory.grow
    drop
  end

  local.get $old
)
"""


I = "i32"; F = "f32"

BINOP_MAP = {
    "+": {I: "i32.add", F: "f32.add"},
    "-": {I: "i32.sub", F: "f32.sub"},
    "*": {I: "i32.mul", F: "f32.mul"},
    "/": {I: "i32.div_s", F: "f32.div"},
    "%": {I: "i32.rem_s"},                 
}

CMP_MAP = {
    "==": {I: "i32.eq", F: "f32.eq"},
    "!=": {I: "i32.ne", F: "f32.ne"},
    "<":  {I: "i32.lt_s", F: "f32.lt"},
    "<=": {I: "i32.le_s", F: "f32.le"},
    ">":  {I: "i32.gt_s", F: "f32.gt"},
    ">=": {I: "i32.ge_s", F: "f32.ge"},
}

LOGIC_MAP = {
    "&&": {I: "i32.and"},
    "||": {I: "i32.or"},
}

LOAD = {I: "i32.load", F: "f32.load"}
STORE = {I: "i32.store", F: "f32.store"}

CONST = {I: lambda v: f"i32.const {v}",
         F: lambda v: f"f32.const {v}"}

LIT_MAX = 8

class CodeGen:
    def __init__(self, program: Program):
        self.program = program
        self.struct_layouts: dict[str, dict] = {}
        self.out: list[str] = []
        self._label_count = 0
        # Stack of (break_label, continue_label, exit_label)
        self._loop_stack: list[tuple[str, str, str]] = []
        self.struct_insts: dict[tuple[str,tuple[str,...]], bool] = {}
        self.fn_insts: dict[tuple[str,tuple[str,...]], bool] = {}
        self._emitted_struct_insts: set[tuple[str, tuple]] = set()
        self._emitted_fn_insts: set[tuple[str, tuple]] = set()
        self.local_types: dict[str, str] = {}   

        self._tv_map: dict[str, TypeExpr] = {}
        self._lit_depth = 0

    def _fresh_label(self, base: str) -> str:
        lbl = f"${base}_{self._label_count}"
        self._label_count += 1
        return lbl

    def gen(self) -> str:
        self.out = ["(module"]
        # 1) host imports
        for imp in self.program.decls:
            if isinstance(imp, ImportDeclaration) and imp.source is None:
                # params can be [TypeExpr, ...] OR [(name, TypeExpr), ...]
                param_types: list[str] = []
                for p in imp.params:
                    if isinstance(p, tuple):
                        _, pt = p
                    else:
                        pt = p
                    param_types.append(wasm_ty(pt))

                # build the (param …) piece only if there are params
                param_part = f"(param {' '.join(param_types)}) " if param_types else ""

                # result
                rt_name = imp.return_type.name if hasattr(imp.return_type, "name") else imp.return_type #type: ignore
                result_part = "" if rt_name == "void" else f"(result {wasm_ty(imp.return_type)})" #type: ignore

                self.out.append(
                    f'  (import "{imp.module}" "{imp.name}" '
                    f'(func ${imp.name} {param_part}{result_part}))'
                )

        self.import_function("muni", "trap_oob", ["i32", "i32", "i32", "i32"])
        self.import_function("muni", "trap_div0", ["i32", "i32"])
        self.import_function("muni", "debug_i32", ["i32"])
        # 2) memory + malloc
        self.out.extend([
            "  (memory $mem 1 65535)",
            "  (global $heap (mut i32) (i32.const 16))",
            malloc,
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
                    if isinstance(sf.expr, IntLiteral):
                        ty = "i32"
                        init = f"(i32.const {sf.expr.value})"
                    elif isinstance(sf.expr, BooleanLiteral):
                        ty = "i32"
                        init = f"(i32.const {1 if sf.expr.value else 0})"
                    elif isinstance(sf.expr, FloatLiteral):
                        ty = "f32"
                        init = f"(f32.const {sf.expr.value})"
                    else:
                        continue
                    self.out.append(f"  (global ${d.name}_{sf.name} {ty} {init})")


        # 6) emit all free, non-generic functions
        for fd in self.program.decls:
            if isinstance(fd, FunctionDeclaration) and not fd.type_params:
                self.gen_func(fd)



    
        # 7) emit each concrete instantiation:
        processed_structs = set()
        changed = True
        while changed:
            changed = False
            for struct_name, targs in list(self.struct_insts):
                key = (struct_name, targs)
                if key in processed_structs:
                    continue

                sd = next(d for d in self.program.decls
                        if isinstance(d, StructureDeclaration) and d.name == struct_name)
                tas = [TypeExpr(n) for n in targs]

                # 7a) constructor
                ctor = next((m for m in sd.methods if m.is_static and m.name == struct_name), None)
                if ctor:
                    self.gen_method(struct_name, ctor, type_args=tas)

                # 7b) instance methods
                for m in sd.methods:
                    if not m.is_static:
                        self.gen_method(struct_name, m, type_args=tas)

                # 7c) other static methods
                for m in sd.methods:
                    if m.is_static and m.name != struct_name:
                        self.gen_method(struct_name, m, type_args=tas)

                processed_structs.add(key)
                changed = True

        # 8) monomorphize any generic free functions
        processed_funcs = set()
        changed = True
        while changed:
            changed = False
            for fn, targs in list(self.fn_insts):
                key = (fn, targs)
                if key in processed_funcs:
                    continue
                fd = next(f for f in self.program.decls
                        if isinstance(f, FunctionDeclaration) and f.name == fn)
                self.gen_func(fd, type_args=[TypeExpr(n) for n in targs])
                processed_funcs.add(key)
                changed = True

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
        self.locals = []
        self.local_types = {}
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
        for pname, pty in m.params:
            params.append(f"(param ${pname} {wasm_ty(pty)})")

        # return signature
        if is_constructor:
            result_decl = "(result i32)"
        else:
            result_decl = "" if m.return_type == TypeExpr("void") else f"(result {wasm_ty(m.return_type)})"
        
        # recursively collect locals (including those in for-init)
        temp_i32 = [
            "__struct_ptr", "__lit", "__arr_ptr", "__idx", "__val", "__arr_build",
            "__set_rcv", "__set_idx", "__get_rcv", "__get_idx",
            "__lit_hdr", "__lit_base", "__new_arr", "__new_len",
            "__set_val",
            *[f"__lit_hdr{i}" for i in range(LIT_MAX)],
            *[f"__lit_base{i}" for i in range(LIT_MAX)],
        ]
        temp_f32 = [
            "__set_val_f32",  # for array.set when element is float
        ]

        def scan(stmt):
            # local variable
            if isinstance(stmt, VariableDeclaration) and stmt.type != TypeExpr("void"):
                if stmt.name not in self.locals:
                    self.locals.append(stmt.name)
                self.local_types[stmt.name] = wasm_ty(stmt.type)
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
        locals_decl = " ".join(
            [f"(local ${n} i32)" for n in temp_i32] +
            [f"(local ${n} f32)" for n in temp_f32] +
            [f"(local ${n} {self.local_types.get(n, 'i32')})"
            for n in self.locals if n not in temp_i32 and n not in temp_f32]
        )
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
        self.locals = []
        self.local_types = {}
        #print(f"[DEBUG] Generating function {func.name} with type args {type_args}")
        temp_i32 = [
            "__struct_ptr", "__lit", "__arr_ptr", "__idx", "__val", "__arr_build",
            "__set_rcv", "__set_idx", "__get_rcv", "__get_idx",
            "__lit_hdr", "__lit_base", "__new_arr", "__new_len",
            "__set_val",
            *[f"__lit_hdr{i}" for i in range(LIT_MAX)],
            *[f"__lit_base{i}" for i in range(LIT_MAX)],
        ]
        temp_f32 = [
            "__set_val_f32",  # for array.set when element is float
        ]


        self.code = []
        raw = func.name
        name = self._mangle(raw, type_args or [])

        # recursively collect locals
        def scan(s):
            if isinstance(s, VariableDeclaration) and s.type != TypeExpr("void"):
                if s.name not in self.locals:
                    self.locals.append(s.name)
                self.local_types[s.name] = wasm_ty(s.type)
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

        params_decl = " ".join(f"(param ${n} {wasm_ty(t)})" for n, t in func.params)
        result_decl = "" if func.return_type == TypeExpr("void") else f"(result {wasm_ty(func.return_type)})"
        locals_decl = " ".join(
            [f"(local ${n} i32)" for n in temp_i32] +
            [f"(local ${n} f32)" for n in temp_f32] +
            [f"(local ${n} {self.local_types.get(n, 'i32')})"
            for n in self.locals if n not in temp_i32 and n not in temp_f32]
        )

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
            fty = getattr(stmt, "field_type", None) or getattr(stmt.obj, "field_type", None)  # whichever you annotate
            op_store = "f32.store" if fty and fty.name == "float" else "i32.store"
            self.emit(f"{op_store} offset={off}")
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
            rt = self._func_return_type(stmt.name)
            if rt.name != "void":
                self.emit("drop")
            return

        # Bare MethodCall
        if isinstance(stmt, MethodCall):
            self.gen_expr(stmt)
            rt = self._method_return_type(stmt.struct.name, stmt.method,  # type: ignore
                                  is_static=isinstance(stmt.receiver, Ident) and stmt.receiver.name == stmt.struct.name)  # type: ignore
            if rt.name != "void":
                self.emit("drop")
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
                stmt.count = IntLiteral("1")
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

            # if count is negative or nil, skip loop
            self.emit("local.get $__struct_ptr")
            self.emit("i32.const 0")
            self.emit("i32.le_s")
            self.emit(f"br_if {br_lbl}")
            
            
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
        if isinstance(expr, IntLiteral):
            self.emit(f"i32.const {expr.value}")
        elif isinstance(expr, FloatLiteral):
            self.emit(f"f32.const {expr.value}")
        elif isinstance(expr, BooleanLiteral):
            self.emit(f"i32.const {1 if expr.value else 0}")
        elif isinstance(expr, ArrayLiteral):
            n = len(expr.elements)
            if n == 0:
                self.emit("i32.const 0"); return

            # choose unique locals for this nesting level
            d = self._lit_depth
            if d >= LIT_MAX:
                raise RuntimeError("Array literal nesting exceeds LIT_MAX")
            hdr  = f"__lit_hdr{d}"
            base = f"__lit_base{d}"

            self._lit_depth += 1
            try:
                slot = 4
                elem_ty = getattr(expr, "array_elem", None)
                if elem_ty is None:
                    is_float = any(isinstance(e, FloatLiteral) for e in expr.elements)
                else:
                    is_float = (elem_ty.name == "float")
                store_op = "f32.store" if is_float else "i32.store"

                # build header and capture it in this level's local
                self.create_array(IntLiteral(n))     # leaves header on stack
                self.emit(f"local.set ${hdr}")

                # base = header.buffer
                self.emit(f"local.get ${hdr}")
                self.emit("i32.load offset=4")
                self.emit(f"local.set ${base}")

                for i, elt in enumerate(expr.elements):
                    # address = base + i*slot
                    self.emit(f"local.get ${base}")
                    self.emit(f"i32.const {i * slot}")
                    self.emit("i32.add")

                    # value (may build nested arrays; safe because this level's locals are unique)
                    self.gen_expr(elt)
                    self.emit(store_op)

                # result: header for this literal
                self.emit(f"local.get ${hdr}")
                return
            finally:
                self._lit_depth -= 1






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
                struct    = vec_ty,
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
                # unary '-'
                if getattr(expr.expr, "type", TypeExpr("int")).name == "float":
                    self.gen_expr(expr.expr)
                    self.emit("f32.neg")
                else:
                    self.emit("i32.const 0")
                    self.gen_expr(expr.expr)
                    self.emit("i32.sub")

        elif isinstance(expr, BinOp):
            op = expr.op
            lty = wasm_ty(expr.left.type)
            rty = wasm_ty(expr.right.type)

            # % only for ints
            if op in ("/", "%") and lty == "i32":
                # INT: keep your div/0 trap
                self.gen_expr(expr.right); self.emit("local.set $__lit")
                self.gen_expr(expr.left);  self.emit("local.set $__struct_ptr")
                line = expr.pos[0] if getattr(expr, "pos", None) else 0 # type: ignore
                col  = expr.pos[1] if getattr(expr, "pos", None) else 0 # type: ignore
                self.emit("local.get $__lit")
                self.emit("i32.const 0")
                self.emit("i32.eq")
                self.emit("if")
                self.emit(f"  i32.const {line}")
                self.emit(f"  i32.const {col}")
                self.emit("  call $trap_div0")
                self.emit("  unreachable")
                self.emit("end")
                self.emit("local.get $__struct_ptr")
                self.emit("local.get $__lit")
                self.emit("i32.div_s" if op == "/" else "i32.rem_s")
                return

            if op == "/" and lty == "f32":
                # FLOAT: IEEE — no div-by-zero trap
                self.gen_expr(expr.left)
                self.gen_expr(expr.right)
                self.emit("f32.div")
                return

            # comparisons
            if op in CMP_MAP:
                # Special-case: equality/inequality may be operator-overloaded for structs
                if op in ("==", "!="):
                    lt = getattr(expr.left, "type", TypeExpr("int"))
                    rt = getattr(expr.right, "type", TypeExpr("int"))

                    # If both are the same struct type (including generics)
                    if self._is_struct_type(lt) and lt.name == getattr(rt, "name", None):
                        base = lt.name
                        # If the struct defines instance _equals, call it
                        if self._struct_has_instance_method(base, "_equals"):
                            # Register monomorph instantiation (generic support)
                            targs = [self._remap_ty(p) for p in lt.params]
                            key = (base, tuple(ta.name for ta in targs))
                            self.struct_insts[key] = True

                            # Evaluate receiver (left) and stash, then call with (this, right)
                            self.gen_expr(expr.left)
                            self.emit("local.set $__arr_ptr")
                            self.emit("local.get $__arr_ptr")
                            self.gen_expr(expr.right)

                            mangled = self._mangle(f"{base}__\x65quals", targs)  # "_equals"
                            # NOTE: above uses a literal "_equals"; the \x65 avoids accidental find/replace issues.


                            self.emit(f"call ${mangled}")

                            # a != b  ⇒  !a._equals(b)
                            if op == "!=":
                                self.emit("i32.eqz")
                            return
                self.gen_expr(expr.left)
                self.gen_expr(expr.right)
                self.emit(CMP_MAP[op][lty])
                return
            
            if op in LOGIC_MAP and lty == "i32":
                self.gen_expr(expr.left)
                self.gen_expr(expr.right)
                self.emit(LOGIC_MAP[op][lty])
                return

            # arithmetic +, -, *
            if op in BINOP_MAP:
                lt = getattr(expr.left, "type", TypeExpr("int"))
                rt = getattr(expr.right, "type", TypeExpr("int"))

                if self._is_struct_type(lt) and lt.name == getattr(rt, "name", None):
                    base = lt.name
                    # If the struct defines instance _<op>, call it
                    method_name = {"+": "add", "-": "sub", "*": "mul", "/": "div"}.get(op)
                    if method_name:
                        # Register monomorph instantiation (generic support)
                        targs = [self._remap_ty(p) for p in lt.params]
                        key = (base, tuple(ta.name for ta in targs))
                        self.struct_insts[key] = True

                        # Evaluate receiver (left) and stash, then call with (this, right)
                        self.gen_expr(expr.left)
                        self.emit("local.set $__arr_ptr")
                        self.emit("local.get $__arr_ptr")
                        self.gen_expr(expr.right)

                        mangled = self._mangle(f"{base}__{method_name}", targs)
                        self.emit(f"call ${mangled}")
                        return
                
                self.gen_expr(expr.left)
                self.gen_expr(expr.right)
                self.emit(BINOP_MAP[op][lty])
                return

            raise NotImplementedError(f"BinOp {op}")
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
            fty = getattr(expr, "field_type", None)
            op_load = "f32.load" if fty and fty.name == "float" else "i32.load"
            self.emit(f"{op_load} offset={off}")
            return
        
        # --- intrinsic array methods (must go _before_ any static‐generic logic) ---
        elif isinstance(expr, MethodCall) and expr.struct.name == "array" and expr.method in ("get", "set"):  # type: ignore
            # source position for nicer traps
            line     = expr.pos[0] if getattr(expr, "pos", None) else 0  # type: ignore
            col      = expr.pos[1] if getattr(expr, "pos", None) else 0  # type: ignore
            elem_ty  = getattr(expr, "array_elem", TypeExpr("int"))
            load_op  = "f32.load"  if elem_ty.name == "float" else "i32.load"
            store_op = "f32.store" if elem_ty.name == "float" else "i32.store"
            slot     = 4
            # array.get(idx)
            if expr.method == "get":
                # save receiver safely
                self.gen_expr(expr.receiver)
                self.emit("local.set $__get_rcv")

                # idx
                self.gen_expr(expr.args[0])
                self.emit("local.set $__get_idx")

                # restore receiver to $__arr_ptr just before checks/use
                self.emit("local.get $__get_rcv")
                self.emit("local.set $__arr_ptr")

                # bounds: if (__get_idx < 0 || >= len) trap
                self.emit("local.get $__get_idx")
                self.emit("i32.const 0")
                self.emit("i32.lt_s")
                self.emit("if")
                self.emit("  local.get $__get_idx")
                self.emit("  local.get $__arr_ptr")
                self.emit("  i32.load offset=0")
                self.emit(f"  i32.const {line}")
                self.emit(f"  i32.const {col}")
                self.emit("  call $trap_oob")
                self.emit("  unreachable")
                self.emit("end")

                self.emit("local.get $__get_idx")
                self.emit("local.get $__arr_ptr")
                self.emit("i32.load offset=0")
                self.emit("i32.ge_s")
                self.emit("if")
                self.emit("  local.get $__get_idx")
                self.emit("  local.get $__arr_ptr")
                self.emit("  i32.load offset=0")
                self.emit(f"  i32.const {line}")
                self.emit(f"  i32.const {col}")
                self.emit("  call $trap_oob")
                self.emit("  unreachable")
                self.emit("end")

                # load value
                self.emit("local.get $__arr_ptr")
                self.emit("i32.load offset=4")
                self.emit("local.get $__get_idx")
                self.emit("i32.const 4")
                self.emit("i32.mul")
                self.emit("i32.add")
                self.emit(load_op)
                return


            # array.set(idx, value)
            if expr.method == "set":
                # save receiver
                self.gen_expr(expr.receiver)
                self.emit("local.set $__set_rcv")

                # idx
                self.gen_expr(expr.args[0])
                self.emit("local.set $__set_idx")

                # value (may build nested arrays)
                self.gen_expr(expr.args[1])
                self.emit("local.set $__set_val_f32" if elem_ty.name == "float" else "local.set $__set_val")

                # restore receiver to $__arr_ptr
                self.emit("local.get $__set_rcv")
                self.emit("local.set $__arr_ptr")

                # bounds on __set_idx vs len(arr)
                self.emit("local.get $__set_idx")
                self.emit("i32.const 0")
                self.emit("i32.lt_s")
                self.emit("if")
                self.emit("  local.get $__set_idx")
                self.emit("  local.get $__arr_ptr")
                self.emit("  i32.load offset=0")
                self.emit(f"  i32.const {line}")
                self.emit(f"  i32.const {col}")
                self.emit("  call $trap_oob")
                self.emit("  unreachable")
                self.emit("end")

                self.emit("local.get $__set_idx")
                self.emit("local.get $__arr_ptr")
                self.emit("i32.load offset=0")
                self.emit("i32.ge_s")
                self.emit("if")
                self.emit("  local.get $__set_idx")
                self.emit("  local.get $__arr_ptr")
                self.emit("  i32.load offset=0")
                self.emit(f"  i32.const {line}")
                self.emit(f"  i32.const {col}")
                self.emit("  call $trap_oob")
                self.emit("  unreachable")
                self.emit("end")

                # *(arr.buffer + idx*4) = val
                self.emit("local.get $__arr_ptr")
                self.emit("i32.load offset=4")
                self.emit("local.get $__set_idx")
                self.emit("i32.const 4")
                self.emit("i32.mul")
                self.emit("i32.add")
                self.emit("local.get $__set_val_f32" if elem_ty.name == "float" else "local.get $__set_val")
                self.emit(store_op)
                return


        # --- static method on a generic struct: Foo<T>.bar(...) ---
        #     only when the left‐hand is the _type_ name itself
        elif (isinstance(expr, MethodCall)
              and isinstance(expr.receiver, Ident)
              and expr.receiver.name == expr.struct.name): # type: ignore
            struct_ty: TypeExpr = expr.struct   # type: ignore
            base  = struct_ty.name
            targs = [self._remap_ty(p) for p in struct_ty.params]

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
            base, targs = struct_ty.name, [self._remap_ty(p) for p in struct_ty.params]
            key = (base, tuple(ta.name for ta in targs))
            self.struct_insts[key] = True

            self.gen_expr(expr.receiver)
            self.emit("local.set $__arr_ptr")   # or a temp for the struct
            self.emit("local.get $__arr_ptr")
            for arg in expr.args:
                self.gen_expr(arg)

            mangled = self._mangle(f"{base}_{expr.method}", targs)
            self.emit(f"call ${mangled}")
            return

        elif isinstance(expr, FunctionCall) and expr.name == "array":
            # header
            header_size = self.struct_layouts["array"]["size"]
            self.emit(f"i32.const {header_size}")
            self.emit("call $malloc")
            self.emit("local.set $__struct_ptr")

            # len -> $__idx   (reuse an existing temp local)
            self.gen_expr(expr.args[0])
            self.emit("local.set $__idx")

            # if len < 0: trap_oob(len, 0, line, col) or just unreachable
            self.emit("local.get $__idx")
            self.emit("i32.const 0")
            self.emit("i32.lt_s")
            self.emit("if")
            # choose your trap; here I'll just do unreachable to keep it simple
            self.emit("  unreachable")
            self.emit("end")

            # store length
            self.emit("local.get $__struct_ptr")
            self.emit("local.get $__idx")
            self.emit("i32.store offset=0")

            # buffer = malloc(len * 4)
            self.emit("local.get $__struct_ptr")
            self.emit("local.get $__idx")
            self.emit("i32.const 4")
            self.emit("i32.mul")
            self.emit("call $malloc")
            self.emit("i32.store offset=4")

            # return header
            self.emit("local.get $__struct_ptr")
            return
        
        # --- explicit cast: as<T>(expr) ---
        elif isinstance(expr, FunctionCall) and expr.name == "as" and len(expr.args) == 1 and len(expr.type_args) == 1:
            # emit source value
            self.gen_expr(expr.args[0])

            # determine src/dst wasm types
            # Prefer the checker’s annotation if present:
            src_ty = getattr(expr.args[0], "type", TypeExpr("int"))
            dst_ty = expr.type_args[0]
            src_wt = wasm_ty(src_ty)
            dst_wt = wasm_ty(dst_ty)

            # numeric & boolean lowering
            if dst_ty.name == "int":
                if src_wt == "f32":
                    self.emit("i32.trunc_f32_s")
                # boolean->int and int->int: already i32 (no-op)
                return

            if dst_ty.name == "float":
                if src_wt == "i32":
                    self.emit("f32.convert_i32_s")
                # float->float: no-op
                return

            if dst_ty.name == "boolean":
                # Normalize to i32 0/1
                if src_wt == "i32":
                    # int or pointer → bool: x != 0
                    self.emit("i32.const 0")
                    self.emit("i32.ne")
                else:  # f32
                    self.emit("f32.const 0")
                    self.emit("f32.ne")
                return

            # for ref types (structs/arrays), as<T> is a no-op at Wasm level (they’re i32)
            # value already on stack
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
            
            sd = next(d for d in self.program.decls
                    if isinstance(d, StructureDeclaration) and d.name == expr.name)
            ctor_decl = next((m for m in sd.methods if m.is_static and m.name == expr.name), None)
            exp_nargs = 0 if ctor_decl is None else len(ctor_decl.params)


            # DEBUG/SANITY: make sure we have the same number of args as the ctor params
            if len(expr.args) != exp_nargs:
                raise RuntimeError(
                    f"ctor call {expr.name}<{','.join(ta.name for ta in concrete_targs)}> "
                    f"has {len(expr.args)} arg(s), expected {exp_nargs} "
                    f"(at method {getattr(self, 'current_struct', '?')}."
                    f"{getattr(self, 'current_method', '?')})"
                )

            # now emit args and call
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
        elif type_expr.name == "float":
            return 4
        elif type_expr.name == "void":
            return 0
        elif type_expr.name in self.struct_layouts:
            return self.struct_layouts[type_expr.name]["size"]
        raise NotImplementedError(f"Unknown type: {type_expr}")



    def _remap_ty(self, t: TypeExpr) -> TypeExpr:
        if not t.params and t.name in self._tv_map:
            return self._tv_map[t.name]
        if t.params:
            return TypeExpr(t.name, [self._remap_ty(p) for p in t.params])
        return t
    
    def import_function(self, env: str, name: str, type_args: list[str], return_type: str | None = None):
        if return_type is None:
            result_decl = ""
        else:
            result_decl = f"(result {return_type})"
        self.out.extend([f"  (import \"{env}\" \"{name}\" (func ${name} (param {' '.join(type_args)}) {result_decl}))"])


    def create_array(self, length: IntLiteral):
        header_size = self.struct_layouts["array"]["size"]
        self.emit(f"i32.const {header_size}")
        self.emit("call $malloc")
        self.emit("local.set $__new_arr")       # header ptr

        self.gen_expr(length)
        self.emit("local.set $__new_len")       # length

        # if len < 0 → unreachable
        self.emit("local.get $__new_len")
        self.emit("i32.const 0")
        self.emit("i32.lt_s")
        self.emit("if"); self.emit("unreachable"); self.emit("end")

        # store length
        self.emit("local.get $__new_arr")
        self.emit("local.get $__new_len")
        self.emit("i32.store offset=0")

        # buffer = malloc(len * 4)
        self.emit("local.get $__new_arr")
        self.emit("local.get $__new_len")
        self.emit("i32.const 4")
        self.emit("i32.mul")
        self.emit("call $malloc")
        self.emit("i32.store offset=4")

        # return header
        self.emit("local.get $__new_arr")
        return
    
    def _is_struct_type(self, t: TypeExpr) -> bool:
        if isinstance(t, str):
            return False
        if t.name in ("int", "boolean", "float", "void"):
            return False
        # arrays are “runtime structs” but we’ll treat them specially
        return t.name in self.struct_layouts

    def _struct_has_instance_method(self, struct_name: str, method_name: str) -> bool:
        for d in self.program.decls:
            if isinstance(d, StructureDeclaration) and d.name == struct_name:
                return any((not m.is_static) and m.name == method_name for m in d.methods)
        return False
    

    def _func_return_type(self, name: str):
        fd = next((d for d in self.program.decls
                if isinstance(d, FunctionDeclaration) and d.name == name), None)
        return fd.return_type if fd else TypeExpr("void")

    def _method_return_type(self, struct_name: str, method: str, is_static: bool):
        sd = next((d for d in self.program.decls
                if isinstance(d, StructureDeclaration) and d.name == struct_name), None)
        if not sd: return TypeExpr("void")
        md = next((m for m in sd.methods if (m.is_static == is_static and m.name == method)), None)
        return md.return_type if md else TypeExpr("void")

WASM_TY = {
"int": "i32",
"boolean": "i32",
"float": "f32",
"void": None,
}

def wasm_ty(t: TypeExpr | str) -> str:
    name = t if isinstance(t, str) else t.name
    if name == "float":
        return "f32"
    return "i32"

