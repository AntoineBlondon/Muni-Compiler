from muni_test import *

@pytest.fixture(scope="module")
def lines():
    return run_muni("tests/integration/test_variables.mun")


cases = [
    ("""
void main() {

    int a = 1;     
    print(a);
    int b = a;
    print(b);
    int c = a + b;
    print(c);
    b = 5;
    print(b);
    a = b * 2;
    print(a);
     
     
}

""",  ["1", "1", "2", "5", "10"]),   # a = 1
    ("""
void main()
{
    boolean flag = true;
    if (flag) { print(1); } else { print(0); }
    flag = false;
    if (flag) { print(1); } else { print(0); }
     
}
""",  ["1", "0"]),
    ("""
void main()
{
    int x = 0;
    print(x);
    x = x + 1;
    print(x);
    int y = x + 10;
    print(y);
    y = y - 5;
    print(y);
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
        print(1);
     } else {
        print(0);
     }
    boolean cmp2 = y == 6;
    if (cmp2) {
        print(1);
     } else {
        print(0);
     }
    boolean cmp3 = y != 6;
    if (cmp3) {
        print(1);
     } else {
        print(0);
     }
}


""", ["1", "1", "0"]),
    ("""
void main()
{
    int a = 10;
    int a2 = -a;
    print(a2);
}
""", ["-10"]),
    ("""
void main()
{
    boolean cmp = true;
    boolean notcmp = !cmp;
    if (notcmp) { print(1); } else { print(0); }
}
""", ["0"]),
    ("""
void main()
{
    boolean flag = true;
    int a = 10;
    int c = 2;
    print(c % 3);
    c = c * 2 + c % 3;
    print(c);
    boolean b = (a > c) && flag;
    if (b) { print(1); } else { print(0); }
}
""", ["2", "6", "1"]),
    ("""
void main()
{
     int nm = -5 % 3;
     print(nm);
     int negmod = -(5 % 3);
     print(nm);
}

""", ["-2", "-2"]),
]


@pytest.mark.parametrize("src,expected", cases)
def test_variables(src, expected):
    lines = run_muni(src)
    assert lines == expected
