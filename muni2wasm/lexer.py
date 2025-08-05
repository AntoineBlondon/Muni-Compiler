import re
from collections import namedtuple


TOKEN_SPEC = [
    (r'"(?:\\.|[^"\\])*"',      "STRING"),
    (r"'(?:\\.|[^'\\])'",       "CHAR"),
    (r"null\b",                 "NULL_KW"),
    (r"void\b",                 "VOID_KW"),
    (r"int\b",                  "INT_KW"),
    (r"boolean\b",              "BOOL_KW"),
    (r"array\b",                "ARRAY_KW"),
    (r"import\b",               "IMPORT_KW"),   
    (r"structure\b",            "STRUCTURE_KW"),
    (r"static\b",               "STATIC_KW"),
    (r"return\b",               "RETURN_KW"),
    (r"if\b",                   "IF_KW"),
    (r"else\b",                 "ELSE_KW"),
    (r"for\b",                  "FOR_KW"),
    (r"while\b",                "WHILE_KW"),
    (r"until\b",                "UNTIL_KW"),
    (r"do\b",                   "DO_KW"),
    (r"break\b",                "BREAK_KW"),
    (r"continue\b",             "CONTINUE_KW"),
    (r"true\b",                 "TRUE"),
    (r"false\b",                "FALSE"),
    (r"[0-9]+",                 "NUMBER"),
    (r"[A-Za-z_][A-Za-z0-9_]*", "IDENT"),
    (r"->",                     "RARROW"),
    (r"[+\-*/%]=?|&&|\|\||==|!=|<=|>=|!",     "OP"),
    (r"<",                      "LT"),
    (r">",                      "GT"),
    (r"=",                      "ASSIGN"),
    (r",",                      "COMMA"),
    (r";",                      "SEMI"),
    (r"\.",                     "DOT"),
    (r"\(",                     "LPAREN"),
    (r"\)",                     "RPAREN"),
    (r"\{",                     "LBRACE"),
    (r"\}",                     "RBRACE"),
    (r"\[",                     "LBRACK"),
    (r"\]",                     "RBRACK"),
    (r"#.*",                     None),
    (r"/\*[\s\S]*?\*/",          None),
    (r"\s+",                     None),
]


Token = namedtuple("Token", ["kind", "text", "line", "col"])

def tokenize(code: str):
    tokens = []
    line, col = 1, 0
    i = 0
    while i < len(code):
        for pattern, kind in TOKEN_SPEC:
            m = re.compile(pattern).match(code, i)
            if not m:
                continue
            text = m.group(0)
            if kind:
                tokens.append(Token(kind, text, line, col))
            # update line/col
            lines = text.split("\n")
            if len(lines) > 1:
                line += len(lines) - 1
                col = len(lines[-1])
            else:
                col += len(text)
            i = m.end()
            break
        else:
            raise SyntaxError(f"{line}:{col}: Unknown token {code[i]!r}")
    tokens.append(Token("EOF", "", line, col))
    return tokens
