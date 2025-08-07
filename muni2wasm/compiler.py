import os
import sys
import subprocess
import tempfile
from pathlib import Path
import logging

from wasmtime import Memory, Store, Linker, Module

from .lexer import tokenize
from .parser import Parser
from .codegen_wat import CodeGen
from .semantics import SemanticChecker
from .environment import register_host_functions
from .importer import import_standard_files, inline_file_imports


def compile_to_wat(source: str, compiler_dir: Path, std_dir: Path | None = None) -> str:
    """
    Lex, parse, import standard files, inline file imports,
    run semantic checks, and generate WAT.
    """
    tokens = tokenize(source)
    ast = Parser(tokens).parse()

    ast = import_standard_files(ast, compiler_dir, std_dir)
    ast = inline_file_imports(ast, compiler_dir)

    SemanticChecker(ast).check()
    return CodeGen(ast).gen()


def compile_file(input_path: str, output_path: str, std_dir: str | Path = "std") -> None:
    """
    Read a .mun file, compile to WAT or WASM, and write to disk.
    """
    inp = Path(input_path)
    out = Path(output_path)
    src = inp.read_text(encoding="utf-8")
    wat = compile_to_wat(src, inp.parent.parent)

    out.parent.mkdir(parents=True, exist_ok=True)
    ext = out.suffix.lower()
    if ext == ".wat":
        out.write_text(wat, encoding="utf-8")
        logging.info(f"Generated {out}")
        return

    if ext == ".wasm":
        # dump to temporary wat file
        with tempfile.NamedTemporaryFile("w+", suffix=".wat", delete=False) as tmp:
            tmp.write(wat)
            tmp.flush()
            tmp_path = tmp.name
        proc = subprocess.run(
            ["wat2wasm", tmp_path, "-o", str(out)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        os.remove(tmp_path)
        if proc.returncode != 0:
            logging.error(proc.stderr.decode())
            sys.exit(proc.returncode)
        logging.info(f"Generated {out}")
        return

    logging.error("Output must end with .wat or .wasm")
    sys.exit(1)




def run_wasm(wasm_path: str) -> None:
    """
    Instantiate and execute a wasm module with a custom host environment.
    """
    wasm = Path(wasm_path)
    if not wasm.exists():
        logging.error(f"File not found: {wasm}")
        sys.exit(1)

    # Initialize Wasmtime store & linker
    store = Store()
    linker = Linker(store.engine)

    # Register your env funcs and get the memory‐ref container
    memory_ref = register_host_functions(linker, store)

    # Load + instantiate
    module = Module.from_file(store.engine, str(wasm))
    instance = linker.instantiate(store, module)

    # Grab the memory export correctly:
    exports = instance.exports(store)
    mem_extern = exports.get("memory")
    if mem_extern is None or not isinstance(mem_extern, Memory):
        logging.error("Module has no valid `memory` export")
        sys.exit(1)
    memory_ref["mem"] = mem_extern

    # Finally, call `main`
    main_fn = exports.get("main")
    if main_fn is None:
        logging.error("No 'main' export found in module.")
        sys.exit(1)

    main_fn(store)  # execute # type: ignore
