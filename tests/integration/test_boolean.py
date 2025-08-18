import pytest
from muni_test import run_muni, compile_error

# ---------------------------
# OK cases
# ---------------------------

ok_cases = [
# && and ||
("""
void main() {
    if (true && false) { write_int(1); } else { write_int(0); }
    if (true && true)  { write_int(1); } else { write_int(0); }
    if (true || false) { write_int(1); } else { write_int(0); }
    if (false || false){ write_int(1); } else { write_int(0); }
}""", ["0","1","1","0"]),

# unary !
("""
void main() {
    if (!true)  { write_int(1); } else { write_int(0); }
    if (!false) { write_int(1); } else { write_int(0); }
}""", ["0","1"]),

# comparisons & equality
("""
void main() {
    if (1 < 2)   { write_int(1); } else { write_int(0); }
    if (2 < 2)   { write_int(1); } else { write_int(0); }
    if (2 <= 2)  { write_int(1); } else { write_int(0); }
    if (3 >= 4)  { write_int(1); } else { write_int(0); }
    if (3 > 4)   { write_int(1); } else { write_int(0); }
    if (3 != 4)  { write_int(1); } else { write_int(0); }
    if (4 == 4)  { write_int(1); } else { write_int(0); }
}""", ["1","0","1","0","0","1","1"]),

# mixed boolean arithmetic in expressions
("""
void main() {
    if (1 + 1 == 2)            { write_int(1); } else { write_int(0); }
    if ((1 < 2) && (2 < 3))    { write_int(1); } else { write_int(0); }
    if ((1 < 2) || (3 < 2))    { write_int(1); } else { write_int(0); }
    if (!false && true)        { write_int(1); } else { write_int(0); }
    if (!false || false)       { write_int(1); } else { write_int(0); }
    if (!(true && false))      { write_int(1); } else { write_int(0); }
}""", ["1","1","1","1","1","1"]),
]

@pytest.mark.parametrize("src,expected", ok_cases)
def test_booleans_ok(src, expected):
    assert run_muni(src) == expected


# ---------------------------
# Compile-time error cases
# ---------------------------

err_cases = [
# if condition must be boolean
("""
void main() {
    if (1) { write_int(1); } else { write_int(0); }
}""", "Condition of if must be boolean"),

# logical && expects boolean, not int
("""
void main() {
    if (1 && 0) { write_int(1); } else { write_int(0); }
}""", "Logical operator '&&' expects boolean"),

# logical || expects boolean, not int
("""
void main() {
    if (1 || 0) { write_int(1); } else { write_int(0); }
}""", "Logical operator '||' expects boolean"),

# unary ! expects boolean
("""
void main() {
    if (!1) { write_int(1); } else { write_int(0); }
}""", "Unary '!' expects boolean"),

# comparison operators expect int operands (not boolean)
("""
void main() {
    if (true < false) { write_int(1); } else { write_int(0); }
}""", "Comparison operator '<' expects int"),

# == requires same types (boolean vs int)
("""
void main() {
    if (true == 1) { write_int(1); } else { write_int(0); }
}""", "expects same types"),
]

@pytest.mark.parametrize("src,needle", err_cases)
def test_booleans_compile_errors(src, needle):
    msg = compile_error(src)
    assert needle in msg
