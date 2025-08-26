# importer.py
from importlib.resources import files, as_file
import sys
from pathlib import Path
from typing import Optional, Set

from .ast import FunctionDeclaration, Program, ImportDeclaration
from .lexer import tokenize
from .parser import Parser


def inline_file_imports(
    ast: Program,
    base_dir: Path,
    seen: Optional[Set[Path]] = None
) -> tuple[Program, Set[Path]]:
    """
    Recursively inline all file-based and .lib imports into the AST.
    Uses a single 'seen' set of absolute paths (files and libs) to avoid duplicates/cycles.
    """
    if seen is None:
        seen = set()

    new_decls = []
    
    for decl in ast.decls:
        if isinstance(decl, ImportDeclaration) and decl.source:
            if decl.source.endswith(".lib"):
                child_ast = load_library(decl.source)
                lib_abs = (base_dir / "lib" / decl.source).resolve()
                if child_ast is None or Path(lib_abs) in seen: continue
                seen.add(Path(lib_abs))

                child_ast, _ = inline_file_imports(child_ast, lib_abs.parent, seen)
                new_decls.extend([d for d in child_ast.decls if not (isinstance(d, FunctionDeclaration) and d.name == "main")])
                continue

            if decl.source.endswith(".mun"):
                import_path = (base_dir / decl.source).resolve()
                if import_path in seen: continue
                if not import_path.is_file():
                    print(f"Error: import file not found: {import_path}", file=sys.stderr)
                    sys.exit(1)
                seen.add(import_path)

                src = import_path.read_text(encoding="utf-8")
                tokens = tokenize(src)
                child_ast = Parser(tokens).parse()

                child_ast, _ = inline_file_imports(child_ast, import_path.parent, seen)
                new_decls.extend([d for d in child_ast.decls if not (isinstance(d, FunctionDeclaration) and d.name == "main")])
        else:
            new_decls.append(decl)

    ast.decls = new_decls
    return ast, seen



def load_library(lib_name: str) -> Optional[Program]:
    """Load a .lib (actually a .mun file in muni2wasm/lib) into an AST."""
    with as_file(files("muni2wasm").joinpath("lib")) as lib_dir:
        if lib_name.endswith(".lib"):
            lib_name = lib_name[:-4]
        lib_path = (lib_dir / (lib_name + ".mun"))
        if not lib_path.is_file():
            return None

        src = lib_path.read_text(encoding="utf-8")
        tokens = tokenize(src)
        return Parser(tokens).parse()



def import_standard_lib(ast: Program, seen: Optional[Set[Path]] = None) -> tuple[Program, Set[Path]]:
    """
    Load and inline std.mun from the standard-library 'lib' directory.
    Share the same 'seen' set so libs aren't duplicated if user code imports them too.
    """
    if seen is None:
        seen = set()

    lib_dir = files("muni2wasm").joinpath("lib")
    # Convert to Path
    std_path = Path(str(lib_dir / "std.lib"))
    if std_path in seen:
        return ast, seen
    seen.add(std_path)

    # now replace .lib with .mun
    std_path = std_path.with_suffix(".mun")

    if not std_path.is_file():
        return ast, seen
    child_ast = load_library("std.lib")

    child_ast, _ = inline_file_imports(child_ast, std_path.parent, seen)  # type: ignore
    ast.decls.extend(child_ast.decls)

    return ast, seen
