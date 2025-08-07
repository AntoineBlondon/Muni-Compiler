from curses import raw
import sys
import os
import subprocess
import tempfile
import argparse

from wasmtime import Memory

from .lexer import tokenize
from .ast import Program, ImportDeclaration
from .parser import Parser
from .codegen_wat import CodeGen
from .semantics import SemanticError, SemanticChecker

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
    ast = import_standard_files(ast, base_dir)
    ast = _inline_file_imports(ast, base_dir)
    SemanticChecker(ast).check()
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

def import_standard_files(ast: Program, base_dir: str) -> Program:
    """
    Import standard library files into the AST.
    This is done by looking for files in the `std` directory relative to the base_dir.
    """
    std_dir = os.path.join(base_dir, "../std")
    if not os.path.isdir(std_dir):
        return ast  # No standard library, nothing to import

    # List all .mun files in the std directory
    for filename in os.listdir(std_dir):
        if filename.endswith(".mun"):
            path = os.path.join(std_dir, filename)
            src = open(path, "r").read()
            toks = tokenize(src)
            child = Parser(toks).parse()
            child = _inline_file_imports(child, std_dir)
            ast.decls.extend(child.decls)

    return ast


def run_wasm(wasm_file: str):
    if not _HAS_WASMTIME:
        print("Error: wasmtime Python bindings not installed. Try `pip install wasmtime`.", file=sys.stderr)
        sys.exit(1)

    store = Store()
    linker = Linker(store.engine)
    
    
    def wasi_print(x: int) -> None:
        print(x)
    
    


    def wasi_print_string(vec_ptr: int) -> None:
        """
        Print a string from a vec<char> (vec<int>) structure in WASM memory.
        
        Memory layout:
        vec<int> at vec_ptr:
        0-4:   data (pointer to array<int> struct)
        4-8:   size (number of characters)
        8-12:  capacity
        
        array<int> struct at data pointer:
        0-4:   length
        4-8:   buffer (pointer to actual int array)
        """
        
        # 1) Read the 'data' field from vec struct (pointer to array<int>)
        data_array_ptr = int.from_bytes(
            memory.read(store, vec_ptr, vec_ptr + 4),
            "little",
        )
        
        # 2) Read the 'size' field from vec struct (number of characters)
        size = int.from_bytes(
            memory.read(store, vec_ptr + 4, vec_ptr + 8),
            "little",
        )
        
        # 3) From the array struct, read the 'buffer' field (pointer to int array)
        buf_ptr = int.from_bytes(
            memory.read(store, data_array_ptr + 4, data_array_ptr + 8),
            "little",
        )
        
        # 4) Read size*4 bytes starting at buf_ptr (each int is 4 bytes)
        raw = memory.read(store, buf_ptr, buf_ptr + size * 4)
        
        # 5) Extract the low byte of each little-endian 32-bit int
        chars = bytes(raw[i] for i in range(0, len(raw), 4))
        
        # 6) Decode and print
        print(chars.decode("utf-8", errors="replace"))
    
    def wasi_write_chr(x: int) -> None:
        """
        Print a single character (int) to stdout.
        """
        print(chr(x), end='')

    linker.define_func(
        "env", "print",
        FuncType([ValType.i32()], []),
        wasi_print
    )
    linker.define_func(
        "env", "print_str",
        FuncType([ValType.i32()], []),
        wasi_print_string
    )
    linker.define_func(
        "env", "write_chr",
        FuncType([ValType.i32()], []),
        wasi_write_chr
    )
    module   = Module.from_file(store.engine, wasm_file)
    instance = linker.instantiate(store, module)
    memory: Memory = instance.exports(store).get("memory") # type: ignore
    if memory is None:
        print("Error: module has no `memory` export", file=sys.stderr)
        sys.exit(1)
    
    
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
