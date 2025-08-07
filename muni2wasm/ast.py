import ast


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
        return f"new {self.type} {self.name} <- {self.expr}"

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
    def __init__(self, name, type_params, params, return_type, body, pos=None):
        self.name = name                   # "factorial"
        self.type_params = type_params
        self.params = params               # [("number","int"),…]
        self.return_type = return_type     # "int", "boolean", or "void"
        self.body = body                   # list of statements
        self.pos = pos
    def __str__(self):
        ps = ", ".join(f"{t} {n}" for n,t in self.params)
        if self.type_params: 
            return f"function {self.return_type} {self.name}<{', '.join(self.type_params)}>({ps}) {{…}}"
        return f"function {self.return_type} {self.name}({ps}) {{…}}"

class FunctionCall:
    def __init__(self, name, type_args, args, pos=None):
        self.name = name 
        self.type_args = type_args
        self.args = args
        self.pos = pos
    def __str__(self):
        a = ", ".join(str(x) for x in self.args)
        return f"{self.name}({a})"


class FieldDeclaration:
    def __init__(self, name: str, type, pos=None):
        self.name = name
        self.type = type
        self.pos = pos
    def __str__(self):
        return f"field({self.type} {self.name})"
    
class MethodDeclaration:
    def __init__(self, name: str, type_params, params, return_type,
                 body: list, is_static: bool, pos=None):
        self.name = name
        self.type_params = type_params
        self.params = params          # [(name, type), …]
        self.return_type = return_type
        self.body = body              # list of statements
        self.is_static = is_static
        self.pos = pos

    def __str__(self):
        static = "static " if self.is_static else ""
        ps = ", ".join(f"{t} {n}" for n,t in self.params)
        return f"{static}{self.return_type} {self.name}({ps}) {{…}}"

class StaticFieldDeclaration:
    def __init__(self, name: str, type, expr, pos=None):
        self.name = name
        self.type = type
        self.expr = expr
        self.pos = pos
    def __str__(self):
        return f"static {self.type} {self.name} = {self.expr}"

class StructureDeclaration:
    def __init__(self, name: str, 
                 type_params, fields: list[FieldDeclaration],
                 static_fields: list[StaticFieldDeclaration],
                 methods: list[MethodDeclaration], pos=None):
        self.name = name
        self.type_params = type_params
        self.fields = fields
        self.static_fields = static_fields
        self.methods = methods
        self.pos = pos

    def __str__(self):
        fs = "\n    ".join(str(f) for f in self.fields)
        sfs = "\n    ".join(str(f) for f in self.static_fields)
        ms = "\n    ".join(str(m) for m in self.methods)
        return (
            f"struct {self.name} {{\n"
            + (f"    {sfs}\n" if sfs else "")
            + (f"    {fs}\n" if fs else "")
            + (f"    {ms}\n" if ms else "")
            + "}"
        )
    
class MemberAccess:
    def __init__(self, obj, field, pos=None):
        self.obj   = obj      # an expression
        self.field = field    # string
        self.struct = None
        self.pos   = pos

    def __str__(self):
        return f"({self.struct} {self.obj}).{self.field}"

class MemberAssignment:
    def __init__(self, obj, field, expr, pos=None):
        self.obj   = obj      # a MemberAccess
        self.field = field    # string (same as obj.field)
        self.expr  = expr     # RHS expression
        self.pos   = pos

    def __str__(self):
        return f"{self.obj}.{self.field} <- {self.expr}"

class MethodCall:
    def __init__(self, receiver, type_args, method: str, args: list, struct=None, pos=None):
        self.receiver = receiver  # an expression
        self.type_args = type_args
        self.method   = method    # method name
        self.struct = struct
        self.args     = args      # list of Expr
        self.pos      = pos

    def __str__(self):
        a = ", ".join(str(x) for x in self.args)
        return f"({self.struct} {self.receiver}).{self.method}({a})"


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


class NullLiteral:
    def __init__(self, pos=None):
        self.pos = pos


class ArrayLiteral:
    def __init__(self, elements: list, pos=None):
        self.elements = elements  # list of Expr
        self.pos = pos
    def __str__(self):
        return "[" + ", ".join(str(e) for e in self.elements) + "]"


class ImportDeclaration:
  def __init__(self,
               source: str | None = None,
               module: str | None = None,
               name:   str | None = None,
               params = None,
               type_params = None,
               return_type = None,
               pos=None):
      self.source      = source       # e.g. "math.mun"
      self.module      = module       # e.g. "env" or "random"
      self.name        = name         # e.g. "print" or "randint"
      self.params      = params or [] # ["int"], ["list"], …
      self.type_params = type_params or []  # e.g. ["T"] for generic imports
      self.return_type = return_type  # "void", "int", or struct name
      self.pos         = pos
  def __str__(self):
      if self.source:
          return f'import <{self.source}>;'
      ps = ", ".join(self.params)
      return f'import {self.module}.{self.name}({ps}) -> {self.return_type};'
  


class TypeExpr:
    def __init__(self, name, params = None, pos = None):
        if not isinstance(name, str):
            raise TypeError(f"name must be a str, cannot be {type(name)}")
        self.name = name
        self.params = params or []
        self.pos = pos

    def __str__(self):
        params = ""
        if self.params:
            params = f"<{', '.join(param.name for param in self.params)}>"
        return f"{self.name}{params}"
    
    def __eq__(self, other):
        return (
            isinstance(other, TypeExpr)
            and self.name == other.name
            and self.params == other.params
        )
    def __hash__(self):
        return hash((self.name, tuple(self.params)))




# in muni2wasm/ast.py

class AliasDeclaration():
    def __init__(self, name: str, type_params: list[str], aliased: TypeExpr, pos=None):
        self.name         = name
        self.type_params  = type_params
        self.aliased      = aliased
        self.pos          = pos

    def __str__(self):
        if self.type_params:
            return f"alias {self.name}<{', '.join(self.type_params)}> = {self.aliased};"
        return f"alias {self.name} = {self.aliased};"
    


class CharLiteral:
    def __init__(self, literal: str, pos=None):
        try:
            value = ast.literal_eval(literal)
        except Exception as e:
            raise SyntaxError(f"Bad character literal {literal}") from e
        if len(value) != 1:
            raise ValueError(f"Character literal must be exactly one character, got {literal!r}")
        self.value = value
        self.pos = pos

    def __str__(self):
        return f"char('{self.value}')"

class StringLiteral:
    def __init__(self, literal: str, pos=None):
        try:
            value = ast.literal_eval(literal)
        except Exception as e:
            raise SyntaxError(f"Bad string literal {literal}") from e
        self.value = value
        self.pos = pos

    def __str__(self):
        return f'string("{self.value}")'