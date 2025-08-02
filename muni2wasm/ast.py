class Program:
    def __init__(self, decls, pos=None):
        self.decls = decls
        self.pos = pos

    def __str__(self):
        return f"Program[{', '.join(str(s) for s in self.decls)}]"


class VariableDeclaration:
    def __init__(self, type, name, expr, pos=None):
        self.type = type
        self.name = name
        self.expr = expr
        self.pos = pos

    def __str__(self):
        return f"(new {self.type}) {self.name} <- {self.expr}"

class VariableAssignment:
    def __init__(self, name, expr, pos=None):
        self.name = name
        self.expr = expr
        self.pos = pos

    def __str__(self):
        return f"{self.name} <- {self.expr}"


class BinOp:
    def __init__(self, op, left, right, pos=None):
        self.op = op
        self.left = left
        self.right = right
        self.pos = pos

    def __str__(self):
        return f"({self.left} {self.op} {self.right})"

class UnaryOp:
    def __init__(self, op, expr, pos=None):
        self.op = op
        self.expr = expr
        self.pos = pos
    def __str__(self):
        return f"({self.op} {self.expr})"

class Number:
    def __init__(self, value, pos=None):
        self.value = int(value)
        self.pos = pos

    def __str__(self):
        return f"int({self.value})"

class BooleanLiteral:
    def __init__(self, value: bool, pos=None):
        self.value = value
        self.pos = pos
    def __str__(self):
        return f"boolean({self.value})"

class Ident:
    def __init__(self, name, pos=None):
        self.name = name
        self.pos = pos

    def __str__(self):
        return f"id({self.name})"


class IfStmt:
    def __init__(self, cond, then_stmts, else_stmts=None, pos=None):
        self.cond = cond                   # expression
        self.then_stmts = then_stmts       # List[Stmt]
        self.else_stmts = else_stmts or [] # List[Stmt]
        self.pos = pos                     # (line, col) for error reporting

    def __str__(self):
        s = f"if({self.cond}) {{ {', '.join(str(s) for s in self.then_stmts)} }}"
        if self.else_stmts:
            s += f" else {{ {', '.join(str(s) for s in self.else_stmts)} }}"
        s += " }"
        return s



class ReturnStmt:
    def __init__(self, expr=None, pos=None):
        self.expr = expr
        self.pos = pos
    def __str__(self):
        return "return" + (f" {self.expr}" if self.expr else "")

class FunctionDeclaration:
    def __init__(self, name, params, return_type, body, pos=None):
        self.name = name                   # "factorial"
        self.params = params               # [("number","int"),…]
        self.return_type = return_type     # "int", "boolean", or "void"
        self.body = body                   # list of statements
        self.pos = pos
    def __str__(self):
        ps = ", ".join(f"{t} {n}" for n,t in self.params)
        return f"function {self.return_type} {self.name}({ps}) {{…}}"

class FunctionCall:
    def __init__(self, name, args, pos=None):
        self.name = name; self.args = args; self.pos = pos
    def __str__(self):
        a = ", ".join(str(x) for x in self.args)
        return f"{self.name}({a})"


class FieldDeclaration:
    def __init__(self, name: str, type: str, pos=None):
        self.name = name
        self.type = type
        self.pos = pos
    def __str__(self):
        return f"field({self.type} {self.name})"
    
class MethodDeclaration:
    def __init__(self, name: str, params: list[tuple[str,str]], return_type: str,
                 body: list, is_static: bool, pos=None):
        self.name = name
        self.params = params          # [(name, type), …]
        self.return_type = return_type
        self.body = body              # list of statements
        self.is_static = is_static
        self.pos = pos

    def __str__(self):
        static = "static " if self.is_static else ""
        ps = ", ".join(f"{t} {n}" for n,t in self.params)
        return f"{static}{self.return_type} {self.name}({ps}) {{…}}"

class StructureDeclaration:
    def __init__(self, name: str, fields: list[FieldDeclaration],
                 methods: list[MethodDeclaration], pos=None):
        self.name = name
        self.fields = fields
        self.methods = methods
        self.pos = pos

    def __str__(self):
        fs = "\n    ".join(str(f) for f in self.fields)
        ms = "\n    ".join(str(m) for m in self.methods)
        return f"struct {self.name} {{\n    {fs}\n    {ms}\n}}"
    
class MemberAccess:
    def __init__(self, obj, field, pos=None):
        self.obj   = obj      # an expression
        self.field = field    # string
        self.struct_name = ""
        self.pos   = pos

    def __str__(self):
        return f"({self.struct_name} {self.obj}).{self.field}"

class MemberAssignment:
    def __init__(self, obj, field, expr, pos=None):
        self.obj   = obj      # a MemberAccess
        self.field = field    # string (same as obj.field)
        self.expr  = expr     # RHS expression
        self.pos   = pos

    def __str__(self):
        return f"{self.obj}.{self.field} <- {self.expr}"

class MethodCall:
    def __init__(self, receiver, method: str, args: list, pos=None):
        self.receiver = receiver  # an expression
        self.method   = method    # method name
        self.struct_name = ""
        self.args     = args      # list of Expr
        self.pos      = pos

    def __str__(self):
        a = ", ".join(str(x) for x in self.args)
        return f"({self.struct_name} {self.receiver}).{self.method}({a})"


class BreakStmt:
    def __init__(self, pos=None):
        self.pos = pos

class ContinueStmt:
    def __init__(self, pos=None):
        self.pos = pos

class WhileStmt:
    def __init__(self, cond, body, else_body=None, pos=None):
        self.cond = cond        # Expr
        self.body = body        # [Stmt]
        self.else_body = else_body or []
        self.pos = pos

class UntilStmt:
    def __init__(self, cond, body, else_body=None, pos=None):
        self.cond = cond        # Expr
        self.body = body        # [Stmt]
        self.else_body = else_body or []
        self.pos = pos


class ForStmt:
    def __init__(self, init, cond, post, body, else_body=None, pos=None):
        self.init      = init      # Stmt or None
        self.cond      = cond      # Expr or None
        self.post      = post      # Stmt or None
        self.body      = body      # [Stmt]
        self.else_body = else_body or []
        self.pos = pos

class DoStmt:
    def __init__(self, count, cond, body, else_body=None, pos=None):
        self.count     = count      # Expr or None  (if None, do once)
        self.cond      = cond       # Expr or None
        self.body      = body       # [Stmt]
        self.else_body = else_body or []
        self.pos = pos


class VoidStatement:
    def __init__(self, pos=None):
        self.pos = pos