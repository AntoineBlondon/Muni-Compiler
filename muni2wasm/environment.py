from wasmtime import FuncType, ValType, Memory
from typing import Optional, Dict
from .env_python import wasi_write_int, wasi_write_chr, wasi_write_flt, get_wasi_input, trap_oob, trap_div0, debug_i32





def register_host_functions(linker, store) -> Dict[str, Optional[Memory]]:
    """
    Define custom host functions on the given Linker and return a memory reference dict.

    Returns:
        A dict with key 'mem' that should be set to the module's Memory after instantiation.
    """
    memory_ref: Dict[str, Optional[Memory]] = {'mem': None}

    
    linker.define_func("env", "write_int", FuncType([ValType.i32()], []), wasi_write_int)
    linker.define_func("env", "write_chr", FuncType([ValType.i32()], []), wasi_write_chr)
    linker.define_func("env", "write_flt", FuncType([ValType.f32()], []), wasi_write_flt)
    linker.define_func("env", "input", FuncType([], [ValType.i32()]), get_wasi_input(memory_ref, store))
    linker.define_func("muni", "trap_oob", FuncType([ValType.i32(), ValType.i32(), ValType.i32(), ValType.i32()], []), trap_oob)
    linker.define_func("muni", "trap_div0", FuncType([ValType.i32(), ValType.i32()], []), trap_div0)
    linker.define_func("muni", "debug_i32", FuncType([ValType.i32()], []), debug_i32)

    return memory_ref
