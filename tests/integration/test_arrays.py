# test_arrays.py
import pytest
from muni_test import run_muni, compile_error, runtime_error

# ---------------------------
# OK cases
# ---------------------------

ok_cases = [
# construct, set/get, and length
("""
void main() {
    array<int> x = array<int>(3);
    x.set(0, 1);
    x.set(1, 2);
    x.set(2, 3);
    write_int(x.get(0));
    write_int(x.get(1));
    write_int(x.get(2));
    write_int(x.length);
}""", ["1","2","3","3"]),

# array literal (homogeneous) + basic reads
("""
void main() {
    array<int> x = [4, 5, 6, 7];
    write_int(x.length);
    write_int(x.get(0));
    write_int(x.get(1));
    write_int(x.get(2));
}""", ["4","4","5","6"]),

# overwrite via set and read back
("""
void main() {
    array<int> x = [1, 1, 1];
    x.set(1, 9);
    write_int(x.get(0));
    write_int(x.get(1));
    write_int(x.get(2));
}""", ["1","9","1"]),
]

@pytest.mark.parametrize("src,expected", ok_cases)
def test_arrays_ok(src, expected):
    assert run_muni(src) == expected


# ---------------------------
# Compile-time error cases
# ---------------------------

compile_err_cases = [
# mixed-type literal → element type check
("""
void main() {
    array<int> x = [1, true, 3];
}""", "Array elements must all be"),

# wrong constructor arity for type params
("""
void main() {
    array<int,int> x = array<int,int>(3);
}""", "Constructor 'array' expects 1 type-arg(s), got 2"),

# wrong value type in set()
("""
void main() {
    array<int> x = array<int>(1);
    x.set(0, true);
}""", "expects int, got boolean"),

# wrong index type in get()
("""
void main() {
    array<int> x = array<int>(1);
    write_int(x.get(true));
}""", "expects int, got boolean"),
]

@pytest.mark.parametrize("src,needle", compile_err_cases)
def test_arrays_compile_errors(src, needle):
    msg = compile_error(src)
    assert needle in msg


# ---------------------------
# Runtime error cases (bounds)
# ---------------------------
# We assert for "bound" in stderr to be engine-agnostic.

runtime_err_cases = [
# get OOB
("""
void main() {
    array<int> x = array<int>(2);
    x.set(0, 10);
    x.set(1, 20);
    write_int(x.get(2)); # OOB
}""", "bound"),

# set OOB
("""
void main() {
    array<int> x = array<int>(2);
    x.set(2, 99); # OOB
}""", "bound"),
]

@pytest.mark.parametrize("src,needle", runtime_err_cases)
def test_arrays_runtime_errors(src, needle):
    err = runtime_error(src).lower()
    assert needle in err  # look for "bound" (e.g., "out of bounds", "index out of bounds")
