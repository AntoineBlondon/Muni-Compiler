from muni_test import *
import pytest

# ---------- OK CASES ----------
ok_cases = [
    # simple assign/update chain
    ("""
void main() {
    int a = 1;
    write_int(a);
    int b = a;
    write_int(b);
    int c = a + b;
    write_int(c);
    b = 5;
    write_int(b);
    a = b * 2;
    write_int(a);
}
""", ["1", "1", "2", "5", "10"]),

    # boolean toggling
    ("""
void main() {
    boolean flag = true;
    if (flag) { write_int(1); } else { write_int(0); }
    flag = false;
    if (flag) { write_int(1); } else { write_int(0); }
}
""", ["1", "0"]),

    # arithmetic with vars
    ("""
void main() {
    int x = 0;
    write_int(x);
    x = x + 1;
    write_int(x);
    int y = x + 10;
    write_int(y);
    y = y - 5;
    write_int(y);
}
""", ["0", "1", "11", "6"]),

    # comparisons stored in vars
    ("""
void main() {
    int a = 10;
    int b = 5;
    int y = 6;
    boolean cmp = a > b;
    if (cmp) { write_int(1); } else { write_int(0); }
    boolean cmp2 = y == 6;
    if (cmp2) { write_int(1); } else { write_int(0); }
    boolean cmp3 = y != 6;
    if (cmp3) { write_int(1); } else { write_int(0); }
}
""", ["1", "1", "0"]),

    # unary minus on var
    ("""
void main() {
    int a = 10;
    int a2 = -a;
    write_int(a2);
}
""", ["-10"]),

    # logical not on var
    ("""
void main() {
    boolean cmp = true;
    boolean notcmp = !cmp;
    if (notcmp) { write_int(1); } else { write_int(0); }
}
""", ["0"]),

    # mixed ops and updates
    ("""
void main() {
    boolean flag = true;
    int a = 10;
    int c = 2;
    write_int(c % 3);
    c = c * 2 + c % 3;
    write_int(c);
    boolean b = (a > c) && flag;
    if (b) { write_int(1); } else { write_int(0); }
}
""", ["2", "6", "1"]),

    # modulo + negation combos
    ("""
void main() {
    int nm = -5 % 3;
    write_int(nm);
    int negmod = -(5 % 3);
    write_int(nm);
}
""", ["-2", "-2"]),
]

@pytest.mark.parametrize("src,expected", ok_cases)
def test_variables_ok(src, expected):
    lines = run_muni(src)
    assert lines == expected


# ---------- ERROR CASES ----------
err_cases = [
    # redeclaration in same scope
    ("""
void main() {
    int a = 1;
    int a = 2;
}
""", "Redeclaration of 'a'"),

    # assignment to undefined variable
    ("""
void main() {
    a = 3;
}
""", "Assignment to undefined 'a'"),

    # missing initializer (non-void must be initialized)
    ("""
void main() {
    int a;
}
""", "Expected ASSIGN, got SEMI"),

    # cannot initialize void variable
    ("""
void main() {
    void v = 0;
}
""", "Cannot initialize void variable 'v'"),

    # type mismatch at declaration init
    ("""
void main() {
    int a = true;
}
""", "Cannot assign boolean to int 'a'"),

    # type mismatch on assignment
    ("""
void main() {
    int a = 0;
    a = true;
}
""", "Cannot assign boolean to int 'a'"),

    # use of undefined identifier in initializer
    ("""
void main() {
    int a = b;
}
""", "Undefined identifier: b"),
]

@pytest.mark.parametrize("src,needle", err_cases)
def test_variables_err(src, needle):
    msg = compile_error(src)
    assert needle in msg
