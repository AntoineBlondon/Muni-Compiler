import pytest
from muni_test import run_muni, compile_error

# -----------------------------------------------------------------------------
# About do/while variants in Muni (docstring comment for future readers)
#
# 1) do { ... }
#    - Executes the body once.
#
# 2) do N { ... }
#    - Executes the body N times. (N must be an int; N == 0 means skip.)
#
# 3) do { ... } while (cond)
#    - Like C: executes body once, then repeats while cond is true.
#
# 4) do N { ... } while (cond)
#    - Muni upgrade: first executes the body N times, then continues
#      executing while cond is true.
#      (No semicolon after the while(...) clause in Muni.)
# -----------------------------------------------------------------------------


# ---------------------------
# for-loop OK cases
# ---------------------------

ok_for = [
# empty header parts
("""
void main() {
    int g = 0;
    for (; g < 0; g = g + 1) { }
    write_int(g);
}""", ["0"]),

# simple counting
("""
void main() {
    int cnt = 0;
    for (int i = 0; i < 4; i = i + 1) { cnt = cnt + 1; }
    write_int(cnt);
}""", ["4"]),

# step 2 and sum
("""
void main() {
    int s = 0;
    for (int i = 0; i < 6; i = i + 2) { s = s + i; }
    write_int(s);
}""", ["6"]),

# no post; increment inside
("""
void main() {
    int f = 0;
    for (; f < 3; ) { f = f + 1; }
    write_int(f);
}""", ["3"]),

# break exits immediately
("""
void main() {
    int d = 0;
    for (; d < 3; d = d + 1) { break; }
    write_int(d);
}""", ["0"]),

# nested for
("""
void main() {
    int sum = 0;
    for (int i = 0; i < 5; i = i + 1) {
        for (int j = 0; j < 5; j = j + 1) { sum = sum + 1; }
    }
    write_int(sum);
}""", ["25"]),

# break inner only; outer continues
("""
void main() {
    int sum = 0;
    for (int i = 0; i < 5; i = i + 1) {
        for (int j = 0; j < 5; j = j + 1) { break; }
        sum = sum + 1;
    }
    write_int(sum);
}""", ["5"]),

# continue in for
("""
void main() {
    int sum = 0;
    for (int i = 0; i < 10; i = i + 1) {
        if (i % 2 != 0) { continue; }
        sum = sum + i;
    }
    write_int(sum);
}""", ["20"]),

# for ... else: else skipped because of break
("""
void main() {
    int sum = 0;
    for (int i = 0; i < 10; i = i + 1) {
        break;
    } else {
        sum = -1;
    }
    write_int(sum);
}""", ["0"]),

# for ... else: else runs when loop finishes normally
("""
void main() {
    int sum = 0;
    for (int i = 0; i < 10; i = i + 1) {
    } else {
        sum = -1;
    }
    write_int(sum);
}""", ["-1"]),
]

@pytest.mark.parametrize("src,expected", ok_for)
def test_for_ok(src, expected):
    assert run_muni(src) == expected


# ---------------------------
# while / until OK cases
# ---------------------------

ok_while_until = [
# while basic
("""
void main() {
    int sum = 0;
    while (sum != 5) { sum = sum + 1; }
    write_int(sum);
}""", ["5"]),

# while with immediate break
("""
void main() {
    while (true) { break; }
    write_int(1);
}""", ["1"]),

# while with continue
("""
void main() {
    int sum = 0;
    while (sum < 10) {
        sum = sum + 1;
        if (sum % 2 != 0) { continue; }
        write_int(sum);
    }
}""", ["2","4","6","8","10"]),

# until: run until condition true
("""
void main() {
    int sum = 0;
    until (sum >= 5) { sum = sum + 1; }
    write_int(sum);
}""", ["5"]),

# until with break
("""
void main() {
    until (false) { break; }
    write_int(-6);
}""", ["-6"]),

# until ... else only runs on normal exit
("""
void main() {
    until (false) { break; } else { write_int(1); }
    write_int(8);
}""", ["8"]),

# until ... else runs when loop ends normally
("""
void main() {
    int x = 0;
    until (x == 2) { x = x + 1; } else { write_int(4); }
    write_int(5);
}""", ["4","5"]),

# until with continue aggregation
("""
void main() {
    int x = 0;
    int sum = 0;
    until (x == 10) {
        x = x + 1;
        if (x % 2 == 0) { continue; }
        sum = sum + x;
    }
    write_int(sum);
}""", ["25"]),
]

@pytest.mark.parametrize("src,expected", ok_while_until)
def test_while_until_ok(src, expected):
    assert run_muni(src) == expected


# ---------------------------
# do / do N / do ... while / do N ... while OK cases
# ---------------------------

ok_do = [
# do once
("""
void main() {
    do { write_int(1); }
    write_int(2);
}""", ["1","2"]),

# do ... else runs after the block (your semantics)
("""
void main() {
    do { write_int(1); } else { write_int(3); }
    write_int(2);
}""", ["1","3","2"]),

# do with break skips else
("""
void main() {
    do { write_int(1); break; } else { write_int(3); }
    write_int(2);
}""", ["1","2"]),

# do N with N == 0 → body skipped
("""
void main() {
    int i = 0;
    do 0 { i = i + 1; }
    write_int(i);
}""", ["0"]),

# do N = 1
("""
void main() {
    int i = 0;
    do 1 { i = i + 1; }
    write_int(i);
}""", ["1"]),

# do N = 3
("""
void main() {
    int i = 0;
    do 3 { i = i + 1; }
    write_int(i);
}""", ["3"]),

# do {..} while(cond)
("""
void main() {
    int i = 0;
    do { i = i + 1; } while (i < 3)
    write_int(i);
}""", ["3"]),

# do N {..} while(cond) → run N times then continue while(cond)
("""
void main() {
    int i = 0;
    do 2 { i = i + 1; } while (i < 5)
    write_int(i);
}""", ["5"]),
]

@pytest.mark.parametrize("src,expected", ok_do)
def test_do_ok(src, expected):
    assert run_muni(src) == expected


# ---------------------------
# Compile-time ERR cases
# ---------------------------

err_cases = [
# if/while/until conditions must be boolean
("""
void main() { if (1) { } }
""", "Condition of if must be boolean"),

("""
void main() { while (1) { } }
""", "Condition of while must be boolean"),

("""
void main() { until (1) { } }
""", "Condition of until must be boolean"),

# for condition must be boolean
("""
void main() { for (; 1; ) { } }
""", "Condition of for must be boolean"),

# do N: count must be int
("""
void main() { do true { } }
""", "Count in do‐repeat must be int, got boolean"),

# break/continue outside loop
("""
void main() { break; }
""", "'break' outside of loop"),

("""
void main() { continue; }
""", "'continue' outside of loop"),
]

@pytest.mark.parametrize("src,needle", err_cases)
def test_control_flow_compile_errors(src, needle):
    msg = compile_error(src)
    assert needle in msg
