# muni2wasm

A compiler that turns Muni source code into WebAssembly.

* Written in Python, ships with a CLI
* No system tools required — uses the Python WABT package to assemble
* Optional: run the resulting `.wasm` with Wasmtime (Python binding)

## Table of contents

* [Installation](#installation)
* [Quick start](#quick-start)
* [The Muni language](#the-muni-language)

  * [Types](#types)
  * [Structures & generics](#structures--generics)
  * [Type aliases](#type-aliases)
  * [Control flow](#control-flow)
  * [Operators](#operators)
  * [Literals](#literals)
  * [Imports](#imports)
  * [Strings](#strings)
* [CLI](#cli)
* [Notes & limitations](#notes--limitations)
* [Contributing](#contributing)
* [License](#license)

## Installation

```bash
pip install muni2wasm
```

Python 3.10+ recommended.


## Quick start

```bash
# Compile .mun → .wasm
muni2wasm compile hello.mun out.wasm

# Run .wasm (requires wasmtime)
muni2wasm run out.wasm
```

Use `--debug` to see full Python tracebacks on errors.

## The Muni language

> This implementation is quite old and doesn't follow the [specifications](https://github.com/AntoineBlondon/Muni-Compiler/the_muni_specifications-V1.pdf) perfectly, I am currently rewriting the compiler to be complient with Version 1.

### Types

* Primitives: `int`, `boolean`, `char`
* Special: `void` (functions that don’t return a value)
* Generic array: `array<T>`
* User types: `structure` (fields + methods, can be generic)

> Internally targets WebAssembly i32 for now.

### Structures & generics

```muni
structure List<T> {
    T element;
    List<T> next;

    List<T>(T element) {     # constructor
        this.element = element;
        this.next = null;
    }

    void append(T element) {
        List<T> cur = this;
        while (cur.next != null) {
            cur = cur.next;
        }
        cur.next = List<T>(element);
    }
}

void main() {
    List<int> xs = List<int>(3);
    xs.append(4);
}
```

### Type aliases

```muni
alias numbers   = array<int>;
alias index<T>  = pair<int, T>;
```

### Control flow

* `if / else`
* `for (init; cond; post) { ... }`
* `while (cond) { ... }`
* `until (cond) { ... }`
* `do <X> { ... } <while (cond)>`

### Operators

* Arithmetic: `+ - * / %` (ints)
* Comparisons: `> < >= <= == !=` (mostly ints)
* Logical: `&& || !`
* Unary: `-` (negate), `!` (not)

### Literals

```
123
true / false
'x'   # char
"hello!\n"  # string
[1, 2, 3]  # array literal
null
```

### Imports

1. File imports (inlines another `.mun` file; path is relative):

```muni
import <vector.mun>;
```

2. Library imports (inlines a library file)

```muni
import <math.lib>; # imports the math.mun lib
```


3. Host imports (declare a host function available at runtime):

```muni
import env.write_int(int) -> void;
import env.write_chr(int) -> void;
```

### Strings

`string` is an alias for `vec<char>` (and `char` is just an alias for `int`).

* `vec<T>` is structure that represents a growable vector around `array<T>` with `size`, `capacity`, `get`, `set`, `push_back`, …
* `array<T>` layout is `{ length, buffer_ptr }` in linear memory.

The standard helpers live in `lib/std.mun` (e.g., the definition of vec<T>, a `print(string)` that calls the host `env.write_chr` per character).

## CLI

```text
muni2wasm compile <input.mun> <output.(wat|wasm)> [--debug]
muni2wasm run     <module.wasm>                  [--debug]
```

* `compile` emits `.wat` or `.wasm` (based on the output suffix), assembling via Python WABT.
* `run` loads the module with Wasmtime and wires a minimal host environment:

  * `env.write_int(i32)` — print integer
  * `env.write_chr(i32)` — print a single character code (ASCII/UTF-8 byte)

> You can define your own host imports and call them from Muni via `import module.name(...) -> ...;`.

## Notes

* Currently uses i32 only (no floats yet).
* `char` is an `int` under the hood; escape sequences like `'\n'` are supported.
* Strings are `vec<char>`; printing strings typically iterates chars and calls `write_chr`.
* Type aliases are expanded before type-checking; generic arity is validated.
* Diagnostics include `file:line:col`.

## Contributing

PRs and discussions welcome! Ideas & roadmap:

* Add `f32`
* Better diagnostics
* More stdlib (strings, I/O helpers)
* JS/Web runner
* Lambdas / closures (and lambda lifting)
* More tests

## License

MIT
