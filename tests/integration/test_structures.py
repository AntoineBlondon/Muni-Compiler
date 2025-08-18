import pytest
from muni_test import run_muni, compile_error

point = """
structure Point {
    static int originX = 0;
    static int originY = 0;

    int x;
    int y;

    Point(int x, int y) { this.x = x; this.y = y; }

    static Point origin() { return Point(Point.originX, Point.originY); }

    int sum() { return this.x + this.y; }
}
"""



# --- success cases: (src, expected_stdout_lines)
ok_cases = [
# array<struct> get/set and field reads
(point + """
void main() {
    array<Point> points = array<Point>(3);
    points.set(0, Point(1, 2));
    points.set(1, Point(3, 4));
    points.set(2, Point(5, 6));
    write_int(points.get(0).x);
    write_int(points.get(0).y);
    write_int(points.get(1).x);
    write_int(points.get(1).y);
    write_int(points.get(2).x);
    write_int(points.get(2).y);
}""", ["1","2","3","4","5","6"]),

# static factory + instance method
(point + """
void main() {
    Point p = Point.origin();
    write_int(p.x);
    write_int(p.y);
    write_int(p.sum());
}""", ["0","0","0"]),

# direct static field access and use in expressions
(point + """
void main() {
    write_int(Point.originX);
    write_int(Point.originY);
    Point p = Point(Point.originX + 7, Point.originY + 9);
    write_int(p.x);
    write_int(p.y);
}""", ["0","0","7","9"]),

# generic static method in non generic struct
("""
structure ArrayCreator {
    static array<T> create_array<T>(int size, T base_value) {
        array<T> a = array<T>(size);
        for (int i = 0; i < size; i = i + 1) {
            a.set(i, base_value);
        }
        return a;
    }
}
void main() {
    array<int> arr = ArrayCreator.create_array<int>(5, 42);
    for (int i = 0; i < arr.length; i = i + 1) {
        write_int(arr.get(i));
    }
}""", ["42","42","42","42","42"]),
]

@pytest.mark.parametrize("src,expected", ok_cases)
def test_structures_ok(src, expected):
    assert run_muni(src) == expected

# --- error cases: (src, substring to find in compiler error)
err_cases = [
# assigning to a static field should be rejected
(point + """
void main() {
    Point.originX = 42;
}""", "Cannot assign to static field"),

# accessing an unknown field should name available fields
(point + """
void main() {
    Point p = Point(1,2);
    write_int(p.z);
}""", "Field 'z' not found in struct 'Point'"),

# calling a static method on an instance should error
(point + """
void main() {
    Point p = Point(1,2);
    p.origin();   # origin is static
}""", "Cannot call static method 'origin'"),

# calling an instance method as static should error
(point + """
void main() {
    write_int(Point.sum());
}""", "No static method 'sum'"),

# using a struct name as a value should be an undefined identifier
(point + """
void main() {
    write_int(Point); # not an expression/value
}""", "Undefined identifier: Point"),
]

@pytest.mark.parametrize("src,needle", err_cases)
def test_structures_errors(src, needle):
    msg = compile_error(src)
    assert needle in msg
