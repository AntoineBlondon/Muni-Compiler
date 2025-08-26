import pytest
from muni_test import run_muni, compile_error, runtime_error

# ---------------------------
# OK cases
# ---------------------------

ok_cases = [
("""
void main() {
    print("Hello, world!");
}""", ["Hello, world!"]),

("""
void main() {}
""", []),
]

@pytest.mark.parametrize("src,expected", ok_cases)
def test_arithmetics_ok(src, expected):
    assert run_muni(src) == expected


# ---------------------------
# ERR cases
# ---------------------------

compile_err_cases = [
("""
""", "Missing 'main' function"),

("""
int main() {
    return 0;
}
""", "Invalid 'main' function signature: 'main' must return void"),

("""
void main(int a) {
    write_int(a);
}
""", "Invalid 'main' function signature: 'main' must have no parameters"),

]

@pytest.mark.parametrize("src,needle", compile_err_cases)
def test_arithmetics_compile_errors(src, needle):
    msg = compile_error(src)
    assert needle in msg
