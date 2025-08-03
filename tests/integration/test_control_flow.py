from muni_test import *

# Each tuple is (muni_source, [expected_stdout_lines])
cases = [
    ("""
    void main() {
        int g = 0;
        for (; g < 0; g = g + 1) { }
        print(g);
    }
    """, ["0"]),

    ("""
    void main() {
        int cnt = 0;
        for (int i = 0; i < 4; i = i + 1) {
            cnt = cnt + 1;
        }
        print(cnt);
    }
    """, ["4"]),

    ("""
    void main() {
        int s = 0;
        for (int i = 0; i < 6; i = i + 2) {
            s = s + i;
        }
        print(s);
    }
    """, ["6"]),

    ("""
    void main() {
        int f = 0;
        for (; f < 3; ) {
            f = f + 1;
        }
        print(f);
    }
    """, ["3"]),

    ("""
    void main() {
        int d = 0;
        for (; d < 3; d = d + 1) {
            break;
        }
        print(d);
    }
    """, ["0"]),

    ("""
    void main() {
        int sum = 0;
        for (int i = 0; i < 5; i = i + 1) {
            for (int j = 0; j < 5; j = j + 1) {
                sum = sum + 1;
            }
        }
        print(sum);
    }
    """, ["25"]),

    ("""
    void main() {
        int sum = 0;
        for (int i = 0; i < 5; i = i + 1) {
            for (int j = 0; j < 5; j = j + 1) {
                break;
            }
            sum = sum + 1;
        }
        print(sum);
    }
    """, ["5"]),

    ("""
    void main() {
        int sum = 0;
        for (int i = 0; i < 10; i = i + 1) {
            if (i % 2 != 0) {
                continue;
            }
            sum = sum + i;
        }
        print(sum);
    }
    """, ["20"]),

    ("""
    void main() {
        int sum = 0;
        for (int i = 0; i < 10; i = i + 1) {
            break;
        } else {
            sum = -1;
        }
        print(sum);
    }
    """, ["0"]),

    ("""
    void main() {
        int sum = 0;
        for (int i = 0; i < 10; i = i + 1) {
        } else {
            sum = -1;
        }
        print(sum);
    }
    """, ["-1"]),

    ("""
    void main() {
        for (;true;) {break;}
        print(1);
     
    }
     """, ["1"]),
    
    ("""

    void main() {
        int sum = 0;
        while (sum != 5) {
            sum = sum + 1;
        }
        print(sum);
     }

""", ["5"]),

    ("""

    void main() {
        while (true) {
            break;
        }
        print(1);
     }

""", ["1"]),

("""
void main() {
    int sum = 0;
    while (sum < 10) {
        sum = sum + 1;
        if (sum % 2 != 0) {
            continue;
        }
        print(sum);
    }
}

""", ["2", "4", "6", "8", "10"]),

("""
void main() {
    int sum = 0;
    until (sum >= 5) {
        sum = sum + 1;
    }
 print(sum);
}

""", ["5"]),

("""
void main() {
    until (false) {
        break;
    }
 print(-6);
}

""", ["-6"]),

("""
void main() {
    until (false) {
        break;
    }
 print(-6);
}

""", ["-6"]),

("""
void main() {
    until (false) {
        break;
    } else {
    print(1);
 }
 print(8);
}

""", ["8"]),


("""
void main() {
    int x = 0;
    until (x == 2) {
        x = x + 1; 
    } else {
    print(4);
 }
 print(5);
}

""", ["4", "5"]),

("""
void main() {
    int x = 0;
    int sum = 0;
    until (x == 10) {
        x = x + 1;
        if (x % 2 == 0) {
            continue;
        }
        sum = sum + x;
    }
 print(sum);
}

""", ["25"]),


("""
void main() {
    do {
    print(1);
    }
    print(2);
}

""", ["1", "2"]),


("""
void main() {
    do {
        print(1);
    } else {
        print(3);
    }
    print(2);
}

""", ["1", "3", "2"]),


("""
void main() {
    do {
        print(1);
        break;
    } else {
        print(3);
    }
    print(2);
}

""", ["1", "2"]),

]

@pytest.mark.parametrize("src,expected", cases)
def test_control_flow(src, expected):
    lines = run_muni(src)
    assert lines == expected
