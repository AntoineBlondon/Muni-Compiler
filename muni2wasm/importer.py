    #!/usr/bin/env python3
"""
importer.py

Handles standard library imports and inlining of file-based imports
for the muni compiler pipeline.
"""
from importlib.resources import files, as_file
import sys
from pathlib import Path
from typing import Optional, Set

from .ast import Program, ImportDeclaration
from .lexer import tokenize
from .parser import Parser


def inline_file_imports(
    ast: Program,
    base_dir: Path,
    seen: Optional[Set[Path]] = None
) -> Program:
    """
    Recursively inline all file-based imports in the AST.

    - "seen" tracks already inlined file paths to avoid cycles.
    - "base_dir" is the directory against which relative imports are resolved.
    """
    if seen is None:
        seen = set()

    new_decls = []
    for decl in ast.decls:
        if isinstance(decl, ImportDeclaration) and decl.source:
            import_path = (base_dir / decl.source).resolve()
            if import_path in seen:
                # Skip cyclic import
                continue
            if not import_path.is_file():
                print(f"Error: import file not found: {import_path}", file=sys.stderr)
                sys.exit(1)
            seen.add(import_path)

            # Read and parse the imported file
            src = import_path.read_text(encoding="utf-8")
            tokens = tokenize(src)
            child_ast = Parser(tokens).parse()

            # Inline the child's imports
            child_ast = inline_file_imports(child_ast, import_path.parent, seen) #type: ignore

            # Splice in the child's top-level declarations
            new_decls.extend(child_ast.decls)
        else:
            new_decls.append(decl)

    ast.decls = new_decls
    return ast


def import_standard_lib(ast: Program) -> Program:
    """
    Load and inline std.mun from the standard-library 'lib' directory.
    """
    with as_file(files("muni2wasm").joinpath("lib")) as lib_dir:
        std_path = lib_dir / "std.mun"
        if not std_path.is_file():
            print(std_path)
            return ast

        # read & parse std.mun
        src = std_path.read_text(encoding="utf-8")
        tokens = tokenize(src)
        child_ast = Parser(tokens).parse()

        # inline any file-imports inside std.mun
        child_ast = inline_file_imports(child_ast, std_path.parent) # type: ignore

        # append its decls
        ast.decls.extend(child_ast.decls)

    return ast
