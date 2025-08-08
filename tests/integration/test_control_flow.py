from muni_test import *

# Each tuple is (muni_source, [expected_stdout_lines])
cases = [
    ("""
    void main() {
        int g = 0;
        for (; g < 0; g = g + 1) { }
        write_int(g);
    }
    """, ["0"]),

    ("""
    void main() {
        int cnt = 0;
        for (int i = 0; i < 4; i = i + 1) {
            cnt = cnt + 1;
        }
        write_int(cnt);
    }
    """, ["4"]),

    ("""
    void main() {
        int s = 0;
        for (int i = 0; i < 6; i = i + 2) {
            s = s + i;
        }
        write_int(s);
    }
    """, ["6"]),

    ("""
    void main() {
        int f = 0;
        for (; f < 3; ) {
            f = f + 1;
        }
        write_int(f);
    }
    """, ["3"]),

    ("""
    void main() {
        int d = 0;
        for (; d < 3; d = d + 1) {
            break;
        }
        write_int(d);
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
        write_int(sum);
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
        write_int(sum);
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
        write_int(sum);
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
        write_int(sum);
    }
    """, ["0"]),

    ("""
    void main() {
        int sum = 0;
        for (int i = 0; i < 10; i = i + 1) {
        } else {
            sum = -1;
        }
        write_int(sum);
    }
    """, ["-1"]),

    ("""
    void main() {
        for (;true;) {break;}
        write_int(1);
     
    }
     """, ["1"]),
    
    ("""

    void main() {
        int sum = 0;
        while (sum != 5) {
            sum = sum + 1;
        }
        write_int(sum);
     }

""", ["5"]),

    ("""

    void main() {
        while (true) {
            break;
        }
        write_int(1);
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
        write_int(sum);
    }
}

""", ["2", "4", "6", "8", "10"]),

("""
void main() {
    int sum = 0;
    until (sum >= 5) {
        sum = sum + 1;
    }
 write_int(sum);
}

""", ["5"]),

("""
void main() {
    until (false) {
        break;
    }
 write_int(-6);
}

""", ["-6"]),

("""
void main() {
    until (false) {
        break;
    }
 write_int(-6);
}

""", ["-6"]),

("""
void main() {
    until (false) {
        break;
    } else {
    write_int(1);
 }
 write_int(8);
}

""", ["8"]),


("""
void main() {
    int x = 0;
    until (x == 2) {
        x = x + 1; 
    } else {
    write_int(4);
 }
 write_int(5);
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
 write_int(sum);
}

""", ["25"]),


("""
void main() {
    do {
    write_int(1);
    }
    write_int(2);
}

""", ["1", "2"]),


("""
void main() {
    do {
        write_int(1);
    } else {
        write_int(3);
    }
    write_int(2);
}

""", ["1", "3", "2"]),


("""
void main() {
    do {
        write_int(1);
        break;
    } else {
        write_int(3);
    }
    write_int(2);
}

""", ["1", "2"]),

("""
void main() {
    int i = 0;
    do 0 {
        i = i + 1;
    }
    write_int(i);
}

""", ["0"]),

("""
void main() {
    int i = 0;
    do 1 {
        i = i + 1;
    }
    write_int(i);
}

""", ["1"]),

("""
void main() {
    int i = 0;
    do 3 {
        i = i + 1;
    }
    write_int(i);
}

""", ["3"]),

]

@pytest.mark.parametrize("src,expected", cases)
def test_control_flow(src, expected):
    lines = run_muni(src)
    assert lines == expected
