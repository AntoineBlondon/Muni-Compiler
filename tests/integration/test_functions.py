import pytest
from muni_test import run_muni, compile_error, runtime_error

# ---------------------------
# OK cases
# ---------------------------

ok_cases = [
# simple call
("""
void main() {
    write_int(1);
}
""", ["1"]),

# call another function
("""
void foo() {
    write_int(2);
}
void main() {
    foo();
}
""", ["2"]),

# return value + use in expression
("""
int add(int a, int b) {
    return a + b;
}
int square(int x) {
    return x * x;
}
void main() {
    write_int(square(add(2, 3)));  # 25
}
""", ["25"]),

# recursion
("""
int fact(int n) {
    if (n <= 1) { return 1; }
    return n * fact(n - 1);
}
void main() {
    write_int(fact(5));  # 120
}
""", ["120"]),

# multiple return paths with same type
("""
int max2(int a, int b) {
    if (a > b) { return a; }
    return b;
}
void main() {
    write_int(max2(7, 3));  # 7
}
""", ["7"]),

# void early return
("""
void ping(int n) {
    if (n < 0) { return; }
    write_int(n);
}
void main() {
    ping(9);  # 9
}
""", ["9"]),


# generic function
("""
array<T> to_array<T>(T value) {
    return [value];
 }
 void main() {
    array<int> arr = to_array<int>(42);
    write_int(arr.get(0));
 }
""", ["42"]),

]

@pytest.mark.parametrize("src,expected", ok_cases)
def test_functions_ok(src, expected):
    assert run_muni(src) == expected


# ---------------------------
# Compile-time errors
# ---------------------------

compile_err_cases = [
# returning a value from void
("""
void foo() {
    return 1;
}
 void main() {}
""", "Cannot return a value from void function"),

# using void function in expression
("""
void foo() { }
void main() {
    int x = foo();  # void in expression
}
""", "void"),

# wrong return type (returning char/string/etc. — here: int vs. void mismatch also OK)
("""
int foo() {
    return "Hello";
}
void main() {}
""", "type"),

# missing return on some path in non-void function
("""
int foo(int a) {
    if (a > 0) { return a; }
    # no return here
}
 void main() {}
""", "may exit without returning"),

# too few args
("""
int add(int a, int b) { return a + b; }
void main() {
    write_int(add(1));  # missing arg
}
""", "expects 2 arguments, got 1"),

# too many args
("""
int add(int a, int b) { return a + b; }
void main() {
    write_int(add(1, 2, 3));  # extra arg
}
""", "expects 2 arguments, got 3"),

# wrong arg type (pass void result as arg)
("""
void noop() {}
int inc(int x) { return x + 1; }
void main() {
    write_int(inc(noop()));  # type mismatch
}
""", "expected int, got void"),

# duplicate function definition
("""
int foo() { return 1; }
int foo() { return 2; }
 void main() {}
""", "redefinition"),

# main with wrong signature (non-void return or params)
("""
int main() {
    return 0;
}
""", "main"),
(
"""
void main(int x) {
}
""", "main"),
]

@pytest.mark.parametrize("src,needle", compile_err_cases)
def test_functions_compile_errors(src, needle):
    msg = compile_error(src)
    assert needle.lower() in msg.lower()

