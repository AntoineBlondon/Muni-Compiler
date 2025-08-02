from muni_test import *

cases = [
    ("""
void main() {
if (true && false) { print(1); } else { print(0); }
if (true && true) { print(1); } else { print(0); }
if (false && false) { print(1); } else { print(0); }
if (true || false) { print(1); } else { print(0); }
if (false || false) { print(1); } else { print(0); }
if (!true) { print(1); } else { print(0); }
if (!false) { print(1); } else { print(0); }
if (1 < 2) { print(1); } else { print(0); }
if (2 < 2) { print(1); } else { print(0); }
if (2 <= 2) { print(1); } else { print(0); }
if (3 >= 4) { print(1); } else { print(0); }
if (3 > 4) { print(1); } else { print(0); }
if (3 != 4) { print(1); } else { print(0); }
if (4 == 4) { print(1); } else { print(0); }
if (1 + 1 == 2) { print(1); } else { print(0); }
if ((1 < 2) && (2 < 3)) { print(1); } else { print(0); }
if ((1 < 2) || (3 < 2)) { print(1); } else { print(0); }
if (!false && true) { print(1); } else { print(0); }
if (!false || false) { print(1); } else { print(0); }
if (!(true && false)) { print(1); } else { print(0); }
}
"""
, ["0","1","0","1","0","0","1","1","0","1","0","0","1","1","1","1","1","1","1","1",])
]


@pytest.mark.parametrize("src,expected", cases)
def test_boolean(src, expected):
    lines = run_muni(src)
    assert lines == expected
