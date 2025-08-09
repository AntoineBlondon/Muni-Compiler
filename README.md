# muni2wasm

A compiler that takes Muni source code and turns it into WebAssembly.

Written in Python and comes with a CLI. No system tools needed, `wabt` is used via python, and you can optionally run the compiled `.wasm` with `wasmtime`

[source directory](https://github.com/AntoineBlondon/Muni-Compiler)


## Table of content



## Installation

```bash
pip install muni2wasm
```

Python 3.10+ recommended.


## TL;DR

```bash
# compile .mun to .wasm
muni2wasm compile hello.mun out.wasm

# run .wasm with a Python binding
muni2wasm run out.wasm
```
Use `--debug` to see full Python traceback on errors


## Muni Language

### Types

From WebAssembly's toolkit (i32, i64, f32, f64)
Muni only supports i32 (for now)

primitives
`int`, `boolean`, `char`


`void` for functions that don't return anything


generic array
`array<T>`
of any length


`structure`

user defined type with fields and methods
(defined at top level)

either static or instantiated

```muni

structure List<T> {
    T element;
    List<T> next;

    List<T>(T element) # constructor function
    {
        this.element = element;
        this.next = null;
    }

    void append(T element)
    {
        List<T> cur = this;
        while (cur.next != null) {
            cur = cur.next;
        }
        cur.next = List<T>(element);
    }

}

void main()
{
    # now we can do
    List<int> my_list = List<int>(3);

    my_list.append(4);

}

```



### Type aliases
```muni
alias numbers = array<int>;

alias index<T> = pair<int, T>;
```
(defined at top level)

### Functions

Functions are defined at top level

### Control flow

if/else

for

while

until

do X while



### Operators

### Literals

123, true/false, 'x', "\n", [1,2,3], null

### Imports

1. File imports (inlines another `.mun` file, path is relative to the importing file):

```muni
import <something.mun>
```

1. Library imports (coming very soon)

1. Host imports (declares a host function):

```muni
import module.function(int, array<char>) -> void;
```

### Strings

`string` is an alias for `vec<char>`
(and `char` is just an alias for `int`)

`vec<T>` is a structure around `array<T>` with size, capacity and methods like get, set, push_back, etc...
(vectors are defined in [std.mun](https://github.com/AntoineBlondon/Muni-Compiler/muni2wasm/lib/std.mun))

`array<T>` is a header { length, buffer_ptr }. buffer_ptr points into linear memory.

the `print` function is also defined in [std.mun](https://github.com/AntoineBlondon/Muni-Compiler/muni2wasm/lib/std.mun)


## CLI

```muni
muni2wasm compile <input.mun> <output.(wat|wasm)> [--debug]
muni2wasm run <module.wasm> [--debug]
```

- `compile` emits .wat or .wasm (depending on output suffix).

- `run` loads the module with Wasmtime and wires simple env imports:

    * env.write_int(i32) -> prints an integer

    * env.write_chr(i32) -> prints a character

## Notes

## Contributing

PRs and discussions welcome!

Next steps:
- add floats as wasm f32
- better error handling
- tests, tests, tests...
- better Python environment 
- create a js environment for webapps
- add lambda lifting to be able to define functions in functions
- add lambda expressions

