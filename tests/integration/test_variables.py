from muni_test import *

@pytest.fixture(scope="module")
def lines():
    return run_muni("tests/integration/test_variables.mun")


cases = [
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

""",  ["1", "1", "2", "5", "10"]),   # a = 1
    ("""
void main()
{
    boolean flag = true;
    if (flag) { write_int(1); } else { write_int(0); }
    flag = false;
    if (flag) { write_int(1); } else { write_int(0); }
     
}
""",  ["1", "0"]),
    ("""
void main()
{
    int x = 0;
    write_int(x);
    x = x + 1;
    write_int(x);
    int y = x + 10;
    write_int(y);
    y = y - 5;
    write_int(y);
}

""",  ["0", "1", "11", "6"]),
    ("""
void main() 
{
    int a = 10;
    int b = 5;
    int y = 6;
    boolean cmp = a > b;
    if (cmp) {
        write_int(1);
     } else {
        write_int(0);
     }
    boolean cmp2 = y == 6;
    if (cmp2) {
        write_int(1);
     } else {
        write_int(0);
     }
    boolean cmp3 = y != 6;
    if (cmp3) {
        write_int(1);
     } else {
        write_int(0);
     }
}


""", ["1", "1", "0"]),
    ("""
void main()
{
    int a = 10;
    int a2 = -a;
    write_int(a2);
}
""", ["-10"]),
    ("""
void main()
{
    boolean cmp = true;
    boolean notcmp = !cmp;
    if (notcmp) { write_int(1); } else { write_int(0); }
}
""", ["0"]),
    ("""
void main()
{
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
    ("""
void main()
{
     int nm = -5 % 3;
     write_int(nm);
     int negmod = -(5 % 3);
     write_int(nm);
}

""", ["-2", "-2"]),
]


@pytest.mark.parametrize("src,expected", cases)
def test_variables(src, expected):
    lines = run_muni(src)
    assert lines == expected
