from muni_test import *

cases = [
    ("""
void main() {
    print(1 + 2 * 3);
    print((1 + 2) * 3);
    print(10 - 3 - 2);
    print(10 - (3 - 2));
    print(12 / 3);
    print(13 / 5);
    print(13 % 5);


    print(0 + 0);
    print(-1 + 2);
    print(1 + -2);


    print(0 - 0);
    print(-1 - 2);
    print(2 - -1);


    print(0 * 5);
    print(-2 * 3);
    print(2 * -3);


    print(0 / 1);
    print(5 / -2);
    print(-5 / 2);


    print(-5 % 2);
    print(5 % -2);
}

""",["7","9","5","9","4","2","3","0","1","-1","0","-3","3","0","-6","-6","0","-2","-2","-1","1"])]



@pytest.mark.parametrize("src,expected", cases)
def test_arithmetic(src, expected):
    lines = run_muni(src)
    assert lines == expected
