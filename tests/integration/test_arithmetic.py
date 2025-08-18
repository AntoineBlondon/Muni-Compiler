import pytest
from muni_test import run_muni, compile_error, runtime_error

# ---------------------------
# OK cases
# ---------------------------

ok_cases = [
# precedence: * before +
("""
void main() {
    write_int(1 + 2 * 3);      # 1 + (2*3) = 7
    write_int((1 + 2) * 3);    # (1+2)*3 = 9
}""", ["7", "9"]),

# associativity: subtraction is left-associative
("""
void main() {
    write_int(10 - 3 - 2);     # (10-3)-2 = 5
    write_int(10 - (3 - 2));   # 10 - 1 = 9
}""", ["5", "9"]),

# division and modulo (positive)
("""
void main() {
    write_int(12 / 3);         # 4
    write_int(13 / 5);         # 2
    write_int(13 % 5);         # 3
}""", ["4", "2", "3"]),

# unary minus with addition/subtraction
("""
void main() {
    write_int(0 + 0);          # 0
    write_int(-1 + 2);         # 1
    write_int(1 + -2);         # -1

    write_int(0 - 0);          # 0
    write_int(-1 - 2);         # -3
    write_int(2 - -1);         # 3
}""", ["0","1","-1","0","-3","3"]),

# multiplication with negatives
("""
void main() {
    write_int(0 * 5);          # 0
    write_int(-2 * 3);         # -6
    write_int(2 * -3);         # -6
}""", ["0","-6","-6"]),

# division/modulo with negatives (Wasm trunc toward zero; rem sign = dividend)
("""
void main() {
    write_int(0 / 1);          # 0
    write_int(5 / -2);         # -2
    write_int(-5 / 2);         # -2

    write_int(-5 % 2);         # -1
    write_int(5 % -2);         # 1
}""", ["0","-2","-2","-1","1"]),
("""
void main() {
    int x = 10;
    x += 5; # 15
    x -= 3; # 12
    x *= 2; # 24
    x /= 4; # 6
    x %= 3; # 0
    write_int(x); # ((((10+5)-3)*2)/4)%3 = 0
}""", ["0"]),

("""
void main() {
    int x = 5;
    x *= 2 + 3; # 5 * (2+3) = 25
    write_int(x);
}""", ["25"]),

("""
void main() {
    int x = 3;
    x += x; # 6
    write_int(x);
    x *= x + 1; # 6 * 7 = 42
    write_int(x);
}""", ["6","42"]),

("""
void main() {
    int x = -5;
    x %= 2; # -5 % 2 = -1 (Wasm sign = dividend)
    write_int(x);
}""", ["-1"]),

("""
void main() {
    int i = 0;
    i++; # 1
    write_int(i);
    i--; # 0
    write_int(i);
}""", ["1","0"]),

("""
void main() {
    for (int i = 0; i < 3; i++) {
        write_int(i);
    }
}""", ["0","1","2"]),

("""
void main() {
    int sum = 0;
    for (int i = 3; i > 0; i--) {
        sum += i; # 3 + 2 + 1 = 6
    }
    write_int(sum);
}""", ["6"]),
]

@pytest.mark.parametrize("src,expected", ok_cases)
def test_arithmetics_ok(src, expected):
    assert run_muni(src) == expected


# ---------------------------
# ERR cases
# ---------------------------

# Compile-time type errors
compile_err_cases = [
# mismatched types on '+'
("""
void main() {
    write_int(1 + true);
}""", "expects same types"),

# boolean arithmetic with same types but not int
("""
void main() {
    # both boolean → passes same-type check, then rejected by '+ expects int'
    write_int(true + false);
}""", "expects int"),

# unary '-' on boolean
("""
void main() {
    write_int(-true);
}""", "Unary '-' expects int"),
]

@pytest.mark.parametrize("src,needle", compile_err_cases)
def test_arithmetics_compile_errors(src, needle):
    msg = compile_error(src)
    assert needle in msg


# Runtime traps (division/modulo by zero). We assert a generic 'zero' to be runner-agnostic.
runtime_err_cases = [
("""
void main() {
    write_int(1 / 0);
}""", "zero"),

("""
void main() {
    write_int(1 % 0);
}""", "zero"),
]

@pytest.mark.parametrize("src,needle", runtime_err_cases)
def test_arithmetics_runtime_errors(src, needle):
    msg = runtime_error(src)
    assert needle.lower().find(needle) != -1 or "zero" in msg.lower()
    # Simpler and more robust:
    assert "zero" in msg.lower()
