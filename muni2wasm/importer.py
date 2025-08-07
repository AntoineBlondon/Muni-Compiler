    #!/usr/bin/env python3
"""
importer.py

Handles standard library imports and inlining of file-based imports
for the muni compiler pipeline.
"""
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
            child_ast = inline_file_imports(child_ast, import_path.parent, seen)

            # Splice in the child's top-level declarations
            new_decls.extend(child_ast.decls)
        else:
            new_decls.append(decl)

    ast.decls = new_decls
    return ast


def import_standard_files(
    ast: Program,
    compiler_dir: Path,
    std_dir: Optional[Path] = None
) -> Program:
    """
    Load and inline all .mun files from the standard library directory.

    - If std_dir is None, defaults to compiler_dir / 'std'.
    - Each std file is parsed, its file-imports are inlined,
      and its declarations are appended to the AST.
    """
    if std_dir is None:
        std_dir = (compiler_dir / "std").resolve()
    else:
        std_dir = std_dir.resolve()

    if not std_dir.is_dir():
        return ast

    for path in sorted(std_dir.iterdir()):
        if path.suffix == ".mun" and path.is_file():
            src = path.read_text(encoding="utf-8")
            tokens = tokenize(src)
            child_ast = Parser(tokens).parse()
            # Inline any file-based imports within the std file
            child_ast = inline_file_imports(child_ast, path.parent)
            # Append std declarations
            ast.decls.extend(child_ast.decls)

    return ast
