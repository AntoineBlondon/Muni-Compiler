from muni_test import *

# Each tuple is (muni_source, [expected_stdout_lines])
cases = [


("""
void main() {
    array<int> x = array<int>(3);
    x.set(0, 1);
    x.set(1, 2);
    x.set(2, 3);
    print(x.get(0));
    print(x.get(1));
    print(x.get(2));
    print(x.length);
}
""", ["1", "2", "3", "3"]),
    

("""
void main() {
    array<int> x = [4, 5, 6, 7];
    print(x.length);
    print(x.get(0));
    print(x.get(1));
    print(x.get(2));
}
""", ["4", "4", "5", "6"]),
    


]

@pytest.mark.parametrize("src,expected", cases)
def test_arrays(src, expected):
    lines = run_muni(src)
    assert lines == expected
