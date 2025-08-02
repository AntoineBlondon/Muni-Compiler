import sys
import os
import subprocess
import tempfile
import argparse

from .lexer import tokenize
from .ast import Program, ImportDeclaration
from .parser import Parser
from .codegen_wat import CodeGen
from .semantics import check, SemanticError

# Try to import wasmtime for the "run" command
try:
    from wasmtime import Store, Linker, Module, FuncType, ValType
    _HAS_WASMTIME = True
except ImportError:
    _HAS_WASMTIME = False

def compile_to_wat(source: str, base_dir: str | None = None) -> str:
    tokens = tokenize(source)
    ast = Parser(tokens).parse()
    if base_dir is None:
        base_dir = os.getcwd()
    ast = _inline_file_imports(ast, base_dir)
    check(ast)
    return CodeGen(ast).gen()

def compile_file(input_file: str, output_file: str):
    # Read source
    source = open(input_file).read()
    base_dir = os.path.dirname(os.path.abspath(input_file))
    wat      = compile_to_wat(source, base_dir)

    # Make sure output directory exists
    out_dir = os.path.dirname(os.path.abspath(output_file))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    ext = os.path.splitext(output_file)[1].lower()
    if ext == ".wat":
        with open(output_file, "w") as f:
            f.write(wat)
        print(f"Generated {output_file}")
        return

    if ext == ".wasm":
        # Dump to a temp .wat
        with tempfile.NamedTemporaryFile("w+", suffix=".wat", delete=False) as tmp:
            tmp.write(wat)
            tmp.flush()
            tmp_path = tmp.name

        # Run wat2wasm, capture errors
        proc = subprocess.run(
            ["wat2wasm", tmp_path, "-o", output_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        os.remove(tmp_path)

        if proc.returncode != 0:
            print(f"Error: wat2wasm failed:\n{proc.stderr.decode()}", file=sys.stderr)
            sys.exit(proc.returncode)
        if not os.path.isfile(output_file):
            print(f"Error: expected {output_file} but it was not created.", file=sys.stderr)
            sys.exit(1)

        print(f"Generated {output_file}")
        return

    # Unknown extension
    print("Error: output file must end with .wat or .wasm", file=sys.stderr)
    sys.exit(1)

def _inline_file_imports(ast: Program, base_dir: str, seen: set[str]=None) -> Program: # type: ignore
    """
    Walk the top‐level ImportDeclarations that have .source set,
    load each file, parse it, recursively inline *its* file‐imports,
    and splice all of those decls in place of the import.
    """
    if seen is None:
        seen = set()
    new_decls = []
    for decl in ast.decls:
        # only care about file imports:
        if isinstance(decl, ImportDeclaration) and decl.source:
            # resolve relative to the importing file's directory
            path = os.path.normpath(os.path.join(base_dir, decl.source))
            if path in seen:
                # already inlined, skip in order to avoid cycles
                continue
            seen.add(path)
            src = open(path, "r").read()
            toks = tokenize(src)
            child = Parser(toks).parse()
            # recurse, using the imported file's dir as new base
            child = _inline_file_imports(child, os.path.dirname(path), seen)
            # splice in everything except nested file‐imports got handled above
            new_decls.extend(child.decls)
        else:
            new_decls.append(decl)
    ast.decls = new_decls
    return ast


def run_wasm(wasm_file: str):
    if not _HAS_WASMTIME:
        print("Error: wasmtime Python bindings not installed. Try `pip install wasmtime`.", file=sys.stderr)
        sys.exit(1)

    store = Store()
    linker = Linker(store.engine)

    def wasi_print(x: int) -> None:
        print(x)

    linker.define_func(
        "env", "print",
        FuncType([ValType.i32()], []),
        wasi_print
    )

    module = Module.from_file(store.engine, wasm_file)
    instance = linker.instantiate(store, module)

    main_fn = instance.exports(store).get("main")
    if main_fn is None:
        print("Error: no `main` export found in module.", file=sys.stderr)
        sys.exit(1)

    main_fn(store) # type: ignore

def main():
    parser = argparse.ArgumentParser(prog="muni2wasm")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="If set, show full Python traceback on errors"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    compile_p = subparsers.add_parser("compile", help="Compile .mun → .wat or .wasm")
    compile_p.add_argument("input", help="Input .mun source file")
    compile_p.add_argument("output", help="Output .wat or .wasm file")

    run_p = subparsers.add_parser("run", help="Run a .wasm module")
    run_p.add_argument("wasm", help="Input .wasm file to execute")

    args = parser.parse_args()

    try:
        if args.command == "compile":
            compile_file(args.input, args.output)
        elif args.command == "run":
            run_wasm(args.wasm)

    except (SyntaxError, SemanticError) as e:
        # If debug, re-raise to see the full traceback
        if args.debug:
            raise

        # Otherwise, print only the concise error
        if args.command == "compile":
            # e.__str__() is "line:col: message"
            print(f"{args.input}:{e}", file=sys.stderr)
        else:
            print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    except Exception as e:
        # Catch any other unexpected exception
        if args.debug:
            raise
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
