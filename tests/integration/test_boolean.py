from muni_test import *

cases = [
    ("""
void main() {
if (true && false) { write_int(1); } else { write_int(0); }
if (true && true) { write_int(1); } else { write_int(0); }
if (false && false) { write_int(1); } else { write_int(0); }
if (true || false) { write_int(1); } else { write_int(0); }
if (false || false) { write_int(1); } else { write_int(0); }
if (!true) { write_int(1); } else { write_int(0); }
if (!false) { write_int(1); } else { write_int(0); }
if (1 < 2) { write_int(1); } else { write_int(0); }
if (2 < 2) { write_int(1); } else { write_int(0); }
if (2 <= 2) { write_int(1); } else { write_int(0); }
if (3 >= 4) { write_int(1); } else { write_int(0); }
if (3 > 4) { write_int(1); } else { write_int(0); }
if (3 != 4) { write_int(1); } else { write_int(0); }
if (4 == 4) { write_int(1); } else { write_int(0); }
if (1 + 1 == 2) { write_int(1); } else { write_int(0); }
if ((1 < 2) && (2 < 3)) { write_int(1); } else { write_int(0); }
if ((1 < 2) || (3 < 2)) { write_int(1); } else { write_int(0); }
if (!false && true) { write_int(1); } else { write_int(0); }
if (!false || false) { write_int(1); } else { write_int(0); }
if (!(true && false)) { write_int(1); } else { write_int(0); }
}
"""
, ["0","1","0","1","0","0","1","1","0","1","0","0","1","1","1","1","1","1","1","1",])
]


@pytest.mark.parametrize("src,expected", cases)
def test_boolean(src, expected):
    lines = run_muni(src)
    assert lines == expected
