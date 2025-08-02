from muni_test import *

cases = [
    ("""
void main() {
print(true && false);
print(true && true);
print(false && false);
print(true || false);
print(false || false);
print(!true);
print(!false);
print(1 < 2);
print(2 < 2);
print(2 <= 2);
print(3 >= 4);
print(3 > 4);
print(3 != 4);
print(4 == 4);
print(1 + 1 == 2);
print((1 < 2) && (2 < 3));
print((1 < 2) || (3 < 2));
print(!false && true);
print(!false || false);
print(!(true && false));
}
"""
, ["0","1","0","1","0","0","1","1","0","1","0","0","1","1","1","1","1","1","1","1",])
]


@pytest.mark.parametrize("src,expected", cases)
def test_boolean(src, expected):
    lines = run_muni(src)
    assert lines == expected
