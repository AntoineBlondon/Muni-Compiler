from wasmtime import Memory
import sys

def string_from_pointer(mem: Memory, store, ptr: int) -> str:
    # layout of `struct vec<char> { array<char> data; int size; int capacity; }`
    #   0..4   data.length     (i32)
    #   4..8   data.buffer     (i32) — pointer to first char’s i32 slot
    #   8..12  size            (i32)
    #  12..16  capacity        (i32)
    # --------------------------------------------------------------------
    data_ptr = int.from_bytes(mem.read(store, ptr, ptr + 4), 'little')
    size = int.from_bytes(mem.read(store, ptr + 4, ptr + 8), 'little')
    # Read buffer pointer from array struct at data_ptr+4..8
    buf_ptr = int.from_bytes(mem.read(store, data_ptr + 4, data_ptr + 8), 'little')
    # Read size*4 bytes, extract low byte of each i32
    raw = mem.read(store, buf_ptr, buf_ptr + size * 4)
    chars = bytes(raw[i] for i in range(0, len(raw), 4))
    return chars.decode('utf-8', errors='replace')


def string_to_pointer(mem: Memory, store, text: str) -> int:
    # --- constants & helpers ---
    WASM_PAGE_SIZE = 64 * 1024  # bytes per Wasm page
    # encode the string
    data = text.encode('utf-8')
    length = len(data)

    # compute current end-of-memory in bytes
    current_pages = mem.size(store)              # number of 64 KiB pages
    current_bytes = current_pages * WASM_PAGE_SIZE

    # sizes of the three allocations we need
    char_buf_bytes    = length * 4               # one i32 per char
    array_struct_bytes = 8                       # i32 length + i32 buffer_ptr
    vec_struct_bytes   = 12                      # i32 data_ptr + i32 size + i32 capacity

    total_bytes = char_buf_bytes + array_struct_bytes + vec_struct_bytes
    # how many pages to grow by?
    pages_needed = (total_bytes + WASM_PAGE_SIZE - 1) // WASM_PAGE_SIZE
    if pages_needed > 0:
        mem.grow(store, pages_needed)

    # --- carve out regions ---
    buf_ptr = current_bytes
    array_ptr = buf_ptr + char_buf_bytes
    vec_ptr = array_ptr + array_struct_bytes

    # --- write the char buffer as i32 slots ---
    for i, byte in enumerate(data):
        # write each char as a 32-bit little-endian int
        mem.write(store,
                  (byte).to_bytes(4, 'little'),
                  buf_ptr + i * 4)

    # --- write the inner array<char> struct ---
    # at array_ptr + 0: i32 length
    mem.write(store, length.to_bytes(4, 'little'), array_ptr + 0)
    # at array_ptr + 4: i32 pointer to the first char’s i32 slot
    mem.write(store, buf_ptr.to_bytes(4, 'little'),  array_ptr + 4)

    # --- write the outer vec<char> struct ---
    # at vec_ptr + 0: i32 pointer to the array<char> struct
    mem.write(store, array_ptr.to_bytes(4, 'little'), vec_ptr + 0)
    # at vec_ptr + 4: i32 size  (same as length)
    mem.write(store, length.to_bytes(4, 'little'),   vec_ptr + 4)
    # at vec_ptr + 8: i32 capacity (we’ll just set it = length for now)
    mem.write(store, length.to_bytes(4, 'little'),   vec_ptr + 8)

    return vec_ptr

def trap_oob(index, length, line, col):
    raise RuntimeError(f"array index {index} out of bounds (length {length}) at {line}:{col}")

def trap_div0(line, col):
    raise RuntimeError(f"division by zero at {line}:{col}")

def debug_i32(x: int) -> None:
    print("DBG:", x)

def wasi_write_int(x: int) -> None:
    print(x)

def wasi_write_chr(x: int) -> None:
    sys.stdout.write(chr(x))
    sys.stdout.flush()

def wasi_write_flt(x: float) -> None:
    print(x)

def get_wasi_input(memory_ref, store):
    def wasi_input() -> int:
        user_input = sys.stdin.readline()
        if memory_ref['mem'] is None:
            raise RuntimeError("Memory not available for input")
        return string_to_pointer(memory_ref['mem'], store, user_input)
    return wasi_input
