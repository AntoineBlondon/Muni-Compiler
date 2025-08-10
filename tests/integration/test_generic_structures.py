from muni_test import *
import pytest

box_struct = r"""
structure Box<T> {
    T value;

    # constructor
    Box<T>(T v) { this.value = v; }

    # instance methods
    T get() { return this.value; }
    void set(T v) { this.value = v; }

    # static helper
    static Box<T> make(T v) {
        Box<T> b = Box<T>(v);
        return b;
    }
}
"""

# ---------------- OK CASES ----------------
ok_cases = [
# basic int box: ctor, get/set, static make
(box_struct + r"""
void main() {
    Box<int> bi = Box<int>(10);
    write_int(bi.get());  # 10
    bi.set(42);
    write_int(bi.get());  # 42

    Box<int> bj = Box<int>.make(7);
    write_int(bj.get());  # 7
}
""", ["10", "42", "7"]),

# boolean box with if
(box_struct + r"""
void main() {
    Box<boolean> bb = Box<boolean>(true);
    if (bb.get()) { write_int(1); } else { write_int(0); }  # 1
    bb.set(false);
    if (bb.get()) { write_int(1); } else { write_int(0); }  # 0
}
""", ["1", "0"]),

# nested boxes: Box<Box<int>>
(box_struct + r"""
void main() {
    Box<int> inner = Box<int>(3);
    Box<Box<int>> outer = Box<Box<int>>(inner);
    Box<int> got = outer.get();
    write_int(got.get());  # 3

    got.set(9);
    write_int(outer.get().get());  # 9
}
""", ["3", "9"]),

# pass/return through functions
(box_struct + r"""
int read_and_inc(Box<int> b) {
    int v = b.get();
    b.set(v + 1);
    return v;
}

void main() {
    Box<int> b = Box<int>(10);
    write_int(read_and_inc(b));  # 10 (returned old value)
    write_int(b.get());          # 11 (mutated in function)
}
""", ["10", "11"]),

# array of Box<int> (exercise storing/reading boxed values)
(box_struct + r"""
void main() {
    array<Box<int>> a = array<Box<int>>(2);
    a.set(0, Box<int>(5));
    a.set(1, Box<int>(8));

    Box<int> b0 = a.get(0);
    Box<int> b1 = a.get(1);
    write_int(b0.get());  # 5
    write_int(b1.get());  # 8
}
""", ["5", "8"]),

(box_struct + r"""
 void main() {
    Box<int> inner = Box<int>(2);
    Box<Box<int>> o1 = Box<Box<int>>.make(inner);
    write_int(o1.get().get());   # 2
}
""", ["2"]),

(box_struct + r"""
void main() {
    array<int> a = array<int>(3);
    a.set(0, 10); a.set(1, 20); a.set(2, 30);
    Box<array<int>> ba = Box<array<int>>(a);
    write_int(ba.get().get(1));  # 20
}
""", ["20"]),

# Box<vec<int>> via string alias plumbing (string = vec<char>), and nested
(box_struct + r"""
void main() {
    string s = "hi";            # vec<char>
    Box<string> bs = Box<string>(s);
    write_int(bs.get().size);   # relies on your vec<T> fields; adjust if different
}
""", ["2"]),

# array<Box<Box<int>>> roundtrip
(box_struct + r"""
void main() {
    Box<int> inner = Box<int>(4);
    Box<Box<int>> outer = Box<Box<int>>(inner);
    array<Box<Box<int>>> arr = array<Box<Box<int>>>(1);
    arr.set(0, outer);
    write_int(arr.get(0).get().get());  # 4
}
""", ["4"]),

# Function producing/consuming Box<T> of different Ts (two functions)
(box_struct + r"""
Box<int> bump(Box<int> b) {
    b.set(b.get() + 1);
    return b;
}
Box<boolean> flip(Box<boolean> b) {
    b.set(!b.get());
    return b;
}
void main() {
    Box<int> bi = Box<int>(7);
    write_int(bump(bi).get());      # 8
    Box<boolean> bb = Box<boolean>(true);
    if (flip(bb).get()) { write_int(1); } else { write_int(0); }  # 0
}
""", ["8", "0"]),
]

@pytest.mark.parametrize("src,expected", ok_cases)
def test_generic_box_ok(src, expected):
    lines = run_muni(src)
    assert lines == expected


# ---------------- ERROR CASES ----------------
err_cases = [
# wrong arity on constructor type args
(box_struct + r"""
void main() {
    Box<int,int> b = Box<int,int>(1);
}
""", "Constructor 'Box' expects 1 type-arg(s), got 2"),

# constructor argument type mismatch
(box_struct + r"""
void main() {
    Box<int> b = Box<int>(true);
}
""", "expects int, got boolean"),

# calling instance method as static
(box_struct + r"""
void main() {
    int x = Box<int>.get();  # get is not static
}
""", "No static method 'get'"),

# calling static method on an instance
(box_struct + r"""
void main() {
    Box<int> b = Box<int>(3);
    b.make(9);  # make is static
}
""", "Cannot call static method 'make' on instance of 'Box'"),

# # wrong arity on static method type args (make takes 0 method type-params)
# (box_struct + r"""
# void main() {
#     Box<int> b = Box<int>(1);
#     Box<int> c = Box<int>.make<boolean>(2);  # make has no method type-params
# }
# """, "Method 'make' expects 0 type-arg(s), got 1"),

# wrong number of ctor *value* args (too many)
(box_struct + r"""
void main() {
    Box<int> b = Box<int>(1, 2);  # extra arg not allowed
}
""", "Box<int> has 2 arg(s), expected 1"),

# # unknown payload type for Box
# (box_struct + r"""
# void main() {
#     Box<Foo> x = Box<Foo>(1);
# }
# """, "Unknown type 'Foo'"),

# function expects Box<int> but you pass Box<boolean>
(box_struct + r"""
int take_box_int(Box<int> b) { return b.get(); }
void main() {
    Box<boolean> bb = Box<boolean>(true);
    int x = take_box_int(bb);
}
""", "In call to 'take_box_int', expected Box<int>, got Box<boolean>"),
]

@pytest.mark.parametrize("src,needle", err_cases)
def test_generic_box_err(src, needle):
    msg = compile_error(src)
    assert needle in msg
