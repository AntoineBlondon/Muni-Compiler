from muni_test import *

cases = [
    ("""
void main() {
    write_int(1 + 2 * 3);
    write_int((1 + 2) * 3);
    write_int(10 - 3 - 2);
    write_int(10 - (3 - 2));
    write_int(12 / 3);
    write_int(13 / 5);
    write_int(13 % 5);


    write_int(0 + 0);
    write_int(-1 + 2);
    write_int(1 + -2);


    write_int(0 - 0);
    write_int(-1 - 2);
    write_int(2 - -1);


    write_int(0 * 5);
    write_int(-2 * 3);
    write_int(2 * -3);


    write_int(0 / 1);
    write_int(5 / -2);
    write_int(-5 / 2);


    write_int(-5 % 2);
    write_int(5 % -2);
}

""",["7","9","5","9","4","2","3","0","1","-1","0","-3","3","0","-6","-6","0","-2","-2","-1","1"])]



@pytest.mark.parametrize("src,expected", cases)
def test_arithmetic(src, expected):
    lines = run_muni(src)
    assert lines == expected
