#!/usr/bin/env python3
"""
environment.py

Defines and registers host functions (environment) for WebAssembly modules.
Provides a simple custom environment with print and string-print capabilities.
"""
from wasmtime import FuncType, ValType, Memory
import sys
from typing import Optional, Dict


def register_host_functions(linker, store) -> Dict[str, Optional[Memory]]:
    """
    Define custom host functions on the given Linker and return a memory reference dict.

    Returns:
        A dict with key 'mem' that should be set to the module's Memory after instantiation.
    """
    memory_ref: Dict[str, Optional[Memory]] = {'mem': None}

    def wasi_print(x: int) -> None:
        # Print an integer followed by newline
        print(x)

    def wasi_write_chr(x: int) -> None:
        # Print a single character
        sys.stdout.write(chr(x))
        sys.stdout.flush()

    def wasi_print_string(vec_ptr: int) -> None:
        # Print a UTF-8 string stored as a vec<char> pointer in WASM memory
        mem = memory_ref['mem']
        if mem is None:
            raise RuntimeError("Memory not available for print_str")
        # Read data pointer (0..4) and size (4..8)
        data_ptr = int.from_bytes(mem.read(store, vec_ptr, vec_ptr + 4), 'little')
        size = int.from_bytes(mem.read(store, vec_ptr + 4, vec_ptr + 8), 'little')
        # Read buffer pointer from array struct at data_ptr+4..8
        buf_ptr = int.from_bytes(mem.read(store, data_ptr + 4, data_ptr + 8), 'little')
        # Read size*4 bytes, extract low byte of each i32
        raw = mem.read(store, buf_ptr, buf_ptr + size * 4)
        chars = bytes(raw[i] for i in range(0, len(raw), 4))
        sys.stdout.write(chars.decode('utf-8', errors='replace'))
        sys.stdout.flush()

    # Register functions under the "env" module
    linker.define_func("env", "print", FuncType([ValType.i32()], []), wasi_print)
    linker.define_func("env", "write_chr", FuncType([ValType.i32()], []), wasi_write_chr)
    linker.define_func("env", "print_str", FuncType([ValType.i32()], []), wasi_print_string)

    return memory_ref
