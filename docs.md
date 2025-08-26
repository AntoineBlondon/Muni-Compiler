# 📘 Muni Language Documentation

## 1. Introduction
- What is Muni?
- Features
- An example

```muni
import <... .lib>

void main()
{

}

```


## 2. Language Basics
- Comments
In muni, there are two types of comments:

```muni
# this is a single line comment

/* 
   and this
   is a multiline comment
*/
```

They are ignored by the lexer.


- Variables
Variables can be declared like this:

```muni
int x = 3;
boolean i_am_true = true;
float something = 21.453;
```

- Builtin Types

primitives:
    i32:
    - int
    - boolean
    - char
    f32:
    - float

structures:
    - array
    - vec
    - string

functions only:
    - void


- Control Flow

if else
while
until
for
do X while



## 3. Functions
- Declaration
- Return types
- Function calls
- Recursion
- Generics

## 4. Structures
- Declaring structures

```
structure Point {
    int x;
    int y;
    
    Point(int x, int y) {
        this.x = x;
        this.y = y;
    }

    static Point origin() {
        return Point(0, 0);
    }

    void add(Point p) {
        this.x += p.x;
        this.y += p.y;
    }
}
```
- Fields and methods
- Member access
- `this` keyword
- Static methods

## 5. Arrays
- Creating arrays
- Accessing elements
- Length
- Nested arrays

## 6. Vectors
- 

## 7. Strings
- Literals
- Concatenation
- Methods
- Conversions

## 8. Aliases
- Declaring aliases
- Behavior in semantics

## 9. Imports
- Syntax
- Standard library
- Custom libraries

## 10. Advanced Topics
- Generics
- Hashmaps
- Casting
- Null safety
- Optionals / Result types

## 11. Compilation and Runtime
- Muni → WASM pipeline
- Runtime functions
- Memory management
- Optimizations

## 12. Formal Grammar
- Tokenization
- Grammar (EBNF)

## 13. Examples
- TicTacToe
- Calculator
- Hashmaps
- Strings

## 14. Future Directions
- Planned features
- Design philosophy
