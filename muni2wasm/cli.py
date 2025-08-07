#!/usr/bin/env python3
"""
muni2wasm CLI — built with Typer for improved UX and extensibility.
"""
import sys
import logging
from pathlib import Path
import typer

from .compiler import compile_file, run_wasm

app = typer.Typer(
    help="Compile and run .mun programs with WebAssembly"
)


@app.command("compile")
def compile_cmd(
    input_file: Path = typer.Argument(
        ..., exists=True, file_okay=True, dir_okay=False,
        help="Path to the .mun source file to compile"
    ),
    output_file: Path = typer.Argument(
        ..., writable=True, file_okay=True, dir_okay=False,
        help="Destination path (must end with .wat or .wasm)"
    ),
    std_dir: Path = typer.Option(
        Path("std"), exists=False, file_okay=False, dir_okay=True,
        help="Path to the standard library directory (defaults to 'std' relative to CWD)"
    ),
    debug: bool = typer.Option(
        False, "--debug", "-d",
        help="Enable debug logging and full tracebacks"
    ),
):
    """
    Compile a .mun source file into a WebAssembly text (.wat) or binary (.wasm).
    """
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="[%(levelname)s] %(message)s"
    )

    # logging.info(f"Compiling {input_file} → {output_file} (std={std_dir})")
    try:
        compile_file(
            str(input_file),
            str(output_file),
            std_dir=str(std_dir)
        )
    except Exception as e:
        if debug:
            raise
        logging.error(f"{input_file}:{e}")
        sys.exit(1)


@app.command("run")
def run_cmd(
    wasm_file: Path = typer.Argument(
        ..., exists=True, file_okay=True, dir_okay=False,
        help="Path to the compiled .wasm module"
    ),
    debug: bool = typer.Option(
        False, "--debug", "-d",
        help="Enable debug logging and full tracebacks"
    ),
):
    """
    Execute a .wasm module produced from a .mun program.
    """
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="[%(levelname)s] %(message)s"
    )
    # logging.info(f"Running {wasm_file}")
    try:
        run_wasm(str(wasm_file))
    except Exception as e:
        if debug:
            raise
        logging.error(f"error: {e}")
        sys.exit(1)


def main():
    app()


if __name__ == "__main__":
    main()
